import { AlertTriangle, Activity, HeartPulse } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { baselineFromBundle, patientName, resourceLabel, resources, type BaselineSummary, type Locale } from "../lib/clinical";
import type { FhirBundle } from "../lib/shl";
import { Badge, Card } from "./ui";

const sections = [
  ["AllergyIntolerance", "emergency.allergies"],
  ["Device", "emergency.devices"],
  ["MedicationStatement", "emergency.medications"],
  ["Condition", "emergency.conditions"],
] as const;

function metricName(metric: string, t: (key: string) => string): string {
  const key = `baseline.${metric}`;
  return t(key) === key ? metric : t(key);
}

export function BaselineView({ baseline }: {baseline: BaselineSummary | null}) {
  const { t, i18n } = useTranslation();
  const [windowDays, setWindowDays] = useState(7);
  if (!baseline || baseline.metrics.length === 0) return null;
  const steps = (baseline.series ?? []).filter((row) => row.metric === "steps").slice(-7);
  const metrics = baseline.metrics.filter((row) => row.window_days === windowDays);
  const values = steps.map((row) => row.value);
  const floor = Math.min(...values);
  const ceiling = Math.max(...values);
  const points = steps.map((row, index) => `${(index / (steps.length - 1)) * 300},${90 - ((row.value - floor) / (ceiling - floor || 1)) * 70}`).join(" ");
  return <Card className="space-y-4">
    <div className="flex items-center gap-2"><Activity aria-hidden="true" /><h2 className="text-xl font-black">{t("emergency.baseline")}</h2></div>
    <p className="subtle text-sm">{t("emergency.indicative")}</p>
    {baseline.last_sync_at && <p className="text-sm">{t("baseline.lastSync")}: {new Date(baseline.last_sync_at).toLocaleString(i18n.language)}</p>}
    {baseline.last_activity_at && <p className="text-sm">{t("baseline.lastActivity")}: {new Date(baseline.last_activity_at).toLocaleString(i18n.language)}</p>}
    <div className="flex flex-wrap gap-2" role="group" aria-label={t("emergency.baseline")}>{[7, 30, 365].map((days) =>
      <button key={days} className="min-h-11 rounded-lg border px-3 font-semibold aria-pressed:bg-[#0f1115] aria-pressed:text-white dark:aria-pressed:bg-[#f1f2f3] dark:aria-pressed:text-[#0f1115]" aria-pressed={windowDays === days} onClick={() => setWindowDays(days)}>{t("baseline.days", {count: days})}</button>)}</div>
    <div className="grid gap-3 sm:grid-cols-2">
      {metrics.map((row) => <div key={row.metric} className="surface-muted p-3">
        <div className="flex flex-wrap items-center justify-between gap-2"><strong>{metricName(row.metric, t)}</strong>
          <Badge tone={row.classification === "within" ? "good" : "neutral"}>{t(`baseline.${row.classification}`)}</Badge></div>
        <p className="mt-2 text-lg font-bold">{row.today === null ? "—" : new Intl.NumberFormat(i18n.language).format(row.today)} <span className="text-xs font-normal">{row.unit}</span></p>
        <p className="subtle text-xs">{t(row.hour_fraction != null ? "baseline.partialRange" : "baseline.days", {count: windowDays})}: {Math.round(row.low * (row.hour_fraction ?? 1))}–{Math.round(row.high * (row.hour_fraction ?? 1))} {row.unit}</p>
      </div>)}
    </div>
    {steps.length > 1 && <>
      <svg viewBox="0 0 300 100" preserveAspectRatio="none" className="h-28 w-full stroke-[#0f1115] dark:stroke-[#f1f2f3]" aria-hidden="true"><polyline points={points} fill="none" strokeWidth="3" vectorEffect="non-scaling-stroke" /></svg>
      <table className="sr-only"><caption>{metricName("steps", t)}</caption><tbody>{steps.map((row) => <tr key={row.day}><th scope="row">{row.day}</th><td>{row.value}</td></tr>)}</tbody></table>
    </>}
  </Card>;
}

export function EmergencyView({ bundle, baselineBundle, baseline, essentials = false }: {
  bundle: FhirBundle; baselineBundle?: FhirBundle | null; baseline?: BaselineSummary | null; essentials?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const locale: Locale = i18n.language.startsWith("pl") ? "pl" : i18n.language.startsWith("it") ? "it" : "en";
  const flags = resources(bundle, "Flag");
  const name = patientName(bundle);
  return <div className="space-y-4">
    <Card className="border-l-[6px] border-l-[#c62828]">
      <div className="mb-3 flex items-center gap-2 text-[#a72024] dark:text-[#ff8989]"><AlertTriangle aria-hidden="true" /><h2 className="text-xl font-black">{t("emergency.critical")}</h2></div>
      {name && <p className="mb-3 text-lg font-bold">{name}</p>}
      {flags.length > 0 && <div className="mb-3 flex flex-wrap gap-2">{flags.map((flag, index) => <Badge key={index} tone="critical">{resourceLabel(flag, locale, t)}</Badge>)}</div>}
      {resources(bundle, "AllergyIntolerance").length > 0 && <div>
        <h3 className="font-bold">{t("emergency.allergies")}</h3>
        <ul className="mt-1 list-inside list-disc">{resources(bundle, "AllergyIntolerance").map((item, index) => <li key={index}>{resourceLabel(item, locale, t)}</li>)}</ul>
      </div>}
    </Card>
    <div className="grid gap-4 md:grid-cols-2">
      {sections.map(([type, title]) => {
        const items = resources(bundle, type);
        // In Essentials, an omitted section means the patient did not select
        // it. Do not describe that as "no recorded items".
        if (items.length === 0 && (essentials || type === "AllergyIntolerance")) return null;
        return <Card key={type}><h2 className="mb-3 flex items-center gap-2 text-lg font-black"><HeartPulse size={20} aria-hidden="true" />{t(title)}</h2>
          {items.length ? <ul className="space-y-2">{items.map((item, index) => <li key={index} className="surface-muted rounded-lg p-3">{resourceLabel(item, locale, t)}</li>)}</ul> : <p className="subtle text-sm">{t("emergency.noData")}</p>}
        </Card>;
      })}
    </div>
    {essentials && <p className="subtle text-sm">{t("emergency.fullOnly")}</p>}
    <BaselineView baseline={baseline ?? (baselineBundle ? baselineFromBundle(baselineBundle) : null)} />
  </div>;
}
