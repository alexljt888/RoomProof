# Backend domain foundation

Python 3.11+. Domain, repository, and services use the standard library;
the HTTP layer uses FastAPI/Pydantic. From the repository root, create a
separate backend environment (keep the existing ML environment unchanged):

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -m unittest discover -s backend/tests -v
backend/.venv/bin/python -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Visit `http://127.0.0.1:8000/docs` for the local interactive contract. HTTP tests
use TestClient in process; no server, network requests, image files, or API key
are needed. HTTPX is included for TestClient; unittest remains the test runner.

`app/domain.py` defines inspections with embedded property details and renter
names, rooms, registered photo metadata, analyses, and findings. Parent object
references enforce ownership; ID properties expose these relationships. The repository groups rooms, photos, analyses, and findings in an
`InspectionState` aggregate.
The domain does not import `ml/`.

AI proposes; the renter confirms. Every finding starts `pending_review`, even
with clear AI certainty. `confirm(reportable=...)` copies the original proposal;
`edit_and_confirm(ApprovedContent(...))` records human replacement content;
`reject(reason)` records rejection without approved content. The latter two
confirmation actions both lead to `confirmed`; editing is an action, not a state.
A completed review cannot be repeated. Only confirmed findings with approved
`reportable=True` are eligible for eventual report inclusion. Eligibility does
not prove image availability; the report export separately checks approved evidence.

Original proposals, evidence references, and approved review snapshots are frozen.
Dataclasses prevent normal attribute assignment; the two controlled terminal
transitions internally replace a private result/review exactly once. This is
practical immutability, not protection against deliberate Python reflection.
Services use atomic repository updates for transitions across concurrent
requests. There is no human authorization yet; renter names are not authentication.

Photo metadata accepts a basename and declared image media type, not bytes, paths,
or URLs. It does not verify an upload or media contents. Capture surface hints
are optional and do not constrain AI classification. Original `FindingProposal.evidence_photos` must include the analyzed photo.
`ApprovedContent.evidence_photos` records the human-approved selection and may
instead contain other photos. Both selections must be nonempty, unique, and
belong to the finding's room and inspection. Confirm-original copies original
evidence. Edit-and-confirm requires a complete `ApprovedContent`, including an
explicit nonempty evidence selection at the domain level; pass `finding.original_proposal.evidence_photos`
when retaining it. The domain snapshot has no nullable evidence selection.
Original evidence and analysis provenance remain unchanged after review. Neither
selection implies durable or tamper-proof storage.

Evidence and limitations accept lists or tuples, copy them into tuples, and
reject invalid containers/members with `InvalidDomainData`. Once reviewed, public
review methods check state before validating a new payload and raise
`TransitionConflict` for subsequent attempts.

An analysis completes with `findings_present`, `no_visible_findings`, or
`uncertain`, or fails with a safe enumerated code. Only successful analyses whose
outcome permits findings can be their source. Services assemble the
analysis and findings atomically through the injected analyzer. `FakePhotoAnalyzer`
remains the default; `OpenAIPhotoAnalyzer` requires explicit injection. Raw provider errors
must not be stored as failure information.

`InvalidDomainData` identifies invalid values/relationships (future HTTP 422);
`TransitionConflict` identifies repeated terminal operations (future HTTP 409).
Backend surface/category vocabulary is intentionally independent of ML.


## Local workflow

`repository.py` defines the small `InspectionRepository` protocol and its
`InMemoryInspectionRepository` implementation. Storage belongs to each instance.
Create, read, update input, committed state, and returned results are isolated by
deep copies. A single lock protects each repository. An update callback works on
a private aggregate; validation or callback failure discards the entire update.
Callbacks are trusted internal service code, must be short, and must not call
back into the repository. They are not an external mutation API.

`services.py` supports `create_inspection`, `add_room`, `register_photo`,
`analyze_photo`, `confirm_finding`, `edit_and_confirm_finding`, `reject_finding`,
`get_inspection`, and `list_inspections`. Operations return detached `InspectionState` snapshots.
Resources are looked up within the requested inspection; unknown or foreign IDs
raise `NotFound`. Malformed IDs/content raise `InvalidDomainData`. UUID possession
is not authorization. Approved evidence IDs resolve to registered photos, and
the service offers a convenience distinct from the domain constructor:
omitted evidence IDs or explicit `None` retain original proposal evidence;
an empty list is invalid; supplied IDs resolve to registered same-room photos.
The service always constructs a domain snapshot with explicit nonempty evidence.

