import { base64url, compactDecrypt } from "jose";

export type ShlPayload = {
  manifestPath: string;
  key: Uint8Array;
  flag: "L" | "P";
  label: string;
  exp?: number;
};

type WirePayload = { url?: unknown; key?: unknown; flag?: unknown; label?: unknown; v?: unknown; exp?: unknown };

/** Remove the secret-bearing fragment before any network request or rendering. */
export function takeShlFragment(location: Location, history: History): string {
  const fragment = location.hash;
  history.replaceState(null, "", location.pathname + location.search);
  return fragment;
}

/** Restrict resolution to this site's manifest endpoint, without URL credentials or queries. */
export function decodeShlFragment(fragment: string, origin: string): ShlPayload {
  if (!fragment.startsWith("#shlink:/") || fragment.length > 4096) throw new Error("Invalid SHL");
  const decoded = new TextDecoder("utf-8", { fatal: true }).decode(
    base64url.decode(fragment.slice("#shlink:/".length)),
  );
  const wire: WirePayload = JSON.parse(decoded);
  if (wire.v !== 1 || typeof wire.url !== "string" || typeof wire.key !== "string" ||
    typeof wire.label !== "string" || (wire.flag !== "L" && wire.flag !== "P")) {
    throw new Error("Invalid SHL");
  }
  const target = new URL(wire.url);
  if (target.origin !== origin || !/^\/api\/shl\/m\/[A-Za-z0-9_-]{43}$/.test(target.pathname) ||
    target.search !== "" || target.hash !== "" || target.username !== "" || target.password !== "") {
    throw new Error("Foreign SHL origin");
  }
  const key = base64url.decode(wire.key);
  if (key.length !== 32) throw new Error("Invalid SHL");
  if (wire.exp !== undefined && (typeof wire.exp !== "number" || wire.exp <= 0)) throw new Error("Invalid SHL");
  return { manifestPath: target.pathname, key, flag: wire.flag, label: wire.label, exp: wire.exp as number | undefined };
}

export type FhirResource = Record<string, unknown> & { resourceType: string };
export type FhirBundle = { resourceType: "Bundle"; type: string; entry?: {resource?: FhirResource}[] };

/** Decrypt each embedded JWE in memory and accept only FHIR Bundles. */
export async function decryptFiles(files: {embedded: string}[], key: Uint8Array): Promise<FhirBundle[]> {
  const bundles: FhirBundle[] = [];
  for (const file of files) {
    const { plaintext, protectedHeader } = await compactDecrypt(file.embedded, key);
    if (protectedHeader.alg !== "dir" || protectedHeader.enc !== "A256GCM") throw new Error("Invalid JWE");
    const parsed: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(plaintext));
    if (!parsed || typeof parsed !== "object" || !("resourceType" in parsed) ||
      parsed.resourceType !== "Bundle" || !("type" in parsed) ||
      (parsed.type !== "document" && parsed.type !== "collection")) throw new Error("Invalid FHIR Bundle");
    bundles.push(parsed as FhirBundle);
  }
  return bundles;
}
