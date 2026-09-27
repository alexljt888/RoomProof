# Small RoomProof evaluation

## Privacy and scope

Keep all real images, manifests, labels, predictions and metrics inside ignored
`ml/data/` and `ml/results/`. Commit this guide, code and synthetic examples only.
The root `.gitignore` ignores `.DS_Store` at every depth in this repository.
Before committing, inspect `git status --short` and `git diff --cached --name-only`.
Never publish local paths, original filenames, hashes, notes or API responses.
API inference still sends images to OpenAI; offline evaluation does not.

## Current collection and later labeling

The current development collection is intentionally paused: 25 local images,
including 20 labeled development records. Six historical single-image sanity-test
outputs are not proper batch evaluation runs and cannot be passed directly to the
batch evaluator. No batch benchmark has been completed.

Add data later when comparing model versions or tuning reportability. At that
point, include reportable damage, clean surfaces, tiny insignificant marks, strong
shadows/texture/reflections, and ambiguous/poor-quality photos. Cover the eight
categories as feasible and reserve independent scenes for held-out evaluation.
All previously inspected sanity-test photos belong in development. The steps below
apply when preparing or extending a dataset; they are not a request to collect now.

1. Put photos under `ml/data/test_images/`. Assign opaque IDs such as `img006` (legacy `img_001` IDs remain valid).
2. Create `ml/data/manifest.jsonl`, one JSON object per line, using the synthetic
   example's structure. `path` is relative to `ml/data/`, not the shell directory.
   Give related views of the same room/wall the same opaque `scene_group`; every
   member of that group must stay in one split (`development` or `held_out`).
   Exact duplicate hashes are rejected.
3. Get each original file's SHA-256 with the offline Python command below and put
   it in the manifest. Example hashes are placeholders, not hashes of real photos.
4. Create `ml/data/labels.jsonl` with the same IDs. View images without seeing
   predictions. Inspect the full photo, then at 100% zoom consistently.
5. Validate before inference. Settle ambiguous annotations where possible, but
   retain `uncertain` when evidence does not support a decision.

```sh
python -c 'import hashlib; from pathlib import Path; print(hashlib.sha256(Path("ml/data/test_images/img_001.jpg").read_bytes()).hexdigest())'
```

## Annotation policy

`visible_mark` means a real surface mark or dirt is visible on wall, floor, door, trim or countertop. Shadows, reflections,
seams and natural texture alone are not marks. `reportable_damage` means the
condition is significant enough to document for human move-in review. It includes
meaningful cleanliness issues, not just physical damage; it does not establish
age, responsibility, or legal liability.

Examples:

| Condition | visible_mark | reportable_damage |
|---|---|---|
| Clean white wall with strong shadow | no | no |
| A few isolated insignificant dark specks | yes | no |
| Clearly visible chipped paint/hole | yes | yes |
| Real scratch, unclear significance | yes | uncertain |
| Too blurred to assess marks | uncertain | uncertain |

Do not infer physical size without a scale. Reportability follows this rubric,
not the model's confidence. Document difficult significance decisions in `note`.
A second person reviewing borderline cases is helpful but not required.

Each confirmed observation has category (scratch, scuff, stain, crack, hole,
chipped_paint, dirt, chip), a supported surface and `reportable` (yes/no/uncertain).
An optional observation-level `note` preserves category ambiguity or distinguishes
separate marks without turning tentative judgments into confident ground truth.
`visible_mark=yes` requires an observation. If even the category is unresolved,
use uncertain/uncertain with no observations and explain in the note. This minimal
schema deliberately avoids guessing category labels. Empty lists represent no
observations or no quality issues. Suggested quality issues: blur, glare,
occlusion, low_light, no_target_surface.

Any reportable observation makes the image reportable. If none is reportable but
one is uncertain, image reportability is uncertain. Otherwise it is no. A visible
mark can be non-reportable: this is the important tiny-speck distinction.

## Run from repository root

Install `ml/requirements.txt` and activate `.venv` as described in the ML README.
Use real local files for these commands, not the synthetic example manifest.

```sh
python -m ml.evaluation.schema --manifest ml/data/manifest.jsonl --labels ml/data/labels.jsonl --check-images
```

Only when ready for paid inference, with `OPENAI_API_KEY` configured:

```sh
python -m ml.evaluation.run_batch --manifest ml/data/manifest.jsonl --labels ml/data/labels.jsonl --split development
```

The runner prints its new directory under `ml/results/`. Substitute that directory:

```sh
python -m ml.evaluation.evaluate --manifest ml/data/manifest.jsonl --labels ml/data/labels.jsonl --run ml/results/RUN_DIRECTORY
```

The evaluator requires `data_contract_version: "inspection_v1"` in `config.json`.
Incompatible versions and older configurations missing this field are rejected;
there is no implicit migration or guessed version. Preserve unversioned historical
runs as archival evidence and use their original evaluation code if needed. Do not
add a version merely to bypass validation. New runs record the version automatically.
The selected split must be `development` or `held_out` and contain at least one
image. Dataset and label hashes must still match the run configuration. Validation
failures stop evaluation before metrics are written.

This last command is offline, prints metrics and writes `metrics.json`. Repeat it
without API costs. To evaluate held-out images, use `--split held_out` only after
freezing the candidate. The runner imports unchanged baseline_v1 functions and
model. Labels and filenames are never part of the model input.

## Metric definitions

For each of visible_mark and reportable_damage, damage_present is a positive
prediction, no_visible_damage negative, and uncertain an abstention. The baseline
has no independent reportability output: scoring it against reportability measures
how well its current findings serve that target, not an explicit significance head.

