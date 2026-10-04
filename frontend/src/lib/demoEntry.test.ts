import { describe, expect, it } from "vitest";
import { validateDemoViewerUrl } from "./demoEntry";

const origin = "https://firstlook-hy-demo.duckdns.org";

describe("demo entry", () => {
  it("accepts the same-origin fragment link", () => {
    const url = `${origin}/s#shlink:/payload`;
    expect(validateDemoViewerUrl(url, origin)).toBe(url);
  });

  it("rejects foreign hosts and key-bearing queries", () => {
    expect(() => validateDemoViewerUrl("https://foreign.example/s#shlink:/payload", origin)).toThrow();
    expect(() => validateDemoViewerUrl(`${origin}/s?key=secret#shlink:/payload`, origin)).toThrow();
    expect(() => validateDemoViewerUrl(`${origin}/s`, origin)).toThrow();
  });
});