`inference.py` defines `PhotoAnalyzer`, `AnalyzerExecution`, `AnalysisOutput`, and
`ProposedFinding`. `analyze(photo)` returns one execution containing output and
immutable provider-neutral provenance.
The boundary has no review status, approved content, or reportability fields.
`FakePhotoAnalyzer` wraps its explicitly configured output with fake provenance or raises an
`AnalyzerFailure` with a safe code. It is not AI, never reads image bytes, and
never branches on filenames. Configure one/multiple proposals, no visible
findings, uncertainty, or a failure code directly.

Analysis reserves a pending record atomically, releases the repository lock for
the analyzer call, then atomically completes the analysis and creates pending
findings. Pending/successful analyses block duplicates with `TransitionConflict`.
Failures create no partial findings and permit another attempt; previous failed
records remain. Failed calls return a snapshot with a failed analysis, rather
than exposing provider exceptions. Invalid output uses `invalid_response`, including wrong return types and
`AnalyzerContractError` raised during output construction. `AnalysisOutput`
validation raises that small contract-specific error; analyzer adapters must
translate their own output parsing/shape errors into it. Unexpected execution or
provider exceptions remain `unavailable`; explicit `AnalyzerFailure` safe codes
are preserved. No exception text or invalid output object is exposed in state. Only explicit review methods
can approve findings. Review checks and writes happen within one locked update.

A small offline example, from the repository root:

```python
from backend.app.domain import AnalysisOutcome, PropertyDetails
from backend.app.inference import AnalysisOutput, FakePhotoAnalyzer
from backend.app.repository import InMemoryInspectionRepository
from backend.app.services import InspectionService

service = InspectionService(
    InMemoryInspectionRepository(),
    FakePhotoAnalyzer(AnalysisOutput(AnalysisOutcome.NO_VISIBLE_FINDINGS)),
)
state = service.create_inspection(PropertyDetails("Example address"), "Example renter")
inspection_id = state.inspection.id
state = service.add_room(inspection_id, "Living room")
room_id = next(iter(state.rooms))
state = service.register_photo(inspection_id, room_id, "example.jpg", "image/jpeg")
photo_id = next(iter(state.photos))
state = service.analyze_photo(inspection_id, photo_id)
```

This repository is development/testing only: process-local, non-durable, no
persistence across restart, and unsuitable for multiple production workers.
There is no production image upload/storage, authentication, or deployment. The manual smoke harness can read one local image and
explicitly compose the real adapter; the default app requires no API key. A process interruption can leave a pending
analysis in a surviving repository instance; recovery/timeouts are not implemented.


## HTTP workflow

`main.create_app(analyzer=...)` creates a fresh in-memory repository and service
for each application. Tests inject deterministic scenarios through the factory;
there is no scenario-selection HTTP field. The default fake always proposes one
synthetic clear wall scratch and explicitly reports that no image was inspected.
Restarting the app loses all state. This is a local workflow milestone, not a
production-ready inspection system.

| Method | Path | Success response |
| --- | --- | --- |
| POST | `/inspections` | 201, inspection state |
| GET | `/inspections` | 200, inspection summaries |
| GET | `/inspections/{inspection_id}` | 200, inspection state |
| POST | `/inspections/{inspection_id}/rooms` | 201, updated inspection state |
| POST | `/inspections/{inspection_id}/rooms/{room_id}/photos` | 201, updated inspection state |
| POST | `/inspections/{inspection_id}/photos/{photo_id}/analyses` | 200, updated inspection state, including handled failure |
| POST | `/inspections/{inspection_id}/findings/{finding_id}/review` | 200, updated inspection state |

Request schemas forbid unknown fields and client-supplied IDs/timestamps.
Review requests are discriminated by `action`:

- `confirm`: requires a JSON boolean `reportable`; copies original content/evidence.
- `edit_and_confirm`: requires category, surface, location, description, and a JSON
  boolean `reportable`. Optional `evidence_photo_ids` follow the service rules above.
