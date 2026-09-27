# RoomProof

RoomProof is being developed as an AI-assisted move-in inspection system: guide
renters through documenting apartment surfaces, identify and organize visible
damage, support human review, and eventually generate an evidence-backed report.
Users must review AI findings before any final report is generated.

## Current status: ML feasibility and evaluation

Implemented:

- A frozen single-image VLM baseline using the OpenAI Responses API and Pydantic
  Structured Outputs.
- An apartment-surface/damage data contract and human annotation workflow.
- Separate `visible_mark` and `reportable_damage` labels and evaluation.
- Batch inference infrastructure, offline metrics from saved predictions, and
  regression tests using synthetic data and mocked inference.

The current local development collection contains 25 images, including 20 labeled
examples and six historical single-image sanity-test outputs. Those outputs are
not a completed batch benchmark. Dataset expansion is intentionally paused until
later model-comparison and tuning milestones; no production accuracy is claimed.

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

- [`ml/experiments/`](ml/experiments/): the frozen single-image baseline.
- [`ml/evaluation/`](ml/evaluation/): schemas, batch runner, offline evaluator,
  annotation guide, and synthetic examples.
- [`ml/tests/`](ml/tests/): offline regression tests.

From the repository root, with Python 3.12:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r ml/requirements.txt
python -m unittest discover -s ml/tests -v
```

Tests require no API key and make no API calls. See the [ML README](ml/README.md)
for optional paid baseline runs and the [annotation guide](ml/evaluation/annotation_guide.md)
for labeling and evaluation instructions.

## Planned architecture — not implemented

React + TypeScript → REST API → Python/FastAPI → AI inference → object storage /
PostgreSQL → human review → PDF report → cloud deployment and CI/CD.

The frontend, application backend, database, object storage, authentication, PDF
generation, production deployment, and trained/fine-tuned detector are future work.
The current code is an experimentation milestone, not an application.

## Privacy

Real inspection images, labels, manifests, generated predictions/results, API
credentials, and local environments are intentionally excluded from Git. Public
examples and test fixtures are synthetic. API inference sends images to OpenAI;
offline evaluation uses saved local predictions without additional API calls.
