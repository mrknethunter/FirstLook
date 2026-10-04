import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { FhirBundle } from "../lib/shl";
import { baselineFromBundle, resourceLabel } from "../lib/clinical";

vi.stubGlobal("document", { documentElement: { lang: "en" } });

const { default: i18n } = await import("../i18n");
const { EmergencyView } = await import("./EmergencyView");

describe("live Essentials presentation", () => {
  it("does not claim an unselected medication section has no recorded items", () => {
    const bundle: FhirBundle = {
      resourceType: "Bundle",
      type: "collection",
      entry: [{ resource: { resourceType: "Flag", code: { text: "flags.insulin" } } }],
    };

    const html = renderToStaticMarkup(<EmergencyView bundle={bundle} essentials />);
    expect(html).toContain("Insulin recorded");
    expect(html).not.toContain("No recorded items");
    expect(html).not.toContain("Medications");
  });

  it("localises the safe T1 insulin-pump label", () => {
    const device = { resourceType: "Device", type: { text: "insulin pump" } };
    for (const [locale, expected] of [
      ["pl", "pompa insulinowa"],
      ["it", "pompa per insulina"],
    ] as const) {
      const strings = i18n.getResourceBundle(locale, "translation") as Record<string, string>;
      expect(resourceLabel(device, locale, (key) => strings[key] ?? key)).toBe(expected);
    }
  });

  it("localises Marco's uncoded source text in the full view", () => {
    const strings = i18n.getResourceBundle("en", "translation") as Record<string, string>;
    const translate = (key: string) => strings[key] ?? key;
    expect(resourceLabel({resourceType: "Device", type: {text: "pompa per insulina"}}, "en", translate)).toBe("insulin pump");
    expect(resourceLabel({resourceType: "MedicationStatement", medicationCodeableConcept: {text: "insulina (formulazione non specificata)"}}, "en", translate)).toBe("Insulin (product not specified)");
  });

  it("uses the server's partial-day classification in the FHIR baseline", () => {
    const bundle: FhirBundle = {resourceType: "Bundle", type: "collection", entry: [{resource: {resourceType: "Observation", code: {coding: [{code: "steps"}]}, valueQuantity: {value: 50, unit: "count"}, referenceRange: [{low: {value: 90}, high: {value: 110}}], extension: [
      {url: "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/baseline-window-days", valueInteger: 7},
      {url: "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/baseline-classification", valueCode: "within"},
      {url: "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/baseline-hour-fraction", valueDecimal: 0.5},
      {url: "https://firstlook-hy-demo.duckdns.org/fhir/StructureDefinition/baseline-last-sync-at", valueDateTime: "2026-10-04T08:00:00Z"},
    ]}}]};
    const result = baselineFromBundle(bundle);
    expect(result.metrics[0]).toMatchObject({classification: "within", hour_fraction: 0.5});
    expect(result.last_sync_at).toBe("2026-10-04T08:00:00Z");
  });
});
