import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, getPrincipal } from "../lib/api";
import { EmergencyView } from "../components/EmergencyView";
import { LoginPanel } from "../components/LoginPanel";
import { Shell } from "../components/Shell";
import { Badge, Button, Card } from "../components/ui";
import type { BaselineSummary } from "../lib/clinical";
import type { FhirBundle } from "../lib/shl";

type Handoff = {id: string; status: string; priority: string; eta_minutes: number; facility_id: string};
type Detail = Handoff & {observations: Record<string, unknown>; notes: string | null; ips: FhirBundle; baseline: BaselineSummary};
const observationLabels: Record<string, string> = {
  heart_rate: "handoff.heartRate", blood_pressure: "handoff.bloodPressure", spo2: "handoff.spo2",
  respiratory_rate: "handoff.respiratoryRate", temperature: "handoff.temperature",
  glucose: "handoff.glucose", gcs: "handoff.gcs", avpu: "handoff.avpu",
};

function BoardContent() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const board = useQuery({queryKey: ["ed-board"], queryFn: () => api<Handoff[]>("/api/v1/ed/board"), refetchInterval: 60_000});
  const detail = useQuery({queryKey: ["ed-detail", selected], queryFn: () => api<Detail>(`/api/v1/ed/handoffs/${selected}`), enabled: Boolean(selected)});
  useEffect(() => {
    const stream = new EventSource("/api/v1/ed/board/stream", {withCredentials: true});
    stream.addEventListener("refresh", () => { void qc.invalidateQueries({queryKey: ["ed-board"]}); if (selected) void qc.invalidateQueries({queryKey: ["ed-detail", selected]}); });
    return () => stream.close();
  }, [qc, selected]);
  async function advance(action: "ack" | "arrive" | "close" | "cancel") {
    if (!selected) return;
    setError(false);
    try {
      await api(`/api/v1/ed/handoffs/${selected}/${action}`, {method: "POST"});
      await qc.invalidateQueries({queryKey: ["ed-board"]});
      if (action === "close" || action === "cancel") setSelected(null);
      else await qc.invalidateQueries({queryKey: ["ed-detail", selected]});
    } catch { setError(true); }
  }
  return <Shell><div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="text-3xl font-black">{t("ed.title")}</h1><p className="subtle">{t("ed.live")}</p></div>
      <Button variant="outline" onClick={() => { void api("/api/v1/auth/logout", {method: "POST"}).then(() => { qc.clear(); window.location.assign("/"); }); }}>{t("common.signOut")}</Button></div>
    {(error || board.isError || detail.isError) && <p role="alert" className="critical-band rounded-xl p-4">{t("common.error")}</p>}
    <div className="grid gap-4 lg:grid-cols-[minmax(17rem,1fr)_2fr]">
      <Card className="space-y-3"><h2 className="text-xl font-black">{t("ed.title")}</h2>
        {board.isPending && <p>{t("common.loading")}</p>}
        {board.data?.length === 0 && <p className="subtle">{t("ed.empty")}</p>}
        <ul className="space-y-2" aria-live="polite">{board.data?.map((item) => <li key={item.id}>
          <button onClick={() => setSelected(item.id)} className="surface-muted w-full rounded-xl p-4 text-left hover:border-[#c62828]" aria-current={selected === item.id ? "true" : undefined}>
            <div className="flex items-center justify-between gap-2"><strong>{t(`ed.${item.status}`)}</strong><Badge tone={item.priority === "red" ? "critical" : "neutral"}>{t(`handoff.${item.priority}`)}</Badge></div>
            <p className="mt-1 text-sm">{t("handoff.eta")}: {item.eta_minutes}</p>
          </button>
        </li>)}</ul>
      </Card>
      {selected && detail.data ? <div className="space-y-4">
        <Card className="space-y-3"><h2 className="text-xl font-black">{t("ed.open")}</h2>
          <div className="flex flex-wrap gap-2"><Badge tone={detail.data.priority === "red" ? "critical" : "neutral"}>{t(`handoff.${detail.data.priority}`)}</Badge><Badge>{t(`ed.${detail.data.status}`)}</Badge></div>
          <p>{t("handoff.eta")}: {detail.data.eta_minutes}</p>
          <h3 className="font-bold">{t("ed.observations")}</h3>
          <dl className="grid grid-cols-2 gap-2">{Object.entries(detail.data.observations ?? {}).map(([key, value]) => <div key={key} className="surface-muted rounded-lg p-2"><dt className="text-xs font-bold">{t(observationLabels[key] ?? key)}</dt><dd>{String(value)}</dd></div>)}</dl>
          {detail.data.notes && <p className="whitespace-pre-wrap text-sm">{detail.data.notes}</p>}
          <div className="flex flex-wrap gap-2">
            {detail.data.status === "pre_alerted" && <Button onClick={() => void advance("ack")}>{t("ed.ack")}</Button>}
            {detail.data.status === "acknowledged" && <Button onClick={() => void advance("arrive")}>{t("ed.arrive")}</Button>}
            {detail.data.status === "arrived" && <Button onClick={() => void advance("close")}>{t("ed.close")}</Button>}
            {detail.data.status !== "arrived" && <Button variant="outline" onClick={() => void advance("cancel")}>{t("ed.cancel")}</Button>}
          </div>
        </Card>
        <EmergencyView bundle={detail.data.ips} baseline={detail.data.baseline} />
      </div> : <Card><p className="subtle">{t("ed.open")}</p></Card>}
    </div>
  </div></Shell>;
}

export function EdBoard() {
  const { t } = useTranslation();
  const me = useQuery({queryKey: ["principal"], queryFn: getPrincipal, retry: false});
  if (me.isLoading) return <Shell><p>{t("common.loading")}</p></Shell>;
  if (me.data?.role !== "ed_staff") return <Shell><LoginPanel role="ed" onSuccess={() => void me.refetch()} /></Shell>;
  return <BoardContent />;
}
