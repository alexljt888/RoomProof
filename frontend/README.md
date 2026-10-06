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
backend state. There is no report generation or AI reportability decision.

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
coverage are ignored. No authentication, durable storage, deployment, or paid
provider setup is added in this step.
