import { expect, test, type Page } from "@playwright/test";
import { base64url, CompactEncrypt } from "jose";

const origin = "http://127.0.0.1:4173";
const manifestId = "m".repeat(43);
const linkId = "11111111-1111-4111-8111-111111111111";
const handoffId = "22222222-2222-4222-8222-222222222222";
const sessionId = "33333333-3333-4333-8333-333333333333";
const facilityId = "44444444-4444-4444-8444-444444444444";
const key = new Uint8Array(32).fill(7);

const essentials = {resourceType: "Bundle", type: "document", entry: [
  {resource: {resourceType: "Patient", name: [{text: "M.R."}]}},
  {resource: {resourceType: "Flag", code: {text: "flags.insulin_pump"}}},
]};
const full = {resourceType: "Bundle", type: "document", entry: [
  {resource: {resourceType: "Patient", name: [{text: "Marco Rossi"}]}},
  {resource: {resourceType: "Flag", code: {text: "flags.insulin_pump"}}},
  {resource: {resourceType: "AllergyIntolerance", code: {coding: [{system: "http://www.whocc.no/atc", code: "M01AE01"}]}}},
  {resource: {resourceType: "Condition", code: {coding: [{system: "http://hl7.org/fhir/sid/icd-10", code: "E10"}]}}},
]};
const baseline = {resourceType: "Bundle", type: "collection", entry: []};

async function encrypted(bundle: object) {
  return await new CompactEncrypt(new TextEncoder().encode(JSON.stringify(bundle)))
    .setProtectedHeader({alg: "dir", enc: "A256GCM"}).encrypt(key);
}

function viewerUrl() {
  const payload = {url: `${origin}/api/shl/m/${manifestId}`, key: base64url.encode(key), flag: "L", label: "FirstLook", v: 1};
  return `${origin}/s#shlink:/${base64url.encode(JSON.stringify(payload))}`;
}

async function mockApi(page: Page) {
  const state: {role: string | null; revoked: boolean; access: boolean; handoff: {status: string; priority: string; eta_minutes: number; facility_id: string; id: string} | null} = {
    role: null, revoked: false, access: false, handoff: null,
  };
  const t1 = await encrypted(essentials);
  const t2 = await encrypted(full);
  const metrics = await encrypted(baseline);
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => route.fulfill({status, contentType: "application/json", headers, body: JSON.stringify(body)});
    if (path === "/api/v1/demo/entry") return json({viewer_url: viewerUrl()});
    if (path === "/api/v1/auth/csrf") return json({csrf_token: "test-csrf"});
    if (path === "/api/v1/me") return state.role ? json({user_id: linkId, tenant: "demo", role: state.role, org_id: facilityId, locale: "pl", theme: "light", mfa_passed: true}) : json({}, 401);
    if (path === "/api/v1/auth/login" && method === "POST") {
      const body = request.postDataJSON() as {email: string};
      state.role = body.email.startsWith("ed-") ? "ed_staff" : "responder";
      return json({mfa_required: false, mfa_setup_required: false});
    }
    if (path === `/api/shl/m/${manifestId}` && method === "POST") {
      if (state.revoked) return json({title: "Not found", status: 404}, 404);
      const body = request.postDataJSON() as {fl_mode?: string};
      if (body.fl_mode === "break_glass" && state.role === null) {
        state.access = true;
        return json({files: [{embedded: t1}], status: "can-change"});
      }
      if (state.role === "responder") {
        state.access = true;
        return json({files: [{embedded: t2}, {embedded: metrics}], status: "can-change"}, 200, {"FL-Emergency-Session": sessionId});
      }
      return json({}, 403);
    }
    if (path === "/api/v1/facilities") return json([{id: facilityId, name: "SOR Kraków Centrum (demo)"}]);
    if (path === "/api/v1/handoffs" && method === "POST") {
      expect(request.headers()["fl-emergency-session"]).toBe(sessionId);
      expect(request.headers()["idempotency-key"]).toBeTruthy();
      const body = request.postDataJSON() as {eta_minutes: number; priority: string};
      state.handoff = {id: handoffId, facility_id: facilityId, status: "pre_alerted", priority: body.priority, eta_minutes: body.eta_minutes};
      return json(state.handoff, 201);
    }
    if (path === "/api/v1/ed/board") return json(state.handoff ? [state.handoff] : []);
    if (path === `/api/v1/ed/handoffs/${handoffId}` && method === "GET") return json({...state.handoff, observations: {}, notes: null, ips: full, baseline: {status: "insufficient_data", metrics: [], series: []}});
    if (path === `/api/v1/ed/handoffs/${handoffId}/ack` && method === "POST") {
      if (state.handoff) state.handoff.status = "acknowledged";
      return json(state.handoff);
    }
    if (path === "/api/v1/patients/me") return json({patient_id: linkId, name: {given: "Marco", family: "Rossi"}, birth_date: null, sections: {}, flags: [], essentials: {items: [], show_sex: false}});
    if (path === "/api/v1/patients/me/links" && method === "GET") return json(state.revoked ? [] : [{id: linkId, kind: "emergency", status: "active", label: "FirstLook", url: viewerUrl()}]);
    if (path === `/api/v1/patients/me/links/${linkId}` && method === "DELETE") { state.revoked = true; return route.fulfill({status: 204}); }
    if (path === "/api/v1/patients/me/access-log") return json(state.access ? [{seq: 1, time: new Date().toISOString(), actor_type: "break_glass", role: "break_glass", tier: "T1", action: "profile.read", outcome: "allowed"}] : []);
    if (path === "/api/v1/patients/me/baseline") return json({status: "insufficient_data", metrics: [], series: []});
    if (path === "/api/v1/patients/me/consents") return json({essentials_content: true, wearable_baseline: true, ed_prealert: true});
    if (["allergies", "medications", "conditions", "devices"].some((section) => path === `/api/v1/patients/me/${section}`)) return json([]);
    if (path.endsWith("/stream")) return route.fulfill({status: 204});
    return json({}, 404);
  });
  return state;
}

