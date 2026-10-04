import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, apiResponse, getPrincipal, jsonBody } from "../lib/api";
import { resourceLabel, type BaselineSummary, type Locale } from "../lib/clinical";
import type { FhirBundle, FhirResource } from "../lib/shl";
import { BaselineView, EmergencyView } from "../components/EmergencyView";
import { LoginPanel } from "../components/LoginPanel";
import { RegisterPanel } from "../components/RegisterPanel";
import { Shell } from "../components/Shell";
import { Badge, Button, Card, Field, Toggle } from "../components/ui";

type Profile = { name: {given: string; family: string}; birth_date: string | null; flags: {id: string; text_key: string}[]; essentials: {items: string[]; show_sex: boolean} };
type Item = {resource: FhirResource; provenance: {source: string}};
type Link = {id: string; kind: string; status: string; url: string | null};
type Access = {seq: number; time: string; actor_type: string; role: string; tier: string; action: string; outcome: string};
type ImportStatus = {id: string; status: string; preview: {add_count?: number; update_count?: number; conflict_count?: number} | null};

const sections = ["allergies", "medications", "conditions", "devices"] as const;

function PatientContent({demo}: {demo: boolean}) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const profile = useQuery({ queryKey: ["patient-profile"], queryFn: () => api<Profile>("/api/v1/patients/me") });
  const links = useQuery({ queryKey: ["patient-links"], queryFn: () => api<Link[]>("/api/v1/patients/me/links") });
  const access = useQuery({ queryKey: ["patient-access"], queryFn: () => api<Access[]>("/api/v1/patients/me/access-log") });
  const baseline = useQuery({ queryKey: ["patient-baseline"], queryFn: () => api<BaselineSummary>("/api/v1/patients/me/baseline") });
  const consents = useQuery({ queryKey: ["patient-consents"], queryFn: () => api<Record<string, boolean>>("/api/v1/patients/me/consents") });
  const records = useQuery({ queryKey: ["patient-records"], queryFn: async () => {
    const rows = await Promise.all(sections.map(async (section) => ({ section, items: await api<Item[]>(`/api/v1/patients/me/${section}`) })));
    return rows;
  } });
  const [selected, setSelected] = useState<string[] | null>(null);
  const [showSex, setShowSex] = useState<boolean | null>(null);
  const [preview, setPreview] = useState<FhirBundle | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [importKind, setImportKind] = useState("activity_csv");
  const [file, setFile] = useState<File | null>(null);
  const [importId, setImportId] = useState<string | null>(null);
  const [importState, setImportState] = useState<ImportStatus | null>(null);
  const [newSection, setNewSection] = useState<typeof sections[number]>("medications");
  const [newItem, setNewItem] = useState("");
  const [given, setGiven] = useState<string | null>(null);
  const [family, setFamily] = useState<string | null>(null);
  const [birthDate, setBirthDate] = useState<string | null>(null);
  const [carrierUrl, setCarrierUrl] = useState<string | null>(null);

  useEffect(() => {
    const stream = new EventSource("/api/v1/patients/me/notifications/stream", { withCredentials: true });
    stream.addEventListener("access", () => { void qc.invalidateQueries({ queryKey: ["patient-access"] }); });
    return () => stream.close();
  }, [qc]);
  useEffect(() => {
    if (!importId) return;
    const timer = window.setInterval(() => {
      void api<ImportStatus>(`/api/v1/imports/${importId}`).then((result) => {
        setImportState(result);
        if (["parsed", "failed", "committed"].includes(result.status)) window.clearInterval(timer);
      }).catch(() => window.clearInterval(timer));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [importId]);
  useEffect(() => () => { if (carrierUrl) URL.revokeObjectURL(carrierUrl); }, [carrierUrl]);

  async function run(work: () => Promise<void>) {
    setBusy(true); setError(false);
    try { await work(); } catch { setError(true); }
    finally { setBusy(false); }
  }
  async function showQr(link: Link) {
    await run(async () => {
      const response = await apiResponse(`/api/v1/patients/me/links/${link.id}/carriers/qr.svg`);
      const objectUrl = URL.createObjectURL(await response.blob());
      setCarrierUrl(objectUrl);
    });
  }
  const activeLink = links.data?.find((item) => item.kind === "emergency" && item.status === "active");
  const choices = [
    ...(profile.data?.flags ?? []).map((flag) => ({id: `flag:${flag.id}`, label: t(flag.text_key)})),
    ...(records.data ?? []).flatMap(({items}) => items.map(({resource}) => ({
      id: String(resource.id ?? ""),
      label: resourceLabel(resource, i18n.language.slice(0, 2) as Locale, t),
    }))),
  ].filter((item) => item.id);
  const selectedItems = selected ?? profile.data?.essentials.items ?? [];
  const sex = showSex ?? profile.data?.essentials.show_sex ?? false;

  return <Shell><div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div>
      <h1 className="text-3xl font-black">{t("patient.title")}</h1>
      {profile.data && <p className="subtle">{profile.data.name.given} {profile.data.name.family}</p>}
    </div><Button variant="outline" onClick={() => void run(async () => { await api("/api/v1/auth/logout", { method: "POST" }); qc.clear(); window.location.assign("/"); })}>{t("common.signOut")}</Button></div>
    {(error || profile.isError) && <p role="alert" className="critical-band rounded-xl p-4">{t("common.error")}</p>}
    <div className="grid gap-5 lg:grid-cols-2">
      <Card className="space-y-4"><h2 className="text-xl font-black">{t("patient.identity")}</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field id="given" label={t("patient.given")} value={given ?? profile.data?.name.given ?? ""} onChange={(event) => setGiven(event.target.value)} maxLength={100} />
          <Field id="family" label={t("patient.family")} value={family ?? profile.data?.name.family ?? ""} onChange={(event) => setFamily(event.target.value)} maxLength={100} />
          <Field id="birth-date" label={t("patient.birthDate")} type="date" value={birthDate ?? profile.data?.birth_date ?? ""} onChange={(event) => setBirthDate(event.target.value)} />
        </div>
        <Button disabled={busy || !(given ?? profile.data?.name.given)?.trim() || !(family ?? profile.data?.name.family)?.trim()} onClick={() => void run(async () => {
          await api("/api/v1/patients/me/identity", {method: "PUT", body: jsonBody({given: (given ?? profile.data?.name.given)?.trim(), family: (family ?? profile.data?.name.family)?.trim(), birth_date: birthDate ?? profile.data?.birth_date ?? null})});
          await qc.invalidateQueries({queryKey: ["patient-profile"]});
        })}>{t("common.save")}</Button>
      </Card>
      <Card className="space-y-4"><h2 className="text-xl font-black">{t("patient.link")}</h2>
        <p className="subtle text-sm">{t("patient.qrHint")}</p>
        {activeLink ? <>
          <Button variant="outline" onClick={() => void showQr(activeLink)}>{t("patient.link")}</Button>
          {carrierUrl && <img src={carrierUrl} alt={t("patient.link")} className="mx-auto max-w-[260px] bg-white p-3" />}
          <div className="flex flex-wrap gap-2">
            <a className="inline-flex min-h-12 items-center rounded-xl border px-4 py-2 text-sm font-bold" href={`/api/v1/patients/me/links/${activeLink.id}/carriers/cards.pdf`} download>{t("patient.print")}</a>
            <a className="inline-flex min-h-12 items-center rounded-xl border px-4 py-2 text-sm font-bold" href={`/api/v1/patients/me/links/${activeLink.id}/carriers/wallpaper-1170.png`} download>{t("patient.wallpaper")}</a>
            <Button variant="outline" disabled={busy} onClick={() => void run(async () => { await api(`/api/v1/patients/me/links/${activeLink.id}/rotate`, { method: "POST" }); setCarrierUrl(null); await qc.invalidateQueries({ queryKey: ["patient-links"] }); })}>{t("patient.rotate")}</Button>
            <Button variant="danger" disabled={busy} onClick={() => { if (window.confirm(t("patient.revokeConfirm"))) void run(async () => { await api(`/api/v1/patients/me/links/${activeLink.id}`, { method: "DELETE" }); setCarrierUrl(null); await qc.invalidateQueries({ queryKey: ["patient-links"] }); }); }}>{t("patient.revoke")}</Button>
          </div>
        </> : <Button disabled={busy} onClick={() => void run(async () => { await api("/api/v1/patients/me/links", { method: "POST", body: jsonBody({kind: "emergency"}) }); await qc.invalidateQueries({ queryKey: ["patient-links"] }); })}>{t("patient.link")}</Button>}
      </Card>
      <Card className="space-y-4"><h2 className="text-xl font-black">{t("patient.essentials")}</h2>
        <p className="subtle text-sm">{t("patient.essentialsHint")}</p>
        <fieldset className="space-y-2"><legend className="sr-only">{t("patient.essentials")}</legend>
          {choices.map((item) => <label key={item.id} className="flex min-h-11 items-center gap-3 rounded-lg p-1"><input className="h-5 w-5" type="checkbox" checked={selectedItems.includes(item.id)} onChange={() => setSelected(selectedItems.includes(item.id) ? selectedItems.filter((id) => id !== item.id) : [...selectedItems, item.id])} />{item.label}</label>)}
        </fieldset>
        <Toggle checked={sex} onCheckedChange={setShowSex} label={t("patient.includeSex")} />
        <div className="flex flex-wrap gap-2"><Button disabled={busy} onClick={() => void run(async () => { await api("/api/v1/patients/me/essentials", { method: "PUT", body: jsonBody({items: selectedItems, show_sex: sex}) }); await qc.invalidateQueries({ queryKey: ["patient-profile"] }); })}>{t("patient.saveEssentials")}</Button>
          <Button variant="outline" onClick={() => void run(async () => setPreview(await api<FhirBundle>("/api/v1/patients/me/essentials/preview")))}>{t("patient.preview")}</Button></div>
      </Card>
    </div>
    {preview && <EmergencyView bundle={preview} essentials />}
    <div className="grid gap-5 lg:grid-cols-2">
      <Card className="space-y-3"><h2 className="text-xl font-black">{t("patient.access")}</h2>
        {access.data?.length ? <ol className="space-y-2" aria-live="polite">{access.data.map((item) => <li key={item.seq} className="surface-muted rounded-lg p-3">
          <div className="flex justify-between gap-2"><strong>{t(`access.actor.${item.role}`, {defaultValue: t("access.actor.other")})}</strong><Badge>{item.tier}</Badge></div>
          <span className="text-sm">{new Date(item.time).toLocaleString(i18n.language)} · {t(`access.action.${item.action}`, {defaultValue: t("access.action.other")})} · {t(`access.outcome.${item.outcome}`, {defaultValue: item.outcome})}</span>
        </li>)}</ol> : <p className="subtle">{t("patient.noAccess")}</p>}
      </Card>
      <Card className="space-y-3"><h2 className="text-xl font-black">{t("patient.consent")}</h2>
        {([ ["essentials_content", "patient.consent.essentials"], ["wearable_baseline", "patient.consent.baseline"], ["ed_prealert", "patient.consent.prealert"] ] as const).map(([kind, label]) =>
          <Toggle key={kind} checked={consents.data?.[kind] ?? false} label={t(label)} onCheckedChange={(granted) => void run(async () => { await api(`/api/v1/patients/me/consents/${kind}`, { method: "PUT", body: jsonBody({granted}) }); await qc.invalidateQueries({ queryKey: ["patient-consents"] }); })} />)}
      </Card>
    </div>
    <BaselineView baseline={baseline.data ?? null} />
    <Card className="space-y-3"><h2 className="text-xl font-black">{t("patient.import")}</h2>
      <p className="subtle text-sm">{t("patient.importHint")}</p>
      <div className="flex flex-wrap gap-3"><div><label htmlFor="import-kind" className="mb-1 block text-sm font-bold">{t("patient.importType")}</label>
        <select id="import-kind" className="field" value={importKind} onChange={(e) => setImportKind(e.target.value)}><option value="activity_csv">CSV</option><option value="activity_json">JSON</option><option value="synthetic_ikp">Synthetic IKP</option></select></div>
        <input type="file" accept=".csv,.json" className="field max-w-xs" onChange={(e) => setFile(e.target.files?.[0] ?? null)} aria-label={t("patient.import")} /></div>
      <Button disabled={busy || !file} onClick={() => void run(async () => { const form = new FormData(); form.set("kind", importKind); form.set("file", file!); const created = await api<{id: string}>("/api/v1/imports", { method: "POST", body: form }); setImportId(created.id); setImportState(null); })}>{t("patient.upload")}</Button>
      {importState && <div role="status">{importState.status === "parsed" ? t("patient.importReady") : importState.status === "failed" ? t("patient.importFailed") : t("patient.importPending")}
        {importState.preview && <p className="text-sm">{importState.preview.add_count ?? 0} {t("patient.importAdded")} · {importState.preview.update_count ?? 0} {t("patient.importUpdated")} · {importState.preview.conflict_count ?? 0} {t("patient.importConflicts")}</p>}
        {importState.status === "parsed" && <Button disabled={busy} onClick={() => void run(async () => { await api(`/api/v1/imports/${importState.id}/commit`, { method: "POST" }); setImportState({...importState, status: "committed"}); await qc.invalidateQueries({ queryKey: ["patient-baseline"] }); await qc.invalidateQueries({ queryKey: ["patient-records"] }); })}>{t("patient.commit")}</Button>}
      </div>}
    </Card>
    <Card className="space-y-3"><h2 className="text-xl font-black">{t("patient.sections")}</h2>
      <div className="grid gap-3 sm:grid-cols-2">{records.data?.map(({section, items}) => <section key={section} className="surface-muted p-3"><h3 className="mb-2 font-bold">{t(`patient.${section}`)}</h3>
        {items.map(({resource}) => <p className="mb-1" key={String(resource.id)}>{resourceLabel(resource, i18n.language.slice(0, 2) as Locale, t)}</p>)}
        {items.length === 0 && <p className="subtle text-sm">{t("common.empty")}</p>}
      </section>)}</div>
      <div className="flex flex-wrap items-end gap-3"><div><label htmlFor="new-section" className="mb-1 block text-sm font-bold">{t("patient.sections")}</label>
        <select id="new-section" className="field" value={newSection} onChange={(e) => setNewSection(e.target.value as typeof sections[number])}>{sections.map((section) => <option key={section} value={section}>{t(`patient.${section}`)}</option>)}</select></div>
        <div><label htmlFor="new-item" className="mb-1 block text-sm font-bold">{t("patient.freeText")}</label>
          <input id="new-item" className="field" maxLength={200} value={newItem} onChange={(e) => setNewItem(e.target.value)} /></div>
        <Button disabled={busy || !newItem.trim()} onClick={() => void run(async () => {
          const text = newItem.trim();
          const payload = newSection === "medications" ? {free_text: text} : newSection === "allergies"
            ? {resourceType: "AllergyIntolerance", clinicalStatus: {text: "active"}, code: {text}}
            : newSection === "conditions" ? {resourceType: "Condition", clinicalStatus: {text: "active"}, code: {text}}
              : {resourceType: "Device", type: {text}, status: "active"};
          await api(`/api/v1/patients/me/${newSection}`, {method: "POST", body: jsonBody(payload)});
          setNewItem(""); await qc.invalidateQueries({queryKey: ["patient-records"]}); await qc.invalidateQueries({queryKey: ["patient-profile"]});
        })}>{t("patient.add")}</Button></div>
    </Card>
    {demo && profile.data?.name.given === "Marco" && profile.data.name.family === "Rossi" && <Button variant="outline" disabled={busy} onClick={() => void run(async () => { await api("/api/v1/demo/sync/marco", { method: "POST" }); await qc.invalidateQueries({ queryKey: ["patient-baseline"] }); })}>{t("patient.sync")}</Button>}
  </div></Shell>;
}

export function PatientApp() {
  const { t } = useTranslation();
  const me = useQuery({ queryKey: ["principal"], queryFn: getPrincipal, retry: false });
  if (me.isLoading) return <Shell><p>{t("common.loading")}</p></Shell>;
  if (me.data?.role !== "patient") return <Shell><div className="grid gap-5 lg:grid-cols-2"><LoginPanel role="patient" onSuccess={() => void me.refetch()} /><RegisterPanel /></div></Shell>;
  return <PatientContent demo={me.data.tenant === "demo"} />;
}
