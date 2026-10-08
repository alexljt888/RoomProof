# RoomProof frontend — local inspection workflow

**AI suggests. You verify.** HTTP mode is the default. The local backend uses
`FakePhotoAnalyzer` unless explicitly composed otherwise: it returns synthetic
suggestions and never calls a model or needs a key. The UI identifies fake analysis
from each returned Analysis, not from a client-side provider assumption.

## Run locally

Use Node 22.12+ (tested with Node 24.19) and npm. From the repository root, start
the existing backend environment in one terminal:

```sh
backend/.venv/bin/python -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Vite proxies `/api` to the loopback backend on port
8000; no browser CORS configuration or frontend secrets are needed. Do not expose
this unauthenticated development server on a public network. For fixture-only mode:

```sh
VITE_DEMO=true npm run dev
```

HTTP mode stores state/images in backend memory: browser refresh can recover an
inspection while the server lives; server restart loses everything. Fixture mode
resets on browser refresh. No data is put into localStorage/sessionStorage.

## Workflow

Create an inspection, add a room, and choose one JPEG/PNG (up to 20 MiB). The UI
registers Photo metadata, uploads its raw bytes to the scoped content endpoint,
and enables Analyze only after sanitized evidence loads successfully. Images are
served from the backend; no object URLs are created or retained. Failed uploads
can be corrected using the same Photo UUID. HEIC/conversion is not supported.

Analysis is an explicit action, never automatically retried. Failed or uncertain
transport outcomes trigger a state refresh before a user can retry; if that refresh
fails, further analysis is blocked until an explicit state refresh succeeds. A
successful uncertain/no-findings outcome is distinct from a failed Analysis.

Review every finding: confirm or edit with an explicit reportability Yes/No, or
reject with an optional reason. Original proposal/evidence and approved content
stay separate; completed reviews are read-only. Summary counts use returned
backend state. AI makes no reportability decision; the Report tab projects approved content.

## Boundaries and checks

`src/api/types.ts` mirrors the backend contracts. `InspectionApi` supports both
fixture and native-fetch HTTP clients; only HTTP mode exposes the content bridge.
The seven original JSON operations remain intact, with scoped binary PUT/GET
added for transient images. Prepared evidence uses `Cache-Control: no-store`.

```sh
npm test
npm run typecheck
npm run lint
npm run build
```

Tests use synthetic files, injected clients, and mocked fetch; no provider calls.
Backend/ML offline suites remain separate. `node_modules`, build output, and
coverage are ignored. No authentication, durable storage, or deployment is provided.

## Explicit real-AI backend

The same UI works with either analyzer; it never holds a provider key or calls
OpenAI. Fake labels come from each backend Analysis. See the
[backend runtime instructions](../backend/README.md#phase-4-step-3-explicit-local-analyzer-mode)
for `ROOMPROOF_ANALYZER=openai`, `ROOMPROOF_OPENAI_MODEL=gpt-6-luna`, and the
backend-only `OPENAI_API_KEY` environment requirement. Fake remains the default.
Do not put credentials in any `VITE_` variable. No frontend configuration changes
are needed. Only explicitly configured real mode sends prepared images to OpenAI
when Analyze is clicked; this consumes credits. Review and reportability choices
remain mandatory. One controlled UI-driven live run passed with `gpt-6-luna`, including human
Edit & Confirm with separate original and approved content. This is integration
verification, not an accuracy benchmark.

## Report preview and PDF (Phase 4 Step 4)

Open Report after review. The preview fetches authoritative backend report data;
it does not reconstruct eligibility from React state. Refresh preview to retrieve
changes from another client. Missing successful analysis, pending review/analysis, and unavailable approved
evidence are clearly shown. Backend `export_ready` controls Download PDF.
Failed analysis requires a successful retry; resolved historical failures do not block. Export rechecks server state and blocks if approved evidence is missing.
Evidence display failures use neutral wording rather than asserting missing content.
Only human-approved reportable content and approved evidence are displayed.

PDF downloads come from the backend, never browser generation or OpenAI. Temporary
browser download URLs are released. Empty reports are valid but do not certify a
damage-free property. Reports disclose unanalysed photos and failed attempts. Unicode
outside the bundled PDF font is explicitly rejected by the backend; preview retains it.
Fixture-only mode directs users to the local HTTP workflow for reports. Storage remains
transient; retain downloaded files locally. Phase 5 will address durable infrastructure.