- `reject`: accepts only the action and an optional reason; no approved content.

Clients cannot directly submit a finding state, review record, or report
eligibility. Routes only translate inputs and call services. `schemas.py` maps
explicit fields to responses; parent references become UUIDs, never recursive
Python objects. Findings expose `original_proposal`, separate `review.approved`,
source analysis ID, state, and eligibility. Analyses expose provenance, status,
outcome, completion time, limitations, and safe failure code. UUIDs and UTC times
serialize as strings. Photos remain registered metadata, not verified uploads.

Application/domain errors have the stable shape:

```json
{"error": {"code": "not_found", "message": "Resource not found in the requested inspection."}}
```

`NotFound` maps to 404/`not_found`; `TransitionConflict` to
409/`transition_conflict`; `InvalidDomainData` to 422/`invalid_domain_input`.
Messages are fixed and do not expose exception text. Unknown and foreign resource
IDs share the same scoped 404. A registered photo in the wrong room, duplicate
evidence, and empty evidence map to domain 422. These checks are resource scoping,
not authentication.

FastAPI request validation keeps its normal 422 `detail` response. It runs before
services, so malformed review requests can return schema 422 even for already
reviewed findings; valid repeated actions return 409. Handled analyzer failures
remain failed analysis state with HTTP 200, rather than becoming server errors.


OpenAPI documents both HTTP 422 shapes on domain-validating operations using
an `anyOf` union of `HTTPValidationError` and `ErrorResponse`. The validation
models are documentation-only; FastAPI's built-in handler remains unchanged.

Known P2 item for final Phase 2 review: Starlette 1.7.0 TestClient emits
`StarletteDeprecationWarning` when falling back to HTTPX 0.28.1. Installed
requirements are compatible and tests pass; the warning is not suppressed.
Dependency cleanup is deferred and does not change runtime correctness.

## Phase 3 Step 1: transient image preparation

`images.py` adds a provider-neutral `ImageSource.read(photo_id) -> bytes` boundary.
`InMemoryImageSource.bind(photo_id, content)` binds bytes once to a UUID, with a
lock and defensive copying of bytearrays. Missing and duplicate bindings fail;
instances share no state. This is development infrastructure, not an upload API.
The source never interprets filenames or paths and does not verify domain ownership;
the existing service remains responsible for scoped photo lookup. A future storage
source can implement the same read contract.

`prepare_image` detects actual JPEG/PNG content, verifies integrity and fully
decodes pixels, applies EXIF orientation, composites transparency onto white, and
encodes a fresh RGB PNG without EXIF, ICC, or text metadata. Grayscale is converted
to RGB. Animated/multipage images and other formats (including HEIC/HEIF) are
unsupported even though the domain permits their metadata declarations.

The versioned `rgb-png-v1` policy limits input to 20 MiB and decoded images to
20 million pixels, accommodating ordinary apartment photos while bounding per-call
memory use. Images above a 4096-pixel longest side are reduced with aspect-preserving
Lanczos resizing; smaller images are not resized. This preserves substantial detail
without forwarding arbitrarily large images. Fresh PNG avoids another lossy JPEG
encode; prepared output is capped at 32 MiB during encoding. These limits are local
preparation policy, not provider limits. Resizing can still reduce subtle detail.
Pillow's bomb protections remain enabled; the explicit pixel cap is stricter than
its default threshold. Existing Pillow warnings are not globally suppressed.

`PreparedImage` is a transient frozen value holding immutable encoded bytes
(excluded from repr), output media type/dimensions, original and prepared SHA-256,
and policy version. Hashes describe content, not guaranteed model repeatability;
PNG byte reproducibility is scoped to the same policy and encoder environment.
Do not log or serialize image bytes; repr exclusion is not a general redaction tool.
Image-layer errors distinguish missing bindings, duplicate bindings, invalid
images, unsupported formats, and resource limits using fixed safe messages.

Step 1 alone added no bytes or hashes to `Photo` or `InspectionState`; Step 3 later
added analysis provenance hashes, never image bytes. No service/analyzer wiring,
image upload, filesystem loading, S3, or real AI calls are implemented in this step.
The development source retains all bound bytes until its instance is released;
it has no total-storage quota and is not production storage. Synthetic in-memory
tests run with the existing backend test command above.

