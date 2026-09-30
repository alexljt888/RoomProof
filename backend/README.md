# Backend domain foundation

Python 3.11+. Domain, repository, and services use the standard library;
the HTTP layer uses FastAPI/Pydantic. From the repository root, create a
separate backend environment (keep the existing ML environment unchanged):

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
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
not prove image availability and does not generate a report.

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
analysis and findings atomically; only a configured fake analyzer runs here. Raw provider errors
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

`inference.py` defines `PhotoAnalyzer`, `AnalysisOutput`, and `ProposedFinding`.
The boundary has no review status, approved content, or reportability fields.
`FakePhotoAnalyzer` returns an explicitly configured output or raises an
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
There is no upload/storage, filesystem image loading, real AI/image inference,
authentication, frontend, or PDF/report generation. A process interruption can leave a pending
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