test("scan, acknowledge, see Essentials, patient access history, revoke", async ({page}) => {
  const state = await mockApi(page);
  await page.goto("/demo");
  await expect(page).toHaveURL(`${origin}/s`);
  await expect(page.getByRole("heading", {name: "Profil ratunkowy"})).toBeVisible();
  await page.getByLabel("Powód dostępu ratunkowego").fill("Nagły dostęp ratunkowy");
  await page.getByRole("checkbox", {name: /Potwierdzam/}).check();
  await page.getByRole("button", {name: "Otwórz dane podstawowe"}).click();
  await expect(page.getByText("Zapisano pompę insulinową", {exact: false})).toBeVisible();
  await expect(page.getByText("Marco Rossi")).toHaveCount(0);
  state.role = "patient";
  await page.goto("/app");
  await expect(page.getByText("Dostęp ratunkowy", {exact: true})).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", {name: "Unieważnij link"}).click();
  await expect.poll(() => state.revoked).toBe(true);
  state.role = null;
  await page.goto(viewerUrl());
  await expect(page).toHaveURL(`${origin}/s`);
  await page.getByLabel("Powód dostępu ratunkowego").fill("Nagły dostęp ratunkowy");
  await page.getByRole("checkbox", {name: /Potwierdzam/}).check();
  await page.getByRole("button", {name: "Otwórz dane podstawowe"}).click();
  await expect(page.getByText("Link jest niedostępny lub został unieważniony.")).toBeVisible();
});

test("responder full view, pre-alert, ED board acknowledgement", async ({page}) => {
  const state = await mockApi(page);
  await page.goto(viewerUrl());
  await page.getByRole("button", {name: "Zaloguj się"}).click();
  await page.getByLabel("E-mail").fill(`responder-${crypto.randomUUID()}@demo.invalid`);
  await page.getByLabel("Hasło").fill(crypto.randomUUID());
  await page.getByRole("button", {name: "Kontynuuj bezpiecznie"}).click();
  await page.getByRole("button", {name: "Widok zalogowanego ratownika"}).click();
  await expect(page.getByText("Marco Rossi")).toBeVisible();
  await page.getByLabel("Szpital docelowy").selectOption(facilityId);
  await page.getByRole("button", {name: "Wyślij zgłoszenie"}).click();
  await expect(page.getByText("Zgłoszenie wysłane")).toBeVisible();
  expect(state.handoff?.status).toBe("pre_alerted");
  await page.goto("/ed");
  await page.getByLabel("E-mail").fill(`ed-${crypto.randomUUID()}@demo.invalid`);
  await page.getByLabel("Hasło").fill(crypto.randomUUID());
  await page.getByRole("button", {name: "Kontynuuj bezpiecznie"}).click();
  await page.getByRole("button", {name: /Wstępnie zgłoszony/}).click();
  await expect(page.getByText("Marco Rossi")).toBeVisible();
  await page.getByRole("button", {name: "Potwierdź"}).click();
  await expect.poll(() => state.handoff?.status).toBe("acknowledged");
});
