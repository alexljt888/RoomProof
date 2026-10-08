# RoomProof

RoomProof is being developed as an AI-assisted move-in inspection system: guide
renters through documenting apartment surfaces, identify and organize visible
damage, support human review, and eventually generate an evidence-backed report.
**AI proposes; the renter confirms.** An AI-generated finding does not
automatically become approved or reportable evidence. Users must review findings
before any future final report is generated.

## Current status: local frontend and explicit real-AI workflow implemented

### Implemented — Phase 1: ML feasibility and evaluation

- A frozen single-image VLM baseline using the OpenAI Responses API and Pydantic
  Structured Outputs for findings.
- An apartment-surface/damage data contract and human annotation workflow.
- Separate `visible_mark` and `reportable_damage` labels and evaluation.
- Batch inference infrastructure, offline metrics from saved predictions, and
  regression tests using synthetic data and mocked inference.

The current local development collection contains 25 images, including 20 labeled
examples and six historical single-image sanity-test outputs. Those outputs are
not a completed batch benchmark. Dataset expansion is intentionally paused until
later model-comparison and tuning milestones; no production accuracy is claimed.

### Implemented — Phase 2: backend domain, workflow, and API

- A domain model and application services for inspections, rooms, photo metadata,
  analyses, and findings, backed by an in-memory inspection repository.
- Explicit confirm, edit-and-confirm, and reject transitions. Original AI
  proposals and evidence remain separate from human-approved content and evidence;
  only confirmed findings with an explicit `reportable=true` decision are report eligible.
- A provider-neutral `PhotoAnalyzer` boundary with a deterministic fake analyzer.
- A FastAPI HTTP API with seven workflow operations, explicit request/response
  schemas, safe application-error mapping, and offline backend/API tests.

The domain retains **photo metadata only**; transient bytes are held separately.
Its fake analyzer inspects no image bytes and performs no real AI inference. State is local to one process and is lost
on restart; this is a development foundation, not a production-ready application.
### Implemented — Phase 3: real AI integration

- Transient image access/preparation and an explicitly injected `OpenAIPhotoAnalyzer`.
- Structured observations and provider-neutral execution provenance through the
  normal application workflow. `FakePhotoAnalyzer` remains the key-free default.
- One controlled real-provider smoke succeeded with one request and zero retries,
  producing structured provenance and one pending-review finding that was not
  report eligible. Human review remains required; AI does not decide reportability.

This is an integration result, **not an accuracy or quality benchmark**. There is
no production image upload/storage, durable persistence, or deployment yet.
See the [backend README](backend/README.md) for setup, endpoints, limitations, and
local usage.

### Implemented — Phase 4: local inspection UI and runtime integration

- React/TypeScript frontend for inspection, rooms, JPEG/PNG upload, analysis,
  and confirm/edit/reject review, preserving original and approved evidence.
- Scoped transient photo content shared with the analyzer through ImageSource.
- Fake/offline remains the default. Explicit backend `ROOMPROOF_ANALYZER=openai`
  with `ROOMPROOF_OPENAI_MODEL=gpt-6-luna` and backend-only `OPENAI_API_KEY` composes
  the existing adapter; no frontend secret or direct provider call is involved.

Real mode sends prepared images to OpenAI only on explicit analysis and consumes
credits. Human review and reportability selection remain required. This runtime
path has offline integration coverage and passed one controlled UI-driven live
test with `gpt-6-luna`: one analysis returned structured findings, followed by
human Edit & Confirm with original proposal and approved content kept separate.
This verifies integration and account/model access, not accuracy. Memory-only storage loses all data on server restart. See
[frontend setup](frontend/README.md) and [backend configuration](backend/README.md).

## Why visibility and reportability are separate

Early sanity tests exposed a useful product failure: a model can correctly detect
a few tiny specks on an otherwise clean wall, yet produce a false positive if it
treats them as reportable damage. `visible_mark` records whether a real mark exists;
`reportable_damage` records whether it merits a move-in finding. Detecting a mark
does not establish its significance, age, or responsibility.

## Frozen baseline and evolving data contract

`baseline_v1` intentionally retains its original wall/floor scope and seven
categories: scratch, scuff, stain, crack, hole, chipped_paint, and dirt.

The newer `inspection_v1` evaluation/data contract supports wall, floor, door,
trim, and countertop, and adds `chip` for missing/gouged substrate material.
This deliberate mismatch preserves the original baseline for a future
`baseline_v2` comparison. Broader-scope scores must account for baseline_v1's
limitations; category metrics measure per-image presence, not localization.

## Repository and offline checks

- [`ml/`](ml/): Phase 1 AI feasibility and evaluation work.
- [`ml/experiments/`](ml/experiments/): the frozen single-image baseline.
- [`ml/evaluation/`](ml/evaluation/): schemas, batch runner, offline evaluator,
  annotation guide, and synthetic examples.
- [`ml/tests/`](ml/tests/): offline regression tests.
- [`backend/`](backend/): domain, application services, HTTP API, and explicit real AI
  integration; [backend setup and tests](backend/README.md).

For the ML offline tests, from the repository root with Python 3.12:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r ml/requirements.txt
python -m unittest discover -s ml/tests -v
```

Tests require no API key and make no API calls. See the [ML README](ml/README.md)
for optional paid baseline runs and the [annotation guide](ml/evaluation/annotation_guide.md)
for labeling and evaluation instructions.

## Architecture and planned work

Current: standalone ML/evaluation tooling plus the local browser workflow:

```text
React → FastAPI / HTTP schemas → application services → domain / in-memory repository
                                ↓
                         PhotoAnalyzer → fake (default) / OpenAI (explicit injection)
```

Not yet implemented: production image upload and
object storage, persistent database/PostgreSQL, authentication/accounts,
cloud deployment and production
infrastructure. Broader AI V2 evaluation and training also remain planned.
The standalone ML baseline is not integrated into the backend.

## Privacy

Real inspection images, labels, manifests, generated predictions/results, API
credentials, and local environments are intentionally excluded from Git. Public
examples and test fixtures are synthetic. Optional ML baseline inference sends
images to OpenAI; offline evaluation uses saved local predictions without
additional API calls. The default backend uses fake analysis without external AI
calls; the explicitly invoked real adapter sends prepared images to OpenAI.

## Roadmap and current checkpoint

- Phase 1 - AI feasibility and evaluation: complete.
- Phase 2 - backend/domain workflow: complete.
- Phase 3 - AI boundary and provenance: complete; production infrastructure is separate.
- Phase 4 - complete local product: Step 1 polished frontend complete; Step 2 HTTP/photo/review
  workflow complete; Step 3 real runtime complete and live-tested; Step 4 report preview
  and PDF export complete. Hands-on review and final focused review passed.
  Phase 4 Step 4 is complete.
- Phase 5 - productionization: PostgreSQL, durable S3-compatible object storage,
  deployment/configuration/secrets, authentication/authorization, concurrency and
  reliability hardening, observability, and CI/CD.

End of Phase 4 means a complete local end-to-end workflow; end of Phase 5 means
productionized durable infrastructure. Step 4 reports deterministically project
only confirmed + reportable human-approved findings and approved evidence.
Preview remains available while work remains. PDF export requires successful
analysis of every registered photo, completed human review, no active analyses,
and valid approved evidence.
No LLM writes reports. A zero-findings report does not certify absence of damage.