## Phase 3 Step 2: explicitly injected OpenAI adapter

`openai_analyzer.py` implements `OpenAIPhotoAnalyzer` with an injected image source,
SDK client, and frozen `AnalyzerConfig` requiring an explicit model identifier.
It creates no client, reads no environment or `.env`, and makes no request at import.
Client creation, credential handling, and lifecycle belong to explicit composition,
now provided by the manual Step 4 harness. The normal `create_app()` still uses `FakePhotoAnalyzer`.
The controlled real-provider integration result is recorded under Step 4 below.

`analyze(photo)` uses only `photo.id` to resolve bytes, calls Step 1 preparation,
and sends the prepared PNG plus the versioned instructions using Responses
`parse(text_format=ProviderResult, store=False)`. No filename, path, renter,
address, inspection graph, or evidence IDs are sent. The injected client's options
are copied with a finite timeout (90 seconds by default) and `max_retries=0`.
There is at most one SDK request invocation per analysis, and none for invalid
image input. Composition must not inject a custom transport that independently
retries requests. The caller owns the client's shared transport lifetime.

The adapter's Pydantic schema uses all five surfaces and eight categories, keeping
`chip` distinct from `chipped_paint`. `findings_present` requires at least one clear
observation; `uncertain` permits only possible observations or none;
`no_visible_findings` requires none. Empty observation text/limitations, unknown
vocabulary, and extra approval/reportability fields are rejected. Structured
responses are translated into the existing `AnalysisOutput`/`ProposedFinding`
values; the provider schema never enters the domain. AI supplies observations,
never approval or reportability, and the service still attaches source evidence.

Image-layer failures map to `unreadable_image`. Provider failures (including
credentials, timeout, rate limit, and unexpected SDK exceptions) map to
`unavailable`. Refusal, incomplete/missing structured output, SDK response
validation errors, and schema/semantic violations raise `AnalyzerContractError`
for existing `invalid_response` handling. Messages are fixed; provider diagnostics
are not returned. No fallback model or automatic model retry is selected.

`analyze(photo)` is the only execution method and returns the provider-neutral
`AnalyzerExecution(output, provenance)` from `inference.py`. The former separate
metadata execution method has been removed. Output and provenance describe the
same invocation; there is no mutable last-result state.

## Phase 3 Step 3: application integration and provenance

`AnalysisProvenance` is a frozen domain value containing analyzer identity/version,
optional requested/reported model, prompt/schema versions and SHA-256, preparation
version, and original/prepared image hashes. SHA-256 values use lowercase hex;
prompt/schema versions require their hashes, and image hashes occur together with
a preparation version. No image bytes, prompts, raw responses, secrets, SDK objects,
or exception details belong in this value. The schema hash identifies canonical
Pydantic schema, not necessarily the SDK-transformed wire schema.

The service captures one analyzer reference and its `configured_provenance` before
reserving an `Analysis`. Reservation stores immutable `attempt_provenance`. Inference
runs outside the repository lock exactly once. Completion validates the execution
and stores `AnalysisResult.provenance`, outcome, and all pending-review findings in
one repository update. Invalid output or provenance rolls back the whole completion.
Analyzer identity and all populated configured fields must agree with final provenance.
For direct domain callers, omitted attempt provenance defaults to identity-only;
the application always supplies its configured snapshot explicitly.

Safe failures retain available provenance and no findings. Image preparation failures
retain configuration; successful preparation adds both image hashes. Invalid or
contradictory failure provenance is discarded in favor of the reservation snapshot,
without changing the safe failure classification. Unexpected exceptions also use
that snapshot. A configured preparation version does not prove preparation completed,
and an unavailable failure does not prove the remote provider received a request.
Retries remain explicit new application attempts. Terminal results remain one-shot.

The default fake returns deterministic identity-only provenance with no invented
model, prompt, or image information. The real adapter remains injected through
`create_app(analyzer=...)`; no real client or key is created/loaded by default.
Tests register Photo metadata through HTTP, bind generated PNG bytes internally to
the returned UUID using the same `InMemoryImageSource`, and analyze through the
existing endpoint. Photo remains metadata-only; Phase 4 adds scoped transient content endpoints.

