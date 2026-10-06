# RoomProof frontend — Phase 4 Step 1

A responsive fixture-driven product shell. **AI suggests. You verify.**
This is not backend integration: no uploads, image reads, or model requests occur.
All illustrations are CSS-generated; all example information is synthetic.

## Run locally

Use Node **22.12+** (tested with Node 24.19) and npm. The older system Node 20.16
is not supported by this stack. Select a compatible Node runtime first.

```sh
cd frontend
npm ci
npm run dev
```

Open the loopback URL printed by Vite (normally http://127.0.0.1:5173).
No backend process or environment file is required. Never put provider credentials
in frontend configuration. Exact dependency versions and `package-lock.json` are
committed together when this checkpoint is approved. Prettier is a small dev-only
formatter for maintaining readable TSX/CSS; no component or icon library is used.

## Explore

- Start an inspection with example renter/property details, then add rooms.
- Or open the seeded inspection to see ready, analyzing, analyzed, and error cards.
- Add **demo** photos and analyze fixtures; no file picker or provider is involved.
- Review suggestions: confirm or edit with an explicit Yes/No reportability choice,
  or reject with an optional reason. Completed reviews are read-only.
- Original suggestions and source evidence remain distinct from approved content.
- The summary separates pending, confirmed/reportable, confirmed/non-reportable,
  and rejected findings. It does not generate a report.

The initial “analyzing” card is an explicitly labeled static visual example.
Demo actions resolve locally. State lives only in memory, resets on page refresh,
and is never placed in localStorage. Custom inspection URLs disappear on refresh.

## Boundaries and checks

`src/api/types.ts` mirrors the current seven FastAPI operations and serialized
contracts. `InspectionApi` is shared by the fixture implementation and the native
fetch client in `http.ts`. The app receives the client rather than importing
fixtures inside components. The HTTP client is prepared but not activated; upload,
evidence retrieval, backend validation details, and integration belong to later
Phase 4 work. Demo illustrations stand in for photos and are not evidence.

```sh
npm test
npm run typecheck
npm run lint
npm run build
```

Tests cover navigation, empty rooms, fixture actions, review choices, rejected
findings, and separation of original/approved content. Fetch is blocked in these
fixture tests. Backend and ML offline suites remain separate and unchanged.
`node_modules`, build output, and coverage are ignored. No production deployment,
authentication, PDF generation, or persistent storage is included.
