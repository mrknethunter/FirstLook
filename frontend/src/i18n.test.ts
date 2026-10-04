import { describe, expect, it, vi } from "vitest";

vi.stubGlobal("document", {documentElement: {lang: "en"}});

const { default: i18n } = await import("./i18n");

describe("demo languages", () => {
  it("has a nonempty translation for every demo key in English, Polish and Italian", () => {
    const english = i18n.getResourceBundle("en", "translation") as Record<string, string>;
    for (const locale of ["pl", "it"]) {
      const translated = i18n.getResourceBundle(locale, "translation") as Record<string, string>;
      expect(Object.keys(translated).sort()).toEqual(Object.keys(english).sort());
      expect(Object.values(translated).every((value) => value.trim().length > 0)).toBe(true);
    }
  });
});
