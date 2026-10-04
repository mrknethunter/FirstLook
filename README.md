# FirstLook

FirstLook is a patient-owned emergency profile built for the Sport & Healthcare track at HackYeah 2026. A patient chooses the information that can help in an emergency and carries a QR code on a phone, card or other physical carrier. A responder can scan it with an ordinary phone camera, see the information allowed for that situation and send a pre-alert to an emergency department. The patient can see who accessed the record and can rotate or revoke the link.

The project is a working demonstration with **synthetic patients and fictional organisations only**. It is not a clinical service or a connection to a hospital information system. The public demo runs at [firstlook-hy-demo.duckdns.org](https://firstlook-hy-demo.duckdns.org/).

## How FirstLook differs

Phone Medical ID screens and paper emergency cards make information available near the patient. FHIR IPS and SMART Health Links provide formats for structured sharing, while hospital pre-alert tools help teams communicate before arrival. FirstLook connects those parts of the journey: the patient maintains one structured emergency profile, a scan grants the appropriate view without installing an app, and a responder can carry the same context into an ED handover. The personal activity baseline adds context from the patient's own history, and each access is visible to the patient. Tiered disclosure and EN, PL and IT views are part of that same flow. In this demo, imports use CSV/JSON or a synthetic patient-portal format and device sync is simulated; live wearable, national-portal and hospital connections remain future work.

## The three journeys

**Patient.** Anna Kowalska and Marco Rossi are the seeded patients. In `/app`, a patient reviews the profile, selects the smaller *Essentials* view available through emergency access, manages consent, and generates an emergency QR code. The app also shows access history, a personal activity baseline and demo imports. The patient can rotate or revoke a link. Marco's device sync is a simulator available only in the demo tenant; it does not read a live wearable.

**First responder.** Scanning a patient's QR opens the mobile viewer at `/s`. An unauthenticated person must give a reason and explicitly acknowledge that emergency access is logged before seeing the pseudonymised Essentials view. A responder who signs in through that scanned link can see the fuller emergency profile and the consented baseline, then send a pre-alert to the receiving department. Professional users cannot search or browse patients: the scanned link is the capability that starts this journey.

**Emergency department.** An ED operator signs in at `/ed` and sees handovers addressed to their facility. The board updates when a responder sends a pre-alert. The operator can open the handover and move it through acknowledgement, arrival and closure. These actions, along with the responder's access, appear in the patient's history.

For a guided walkthrough, use the [three-persona test guide](docs/PERSONA_TEST_GUIDE.md). It includes the steps and expected results for separate patient, responder and ED sessions.

## What the QR codes contain

The patient's emergency QR encodes a FirstLook viewer URL ending in `#shlink:/...`. The fragment contains the SMART Health Link payload, including the manifest location and decryption key. The browser removes the fragment from the address bar after reading it; the key is not placed in a query string or sent as part of the HTTP request URL. The server selects the permitted tier before returning encrypted files, which the viewer decrypts in memory. Emergency links use the SHL `L` flag without a passcode. Time-limited clinician shares use `P` with a passcode.

The **presentation QR** has a different job. It points to `/demo`, a stable entry page for Marco. That page asks the demo-only API for his current viewer URL and opens it in the SPA. A rotation can therefore change Marco's underlying emergency link without requiring a new presentation QR. The patient app also generates QR SVG/PNG, printable cards and a lock-screen wallpaper for the patient's own link. The carrier is a way to present the link, not a separate clinical record.

## Clinical data and interoperability

FirstLook uses HL7 FHIR R4 and the International Patient Summary (IPS 2.0.1) as its clinical model. The backend stores validated FHIR resources and builds an IPS document Bundle on demand. Its Composition includes the required Problems, Allergies and Medications sections, with optional sections when the corresponding data exists. The patient can request their IPS through the authenticated API. Emergency manifests contain tier-specific FHIR Bundles, and the ED handover carries an IPS snapshot for the receiving team. The UI reads structured FHIR fields rather than rendering untrusted narrative HTML.

The activity baseline is derived from the patient's own imported or synthetic observations using the documented median/MAD rules. Versioned YAML rules generate informational clinical flags from known codes; no AI or ML makes clinical decisions. CSV/JSON activity imports and a synthetic IKP-style adapter are included. Apple Health XML, a general FHIR import and live hospital integrations are outside the current demo path. The [import formats](docs/IMPORT_FORMATS.md) and [terminology provenance](docs/TERMINOLOGY.md) describe what the implementation accepts and how seeded labels are translated.

## Software architecture

The deployment is deliberately small enough to run on one Linux host and to inspect end to end:

```text
Phone or desktop browser
         |
   Host Caddy (HTTPS)
      /          \
React SPA      FastAPI
 (web)          |   \
             worker  PostgreSQL 16
```

Host Caddy terminates HTTPS and routes the SPA and API to services bound only to `127.0.0.1`. Docker Compose separates the public-facing edge network from the internal backend network; PostgreSQL has no published port. The backend is Python 3.12 with FastAPI, Pydantic v2, SQLAlchemy 2, psycopg 3 and Alembic. PostgreSQL also backs the job queue and event notifications. The worker processes staged imports and maintenance jobs. The frontend is a React, strict TypeScript and Vite SPA with Tailwind, Radix primitives, TanStack Query and react-i18next. EN, PL and IT are available in the demo flows.

The code follows the [architecture and technical requirements](docs/FL-DOC-02_Architecture_Technical_Requirements.pdf), the [security and privacy design](docs/FL-DOC-03_Security_Privacy_Design.pdf) and the [project dossier](docs/FL-DOC-01_Project_Dossier.pdf). Approved corrections to those documents are recorded in [DECISIONS.md](docs/DECISIONS.md).

## Privacy and security by design

Access is based on the minimum information needed for each role. Anonymous break-glass access returns a pseudonymised Essentials Bundle; authenticated responders can receive the fuller emergency view through the same link; ED staff can read handovers addressed to their facility. Every API route declares an authorisation policy, with object-level checks and patient-visible audit events. Break-glass requests require a reason and acknowledgement and are rate limited per link and source IP. Patients can revoke a link, which blocks new manifest reads.

Clinical resources are encrypted with per-patient data keys. Direct identifiers are kept behind a separate vault database role, while application, worker and migration roles have distinct privileges. Sessions are server-side; passwords use Argon2id, browser mutations use CSRF protection, and production professional accounts require MFA. The isolated demo tenant uses synthetic data and a documented MFA exception for judge accounts. Secrets are mounted as files rather than built into images. The viewer keeps decrypted data in memory, and the edge sets `Referrer-Policy: no-referrer`. See [DECISIONS.md](docs/DECISIONS.md) for the demo-specific trade-offs, including the temporary host access-log configuration.

## Run and verify the demo

On a Linux host with Docker Engine, Compose v2 and OpenSSL, start from the repository root:

```bash
bash scripts/start-demo.sh
docker compose ps
```

The script creates missing demo secrets, builds the images, runs migrations and seeds the synthetic accounts. To keep the same judge credentials across deployments, copy the separately supplied `demo_credentials.tsv` into `secrets/` **before** running it. Credentials and other secrets are deliberately excluded from the repository and deployment ZIP. The team lead configures the already installed host Caddy using [Caddyfile.example](Caddyfile.example); the script does not edit the host configuration. The approved public origin is `https://firstlook-hy-demo.duckdns.org`.

The [deployment guide](docs/DEPLOYMENT.md) covers first install, upgrades, secret handling, health checks and Caddy routing. The [test guide](docs/PERSONA_TEST_GUIDE.md) covers the judge flow on three separate sessions. Unit, type, lint, browser and security checks are configured in the repository and CI. A successful container start does not replace the phone, authorisation and accessibility checks in the [pre-demo acceptance record](docs/PRE_DEMO_ACCEPTANCE.md).

## Libraries and external resources

The backend uses FastAPI, Pydantic, SQLAlchemy, psycopg, Alembic, structlog, argon2-cffi, cryptography, pyotp, fhir.resources, PyYAML, jwcrypto, segno, Pillow, ReportLab and ijson. The SPA uses React, TypeScript, Vite, Tailwind CSS, Radix UI primitives, TanStack Query, react-i18next, `jose`, React Hook Form, Zod and Lucide. PostgreSQL 16 and Docker Compose provide storage and orchestration. Vitest, Playwright, pytest, Ruff and mypy support verification. Direct and transitive dependency versions are pinned in `backend/uv.lock` and `frontend/pnpm-lock.yaml`.

The interoperability references are HL7 FHIR R4, the [FHIR IPS Implementation Guide 2.0.1](https://build.fhir.org/ig/HL7/fhir-ips/en/artifacts.html) and the [SMART Health Links specification](https://docs.smarthealthit.org/smart-health-links/spec). The FirstLook wordmark was supplied by the team lead from the project draft. No real patient records, real institution branding or live wearable feeds are included.

## HackYeah disclosure

The FirstLook idea, its user journeys and its software architecture were conceived during HackYeah 2026. The team documented the design and built the demo during the event. LLM tools were integrated into the software development cycle to help with implementation, review, tests and documentation; team members remain responsible for checking and explaining the result. No LLM or other AI model runs in the clinical path or decides what a responder should do.
