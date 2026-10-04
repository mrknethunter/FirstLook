import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ApiError, api, apiResponse, getPrincipal, jsonBody } from "../lib/api";
import { decodeShlFragment, decryptFiles, takeShlFragment, type FhirBundle, type ShlPayload } from "../lib/shl";
import { EmergencyView } from "../components/EmergencyView";
import { LoginPanel } from "../components/LoginPanel";
import { Shell } from "../components/Shell";
import { Button, Card, Field } from "../components/ui";

type Manifest = { files: {embedded: string}[]; status: string };
type Facility = {id: string; name: string};

function initialLink(): {link: ShlPayload | null; foreign: boolean} {
  const fragment = takeShlFragment(window.location, window.history);
  try { return {link: decodeShlFragment(fragment, window.location.origin), foreign: false}; }
  catch (error) { return {link: null, foreign: error instanceof Error && error.message === "Foreign SHL origin"}; }
}

function HandoffForm({ session }: {session: string}) {
  const { t } = useTranslation();
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [facility, setFacility] = useState("");
  const [eta, setEta] = useState("15");
  const [priority, setPriority] = useState("yellow");
  const [heartRate, setHeartRate] = useState("");
  const [bloodPressure, setBloodPressure] = useState("");
  const [spo2, setSpo2] = useState("");
  const [notes, setNotes] = useState("");
  const [status, setStatus] = useState<"idle" | "pending" | "sent" | "error">("idle");
  const idempotencyKey = useRef(crypto.randomUUID());
  useEffect(() => { void api<Facility[]>("/api/v1/facilities?type=ed").then(setFacilities).catch(() => setStatus("error")); }, []);
  async function submit(event: FormEvent) {
    event.preventDefault(); setStatus("pending");
    const observations: Record<string, string | number> = {};
    if (heartRate) observations.heart_rate = Number(heartRate);
    if (bloodPressure) observations.blood_pressure = bloodPressure;
    if (spo2) observations.spo2 = Number(spo2);
    try {
      await api("/api/v1/handoffs", {
        method: "POST",
        headers: { "FL-Emergency-Session": session, "Idempotency-Key": idempotencyKey.current },
        body: jsonBody({ facility_id: facility, eta_minutes: Number(eta), priority, observations, notes: notes || null }),
      });
      setStatus("sent");
    } catch { setStatus("error"); }
  }
  return <Card className="space-y-4">
    <h2 className="text-xl font-black">{t("handoff.title")}</h2>
    {status === "sent" ? <p role="status" className="font-bold text-[#125e4c]">{t("handoff.sent")}</p> : <form className="space-y-4" onSubmit={submit}>
      <div><label className="mb-1 block text-sm font-bold" htmlFor="facility">{t("handoff.facility")}</label>
        <select id="facility" className="field" required value={facility} onChange={(e) => setFacility(e.target.value)}>
          <option value="">—</option>{facilities.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id="eta" label={t("handoff.eta")} type="number" min={0} max={1440} required value={eta} onChange={(e) => setEta(e.target.value)} />
        <div><label className="mb-1 block text-sm font-bold" htmlFor="priority">{t("handoff.priority")}</label>
          <select id="priority" className="field" value={priority} onChange={(e) => setPriority(e.target.value)}>
            {["red", "orange", "yellow", "green"].map((item) => <option key={item} value={item}>{t(`handoff.${item}`)}</option>)}
          </select></div>
        <Field id="heart-rate" label={t("handoff.heartRate")} type="number" min={0} value={heartRate} onChange={(e) => setHeartRate(e.target.value)} />
        <Field id="blood-pressure" label={t("handoff.bloodPressure")} value={bloodPressure} maxLength={32} onChange={(e) => setBloodPressure(e.target.value)} />
        <Field id="spo2" label={t("handoff.spo2")} type="number" min={0} max={100} value={spo2} onChange={(e) => setSpo2(e.target.value)} />
      </div>
      <div><label className="mb-1 block text-sm font-bold" htmlFor="notes">{t("handoff.notes")}</label>
        <textarea id="notes" className="field min-h-24" maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
      {status === "error" && <p role="alert" className="text-sm text-[#ad2335]">{t("common.error")}</p>}
      <Button type="submit" disabled={status === "pending" || !facility}>{t("handoff.send")}</Button>
    </form>}
  </Card>;
}

export function ShlViewer() {
  const { t } = useTranslation();
  const [{link, foreign}] = useState(initialLink);
  const [reason, setReason] = useState("");
  const [acknowledge, setAcknowledge] = useState(false);
  const [passcode, setPasscode] = useState("");
  const [loggedIn, setLoggedIn] = useState(false);
  const [showLogin, setShowLogin] = useState(false);
  const [bundle, setBundle] = useState<FhirBundle | null>(null);
  const [baseline, setBaseline] = useState<FhirBundle | null>(null);
  const [session, setSession] = useState<string | null>(null);
  const [tier, setTier] = useState<"essentials" | "full">("essentials");
  const [pending, setPending] = useState(false);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  useEffect(() => { void getPrincipal().then((principal) => { if (principal?.role === "responder") setLoggedIn(true); }).catch(() => {}); }, []);

  async function open(mode: "break_glass" | "responder" | "passcode") {
    if (!link) return;
    setPending(true); setErrorStatus(null);
    try {
      const body = mode === "break_glass" ? { fl_mode: mode, fl_reason: reason.trim(), fl_acknowledge: acknowledge }
        : mode === "responder" ? { fl_mode: mode } : { passcode };
      const response = await apiResponse(link.manifestPath, { method: "POST", body: jsonBody(body) });
      const result = await response.json() as Manifest;
      const decoded = await decryptFiles(result.files, link.key);
      if (!decoded[0]) throw new Error("Missing IPS");
      setBundle(decoded[0]); setBaseline(decoded[1] ?? null);
      const emergencySession = response.headers.get("FL-Emergency-Session");
      setSession(emergencySession);
      setTier(link.flag === "P" || emergencySession ? "full" : "essentials");
    } catch (error) { setErrorStatus(error instanceof ApiError ? error.status : 500); }
    finally { setPending(false); }
  }

  return <Shell compact><div className="mx-auto max-w-3xl space-y-5">
    <h1 className="text-3xl font-black">{t("viewer.title")}</h1>
    {!link ? <Card><p role="alert">{t(foreign ? "viewer.originWarning" : "viewer.invalid")}</p></Card> : bundle ? <>
      <EmergencyView bundle={bundle} baselineBundle={baseline} essentials={tier === "essentials"} />
      {tier === "full" && session && <HandoffForm session={session} />}
      <Button variant="outline" onClick={() => { setBundle(null); setBaseline(null); setSession(null); }}>{t("emergency.stop")}</Button>
    </> : <>
      <Card><p>{t("viewer.scanNotice")}</p></Card>
      {link.flag === "P" ? <Card className="space-y-4">
        <h2 className="text-xl font-black">{t("viewer.openShare")}</h2>
        <Field id="passcode" label={t("viewer.passcode")} type="password" value={passcode} onChange={(e) => setPasscode(e.target.value)} />
        <Button disabled={pending || !passcode} onClick={() => void open("passcode")}>{t("viewer.openShare")}</Button>
      </Card> : <>
        <Card className="space-y-4">
          <h2 className="text-xl font-black">{t("viewer.breakglass")}</h2>
          <p className="subtle text-sm">{t("viewer.breakglassHint")}</p>
          <div><label className="mb-1 block text-sm font-bold" htmlFor="reason">{t("viewer.reason")}</label>
            <textarea id="reason" className="field min-h-24" minLength={10} maxLength={280} value={reason} onChange={(e) => setReason(e.target.value)} aria-describedby="reason-hint" />
            <p id="reason-hint" className="subtle text-xs">{t("viewer.reasonHint")}</p></div>
          <label className="flex items-start gap-3 text-sm"><input type="checkbox" className="mt-1 h-5 w-5" checked={acknowledge} onChange={(e) => setAcknowledge(e.target.checked)} />{t("viewer.ack")}</label>
          <Button disabled={pending || !acknowledge || reason.trim().length < 10} onClick={() => void open("break_glass")}>{t("viewer.openEssentials")}</Button>
        </Card>
        <Card className="space-y-4">
          <h2 className="text-xl font-black">{t("viewer.responder")}</h2>
          <p className="subtle text-sm">{t("viewer.responderHint")}</p>
          {loggedIn ? <Button disabled={pending} onClick={() => void open("responder")}>{t("viewer.responder")}</Button>
            : showLogin ? <LoginPanel role="responder" onSuccess={() => { void getPrincipal().then((principal) => { if (principal?.role === "responder") setLoggedIn(true); else setErrorStatus(403); }).catch(() => setErrorStatus(403)); }} />
              : <Button variant="outline" onClick={() => setShowLogin(true)}>{t("common.signIn")}</Button>}
        </Card>
      </>}
      {errorStatus && <p role="alert" className="rounded-xl border border-[#ad2335] p-4 text-[#ad2335]">{t(errorStatus === 429 ? "viewer.limit" : errorStatus === 404 ? "viewer.invalid" : "viewer.denied")}</p>}
    </>}
    <Link className="subtle underline" to="/">{t("nav.home")}</Link>
  </div></Shell>;
}