TP/FP/TN/FN use only known human labels and decisive successful predictions.
Human-uncertain labels are counted separately. Missing/failed predictions on known
labels are errors. The output includes local IDs for every outcome.

- Precision = TP / (TP + FP); recall = TP / (TP + FN).
- F1 = 2TP / (2TP + FP + FN); false-positive rate = FP / (FP + TN).
- Coverage = decided / human-known images.
- Abstention rate = model-uncertain / human-known images.
- Error rate = errors (including missing) / human-known images.
- API failure rate = API-exception records / attempted image-level API calls.
  SDK automatic retries are part of one image-level call. Image errors and missing
  records are excluded from this denominator. Invalid/refused responses are counted
  separately, not mislabeled as transport/API exceptions.

Every rate contains numerator, denominator and value (`N/A` for zero denominator).
Recall/F1 can look better when hard images abstain: always inspect coverage and
abstentions alongside them. Coverage + abstention + error rate sums to 1 when defined.

Categories are **per-image category presence, not localization accuracy**. Only
clear model findings count; repeated categories count once. Visible-mark ground
truth uses all observations; reportability uses only reportable observations.
Category metrics use the same decided cases as binary metrics. Unknown category
reportability is excluded for that category, unless another observation confirms
it. `support` is the number of evaluated positive images, and `evaluated` shows the
category's denominator population. Abstentions/errors are excluded, not clean
predictions. Inspect binary coverage to understand those exclusions.

## Freeze comparisons

Keep the manifest, labels, rubric and baseline fixed for a comparison. Each run
stores the model, exact prompt + hash, output schema + hash, manifest/labels hashes,
Git commit if available, split and timestamp. The manifest includes image hashes,
which are checked before requests. Hashes of manifest/labels use exact file bytes,
so even formatting changes invalidate the match during evaluation.

A Git commit identifies committed code only: commit code before a comparison;
never include local datasets. A pinned model does not guarantee identical outputs.
Do not select the best of repeated calls. Each invocation creates a new run with
one record per image; no resume framework is included. Interrupted runs can be
scored with missing images counted as errors. Use a fresh run for a deliberate
rerun and retain the original.

Tune future baseline_v2 on development data; do not alter baseline_v1. Compare
frozen candidates on the same held-out set and inspect the saved prompt/schema
hashes. If labels need correction, preserve the old local dataset files and create
a new dataset version for subsequent runs. Once held-out examples guide tuning,
they are development evidence, not untouched test data.

## V1 data contract (`inspection_v1`)

This is the evaluation/data vocabulary, distinct from the frozen **baseline_v1**
model contract. Saved predictions accept the expanded vocabulary and original
baseline outputs. The batch runner still sends baseline_v1's original prompt and
output schema: wall/floor only, seven original categories. It cannot emit `chip`.
No labels are coerced to wall/floor, scratch, or chipped_paint to fit that model.
Metrics cover all labeled observations. Unsupported cases therefore measure a
scope limitation as well as detection performance; do not describe them as a
fair within-scope comparison. Category metrics remain per-image category presence,
not surface assignment or localization accuracy. A scratch on a wrong predicted
surface can still receive category-presence credit.

### Surfaces

- `wall`: main vertical wall surface.
- `floor`: walking surface, including wood-like flooring and carpet.
- `door`: door panel/leaf, not its surrounding frame.
- `trim`: frames, casings, baseboards and narrow finishing strips.
- `countertop`: worktop/counter surface, regardless of its apparent material.

Use separate observations for damage on different surfaces. Several marks of the
same category/surface/reportability may be grouped; separate them when significance
or interpretation differs. Do not label a structural boundary, wood grain, stone
veining, reflection or shadow as damage merely because it is visually distinct.

### Eight small categories

| Category | Meaning |
|---|---|
| scratch | Linear abrasion/incised mark without clear substantial material loss |
| scuff | Superficial rubbed/transferred mark; depth or material loss not evident |
| stain | Discoloration; do not infer chemical cause or permanence |
| crack | Visible fissure/split, not a seam or natural pattern |
| hole | Local opening/puncture, rather than a shallow missing surface fragment |
| chipped_paint | Flaking/peeling/chipping of paint or surface coating |
| dirt | Apparent surface debris, grime or residue; no assertion it is removable |
| chip | Localized missing/gouged surface material, such as wood/laminate/stone; not merely paint loss |

`chip` is the sole added category. Do not label the same ambiguous defect as both
scratch and chip merely to hedge. Preserve the initial human category and note
alternatives for review. When both coating and underlying material loss are clearly
separate observations, represent them separately. A reportable chip can be small;
size alone does not determine reportability. Tiny superficial specks may be real
and non-reportable. The visible_mark/reportable_damage distinction is unchanged.
No tags field is supported; record review context in notes.

### Local dataset preparation

Images used to design this contract belong in development, even without API runs.
Reserve independently collected scenes for held-out evaluation. When scene identity
is unknown, a collection-wide opaque scene_group is a conservative temporary choice:
it prevents a future split from separating potentially related images. Confirm real
scene groups manually before any split reassignment; it is not a claim that every
photo depicts one room. Category-ambiguous labels are provisional even if their
image-level visible/reportable decisions are human-reviewed.

Use only synthetic records in committed examples/tests. Keep actual annotations,
file hashes and any review checklist under the ignored data directory. The manifest
may cover a selected subset of files in test_images; every included ID needs exactly
one label. Preserve original image bytes and filename case when creating hashes.