HTTP analyses expose `provenance: null` while pending. Terminal responses select only
`requested_model`, `provider_model`, `prompt_version`, `schema_version`, and
`preparation_version`. Existing analyzer identity fields remain. All hashes stay
internal. Human review, reportability, original evidence, approved evidence, and
source-analysis links are unchanged. In-memory provenance is not durable storage.

`AnalyzerConfig.max_prepared_image_bytes` accepts a positive integer or `None`.
`None` disables the provider-specific bound for this offline stage; Step 1's generic
32 MiB output limit still applies. The adapter checks a supplied bound after image
preparation and before base64 allocation or provider invocation. Rejection returns
`unreadable_image` with preparation provenance. Base64 adds roughly one third to the
image size, before JSON/prompt/schema overhead. Step 4 composition explicitly supplies the approved 20971520-byte prepared-image
bound; this is smoke configuration, not a general claim about all provider limits. Step 1 policy is unchanged.

The permanent SDK compatibility regression uses OpenAI 3.8.0 with HTTPX2
`MockTransport`, a synthetic placeholder credential, and blocked socket connections.
It covers structured parsing/request construction and one transport attempt for a
retryable failure despite retries on the caller's client. Other tests use injected
stubs and memory-only synthetic images; these tests make no real provider calls.

Normal tests use generated in-memory images and injected clients. They need no
API key, private images, or network. OpenAI 3.8.0 adds HTTPX2 transitively; with it
installed, Starlette 1.7.0 selects HTTPX2 and no longer emits the previously noted
HTTPX fallback warning. The existing direct dependency pins remain unchanged.

## Phase 3 Step 4: controlled integration smoke

`backend/scripts/smoke_openai_analysis.py` uses `InspectionService` directly with
`InMemoryInspectionRepository`, `InMemoryImageSource`, and an explicitly injected
`OpenAIPhotoAnalyzer`. It creates synthetic property/renter/room metadata,
registers one photo, and binds one local JPEG/PNG to its UUID. Only prepared pixels
are sent; the local path and filename are not sent. No results are persisted.

One controlled real-provider smoke succeeded: one request, zero retries, a
`succeeded` analysis with `findings_present`, structured execution provenance, and
one `pending_review` finding with report eligibility false. Requested and returned
model were `gpt-4.1-mini-2025-04-14`; prompt/schema version was
`roomproof-observations-v1` and preparation version was `rgb-png-v1`. No private
smoke artifact was written. This verifies integration, **not model accuracy or
quality**. Human review remains required; AI makes no reportability decision.

Phase 3 real AI integration is implemented. The fake remains the default; there
is still no production image upload/storage, durable persistence, or deployment.
The command below is for any future separately authorized run, from the repository root:

```sh
backend/.venv/bin/python -m backend.scripts.smoke_openai_analysis '<local-image-path>'
```

Supply `OPENAI_API_KEY` through the process environment using your existing secure
local workflow; do not put a key in command arguments, shell history, or Git.
The harness does not load `.env` automatically and does not add a second secret
file. Missing/blank keys fail before client construction. Default `create_app()`
continues to use `FakePhotoAnalyzer`, requires no key, and never runs this script.
Importing the script does not execute it. Automated tests use synthetic inputs
and mocked clients, never the live smoke.

Fixed approved smoke settings are model `gpt-4.1-mini-2025-04-14`, prepared-image
bound `20971520` bytes (20 MiB), existing `detail="high"`, 90-second adapter timeout,
and `max_retries=0`. No output-token cap was added. There is one service analysis
attempt and at most one Responses invocation; invalid images make no provider
request. There is no retry loop, fallback, or second verification call. A timeout
cannot establish whether the provider received the request. Failures stop with a
nonzero exit; do not automatically rerun. The explicit OpenAI endpoint prevents
an environment base-URL override from redirecting this smoke.

Output is an allowlisted JSON summary of analysis status/outcome/safe failure code,
finding count and observation fields, review state/report eligibility, analyzer
identity, models, and prompt/schema/preparation versions. It excludes paths,
filenames, credentials, raw requests/responses, image bytes, hashes, and property
metadata. SDK logging is disabled during execution to avoid diagnostic leakage.
Keep terminal observations private. Use only a manually approved, non-sensitive
image already in ignored local storage; never copy it into tracked fixtures.

