import { describe, expect, it } from "vitest";
import { base64url, CompactEncrypt } from "jose";
import { decodeShlFragment, decryptFiles, takeShlFragment } from "./shl";

const origin = "https://firstlook-hy-demo.duckdns.org";
const key = new Uint8Array(32).fill(7);

function fragment(url: string) {
  const payload = { url, key: base64url.encode(key), flag: "L", label: "FirstLook", v: 1 };
  return `#shlink:/${base64url.encode(JSON.stringify(payload))}`;
}

describe("SMART Health Link client", () => {
  it("accepts only the configured manifest origin", () => {
    const valid = fragment(`${origin}/api/shl/m/${"a".repeat(43)}`);
    expect(decodeShlFragment(valid, origin).key).toEqual(key);
    expect(() => decodeShlFragment(fragment(`https://other.example/api/shl/m/${"a".repeat(43)}`), origin)).toThrow();
    expect(() => decodeShlFragment(fragment(`${origin}/api/shl/m/${"a".repeat(43)}?x=1`), origin)).toThrow();
  });

  it("decrypts a compact dir/A256GCM FHIR Bundle", async () => {
    const plaintext = new TextEncoder().encode(JSON.stringify({ resourceType: "Bundle", type: "collection", entry: [] }));
    const embedded = await new CompactEncrypt(plaintext).setProtectedHeader({ alg: "dir", enc: "A256GCM" }).encrypt(key);
    expect((await decryptFiles([{ embedded }], key))[0].type).toBe("collection");
  });

  it("removes the key-bearing fragment before any manifest request can be made", () => {
    const secret = fragment(`${origin}/api/shl/m/${"a".repeat(43)}`);
    const calls: string[] = [];
    const location = { hash: secret, pathname: "/s", search: "" } as Location;
    const history = { replaceState: (_state: unknown, _unused: string, url: string) => { calls.push(url); } } as unknown as History;
    expect(takeShlFragment(location, history)).toBe(secret);
    expect(calls).toEqual(["/s"]);
  });
});
