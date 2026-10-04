/** Validate the demo entry response before navigating to a fragment-key URL. */
export function validateDemoViewerUrl(value: unknown, origin: string): string {
  if (typeof value !== "string") throw new Error("Invalid demo entry");
  const parsed = new URL(value);
  if (
    parsed.origin !== origin ||
    parsed.pathname !== "/s" ||
    parsed.search !== "" ||
    !parsed.hash.startsWith("#shlink:/") ||
    parsed.username !== "" ||
    parsed.password !== ""
  ) {
    throw new Error("Invalid demo entry");
  }
  return value;
}