Exit 0 means the integration completed, including valid zero-finding or uncertain
outcomes. It does not establish model accuracy. Findings remain pending review,
with no AI approval or reportability decision. Exit 1 means analysis/setup could
not complete; exit 2 means missing configuration or invalid local input. No durable
persistence or production deployment is introduced.

## Phase 4 Step 2: transient browser photo content

The original seven JSON operations remain compatible. Two scoped content routes
now bind browser bytes without changing Photo domain metadata:

- `PUT /inspections/{inspection_id}/photos/{photo_id}/content`: raw JPEG/PNG
  request body; success 204. Verify ownership, bound streaming input to 20 MiB,
  validate with `prepare_image`, then bind original bytes once. Invalid input
  returns safe 422; input/storage limits 413; replacement 409; wrong scope 404.
  Invalid uploads leave the registered UUID available for a corrected upload.
- `GET` at the same path: sanitized `image/png`, `Cache-Control: no-store`, and
  `X-Content-Type-Options: nosniff`. Missing content returns safe 404. Original
  EXIF and other metadata are never served. Error bodies use safe `detail`
  code/message objects, alongside the existing JSON API error formats.

`InMemoryImageSource` enforces a 100 MiB aggregate encoded-byte bound per app
instance under its binding lock, in addition to existing per-image limits.
Transient preparation/request buffers also consume memory; this is not a total
process-memory quota or production storage. Nothing writes images to disk.
`create_app(image_source=...)` can inject a smaller-capacity source for testing.
An analyzer exposing `image_source` shares that exact source automatically;
supplying a different upload source is rejected. Future storage can replace
read/bind behavior without putting storage details into the Photo domain.

The default factory still uses the offline fake and needs no key. Explicit real
adapter injection remains available as in Phase 3; the explicit local runtime
configuration below now composes it for the HTTP workflow. Content upload does
not invoke analysis. Browser analysis buttons require loaded content; legacy
metadata-only fake API callers remain compatible.

Run locally with one process (avoid reload when retaining in-memory inspections):

```sh
backend/.venv/bin/python -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Run Vite separately as documented in `frontend/README.md`. These local servers
have no authentication and must not be publicly exposed. Server restart loses
all state and image bytes; no durable persistence, S3, or deployment exists.

## Phase 4 Step 3: explicit local analyzer mode

`runtime.py` composes the existing adapter into the same service and HTTP routes.
Missing `ROOMPROOF_ANALYZER` or `ROOMPROOF_ANALYZER=fake` uses the deterministic
fake without a key or OpenAI client. `ROOMPROOF_ANALYZER=openai` requires both
nonblank `OPENAI_API_KEY` and `ROOMPROOF_OPENAI_MODEL`; unknown modes or missing
configuration fail startup with fixed safe messages, never a silent fallback.
Explicit `create_app(analyzer=...)` injection bypasses environment selection.

For a **future authorized manual real-AI run**, provide the key through a secure
backend process environment (never a command argument, frontend `VITE_` variable,
or Git). This factory does not load `.env`. From the repository root:

```sh
ROOMPROOF_ANALYZER=openai ROOMPROOF_OPENAI_MODEL=gpt-6-luna \
  backend/.venv/bin/python -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Run `npm run dev` from `frontend/` separately. Stop the existing fake server before
switching; switching/restarting loses all in-memory inspections and images. Use
one worker, loopback only, without reload for a controlled session. To explicitly
return to offline mode, use `ROOMPROOF_ANALYZER=fake` with the same backend command.
Normal `uvicorn app.main:create_app --factory --reload` from `backend/` remains
fake/key-free when analyzer configuration is absent.

