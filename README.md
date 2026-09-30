# RoomProof

RoomProof is being developed as an AI-assisted move-in inspection system: guide
renters through documenting apartment surfaces, identify and organize visible
damage, support human review, and eventually generate an evidence-backed report.
**AI proposes; the renter confirms.** An AI-generated finding does not
automatically become approved or reportable evidence. Users must review findings
before any future final report is generated.

## Current status: ML evaluation and backend foundation

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

The backend registers **photo metadata only**. Its fake analyzer inspects no image
bytes and performs no real AI inference. State is local to one process and is lost
on restart; this is a development foundation, not a production-ready application.
See the [backend README](backend/README.md) for setup, endpoints, limitations, and
local usage.

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
- [`backend/`](backend/): Phase 2 domain, application services, and HTTP API
  foundation; [backend setup and tests](backend/README.md).

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

Current: standalone Phase 1 ML/evaluation tooling plus a Phase 2 backend:

```text
FastAPI / HTTP schemas → application services → domain / in-memory repository
                                ↓
                         PhotoAnalyzer → deterministic fake analyzer
```

Not yet implemented: real backend image/VLM integration, actual image upload and
object storage, persistent database/PostgreSQL, authentication/accounts,
React/TypeScript frontend, PDF/report generation, cloud deployment, and production
infrastructure. Broader AI V2 evaluation and training also remain planned.
The standalone ML baseline is not integrated into the backend.

## Privacy

Real inspection images, labels, manifests, generated predictions/results, API
credentials, and local environments are intentionally excluded from Git. Public
examples and test fixtures are synthetic. Optional ML baseline inference sends
images to OpenAI; offline evaluation uses saved local predictions without
additional API calls. The Phase 2 backend uses only fake analysis and makes no
external AI calls.
