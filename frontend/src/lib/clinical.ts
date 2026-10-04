import type { FhirBundle, FhirResource } from "./shl";

export type Locale = "en" | "pl" | "it";

// These five curated displays mirror the source-backed rows in docs/TERMINOLOGY.md.
const displays: Record<string, Record<Locale, string>> = {
  "http://www.whocc.no/atc|B01AF02": { en: "apixaban", pl: "apiksaban", it: "apixaban" },
  "http://www.whocc.no/atc|A10BA02": { en: "metformin", pl: "metformina", it: "metformina" },
  "http://www.whocc.no/atc|M01AE01": { en: "ibuprofen", pl: "ibuprofen", it: "ibuprofene" },
  "http://hl7.org/fhir/sid/icd-10|E10": { en: "type 1 diabetes", pl: "cukrzyca typu 1", it: "diabete di tipo 1" },
  "http://snomed.info/sct|14106009": { en: "cardiac pacemaker", pl: "rozrusznik serca", it: "pacemaker cardiaco" },
};

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function resources(bundle: FhirBundle | null, type: string): FhirResource[] {
  return (bundle?.entry ?? []).map((entry) => entry.resource).filter(
    (item): item is FhirResource => Boolean(item && item.resourceType === type),
  );
}

export function patientName(bundle: FhirBundle | null): string {
  const patient = resources(bundle, "Patient")[0];
  if (!patient) return "";
  const first = Array.isArray(patient.name) ? object(patient.name[0]) : {};
  if (typeof first.text === "string") return first.text;
  const given = Array.isArray(first.given) ? first.given.filter((part): part is string => typeof part === "string").join(" ") : "";
  return [given, typeof first.family === "string" ? first.family : ""].filter(Boolean).join(" ");
}

function concept(resource: FhirResource): Record<string, unknown> {
  return object(resource.medicationCodeableConcept ?? resource.code ?? resource.type);
}

export function resourceLabel(resource: FhirResource, locale: Locale, translate: (key: string) => string): string {
  const coded = concept(resource);
  if (resource.resourceType === "Flag" && typeof coded.text === "string") return translate(coded.text);
  const coding = Array.isArray(coded.coding) ? object(coded.coding[0]) : {};
  if (typeof coding.system === "string" && typeof coding.code === "string") {
    const local = displays[`${coding.system}|${coding.code}`]?.[locale];
    if (local) return local;
  }
  const extensions = Array.isArray(resource.extension) ? resource.extension.map(object) : [];
  if (resource.resourceType === "Device" && (coded.text === "insulin pump" || coded.text === "pompa per insulina")) return translate("device.insulinPump");
  if (resource.resourceType === "MedicationStatement" && coded.text === "insulina (formulazione non specificata)") return translate("med.insulinUnspecified");
  if (extensions.some((item) => item.valueString === "insulin_pump")) return translate("flags.insulin_pump");
  if (extensions.some((item) => item.valueString === "A10A")) return translate("med.insulinUnspecified");
  if (typeof coded.text === "string") return coded.text;
  if (typeof coding.display === "string") return coding.display;
  if (typeof coding.code === "string") return coding.code;
  return "—";
}

export type BaselineMetric = { metric: string; unit: string; window_days: number; low: number; high: number; median: number; today: number | null; classification: string; hour_fraction?: number | null };
export type BaselineSummary = { status: string; label?: string; last_sync_at?: string | null; last_activity_at?: string | null; metrics: BaselineMetric[]; series?: {day: string; metric: string; value: number}[] };

export function baselineFromBundle(bundle: FhirBundle | null): BaselineSummary {
  const metrics: BaselineMetric[] = [];
  const series: {day: string; metric: string; value: number}[] = [];
  let sync: unknown;
  let activity: unknown;
  for (const row of resources(bundle, "Observation")) {
    const coded = object(row.code);
    const coding = Array.isArray(coded.coding) ? object(coded.coding[0]) : {};
    const metric = typeof coding.code === "string" ? coding.code : "";
    const quantity = object(row.valueQuantity);
    const unit = typeof quantity.unit === "string" ? quantity.unit : "";
    if (typeof row.effectiveDateTime === "string" && typeof quantity.value === "number") {
      series.push({ day: row.effectiveDateTime, metric, value: quantity.value });
      continue;
    }
    const extension = Array.isArray(row.extension) ? row.extension.map(object) : [];
    sync ??= extension.find((item) => item.url === "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/baseline-last-sync-at")?.valueDateTime;
    activity ??= extension.find((item) => item.url === "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/baseline-last-activity-at")?.valueDateTime;
    const window = extension.find((item) => item.url === "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/baseline-window-days")?.valueInteger;
    const classification = extension.find((item) => item.url === "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/baseline-classification")?.valueCode;
    const fraction = extension.find((item) => item.url === "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/baseline-hour-fraction")?.valueDecimal;
    const range = Array.isArray(row.referenceRange) ? object(row.referenceRange[0]) : {};
    const low = object(range.low).value;
    const high = object(range.high).value;
    if (typeof window !== "number" || typeof low !== "number" || typeof high !== "number") continue;
    const today = typeof quantity.value === "number" ? quantity.value : null;
    metrics.push({
      metric, unit: unit || String(object(range.low).unit ?? ""), window_days: window,
      low, high, median: (low + high) / 2, today,
      classification: classification === "below" || classification === "within" || classification === "above" ? classification : "insufficient_data",
      hour_fraction: typeof fraction === "number" && fraction > 0 && fraction <= 1 ? fraction : null,
    });
  }
  return { status: metrics.length ? "available" : "insufficient_data", metrics, series,
    last_sync_at: typeof sync === "string" ? sync : null,
    last_activity_at: typeof activity === "string" ? activity : null };
}