The upload bridge and OpenAI adapter share exactly one `InMemoryImageSource`.
Upload alone does not invoke AI. Clicking Analyze in real mode sends prepared
image pixels to OpenAI and consumes API credits. Photo stays metadata-only.
The selected model is explicit/configurable; initial development configuration is
`gpt-6-luna`. The runtime fixes a 90-second timeout, `max_retries=0`, official OpenAI
endpoint, and 20971520-byte (20 MiB) prepared-image bound. Existing `detail="high"`,
structured output, preparation protections, and no output-token override remain.
There is no automatic retry/fallback; failures use existing safe analysis states.
Provider/transport diagnostic logging is disabled to avoid payload leakage;
application/server logging remains available. The app closes its owned SDK client
on shutdown; explicitly injected clients remain caller-owned.

Real findings start pending review. Only human confirmation with explicit
reportability can make a finding eligible; AI never decides reportability.
Original proposals/evidence remain separate from approved content. Safe provenance
passes through HTTP, while hashes stay internal. The UI uses returned analyzer
identity for fake labels, never frontend provider configuration or credentials.

Runtime integration tests use synthetic JPEG/PNG, synthetic credentials, the
pinned SDK with MockTransport, and blocked DNS/sockets. One controlled Step 3
UI-driven live test passed with `gpt-6-luna`: upload, one analysis POST (200),
structured output, pending review, and human Edit & Confirm. The user corrected
the approved category from scratch to hole and selected reportability; the
original AI proposal and source evidence remained intact. No visible automatic
retry, traceback, or credential exposure was observed. This verifies live access
and integration, not accuracy. The earlier Phase 3 smoke is also not a benchmark. Storage remains transient; no authentication, durable persistence,
production storage, or deployment is provided.

## Phase 4 Step 4: reviewed reports (complete)

Hands-on review, final focused review, and final Phase 4 integration review passed.
Phase 4 is the complete local product; Phase 5 is next and is not implemented.

`reports.py` projects one validated repository snapshot into an allowlisted read
model. Only confirmed findings with approved `reportable=True` appear, grouped by
room, using approved text and approved evidence IDs. Preview/export never mutate
inspection or review state and never invoke an analyzer. Domains remain metadata-only.

- `GET /inspections/{id}/report`: backend-authoritative JSON preview, no-store.
  Includes room/finding counts, pending reviews/analyses, unanalysed photos and
  failed attempts. Pending findings are excluded but prominently counted.
- `GET /inspections/{id}/report.pdf`: memory-only deterministic ReportLab PDF,
  `application/pdf`, fixed attachment filename `roomproof-inspection.pdf`, no-store.
  Any registered photo without successful analysis, pending review, or active
  analysis blocks with 409. Missing/invalid approved evidence
  also blocks with safe 409. Both endpoints return 404 for unknown inspections.
  No arbitrary path or URL input is accepted. Images resolve by validated UUID
  from ImageSource and pass existing preparation before embedding.

Zero findings is valid, explicitly stated without claiming the property is
undamaged. Unanalysed photos and failed attempts remain disclosed. `export_ready` is computed
from photos lacking successful analysis, pending reviews/analyses, and unavailable
approved evidence; both PDF generation and the UI use this backend decision.
A failed attempt blocks until that photo has a successful retry; historical failures
remain disclosed but do not block after success. Every registered photo is required,
including replacement-evidence photos and metadata awaiting upload.
`review_complete` alone is not export eligibility. PDF export rechecks the current snapshot even
if the preview is stale. All approved evidence is required, including replacements;
original AI evidence is never substituted. The download is a snapshot, not a finalization lock.

ReportLab 4.4.9 is the runtime dependency; pypdf 6.10.0 is test-only in
`requirements-dev.txt` for text/image verification. The bundled Vera font is used
without system-font dependencies. Unsupported characters (including CJK) explicitly
block PDF export with 422 rather than silently disappearing; preview preserves text.
No server PDF files or report persistence are created. Existing transient storage
limits and restart data loss still apply. Do not expose the unauthenticated app publicly.

Phase 4 finishes the local product; Phase 5 adds durable infrastructure and hardening
(see root roadmap). Deferred P2s: post-client/pre-lifespan construction cleanup,
existing photo-card missing/connection error ambiguity, and a dedicated aggregate
memory race test. Phase 5 also retains PDF aggregate resource/concurrency limits
and PDF font/CJK coverage (unsupported text currently returns 422) as deferred P2s.
Report evidence errors use neutral wording and export checks bytes
server-side, so the existing photo-card ambiguity cannot silently omit report evidence.
