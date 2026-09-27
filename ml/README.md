# Single-image VLM baseline

This experiment detects visible wall/floor issues, not when they occurred.
It does not generate reports. Every saved prediction has `review_status: pending`
and must be checked by a person before any future report uses it.

## Setup

Use Python 3.12. From the repository root:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r ml/requirements.txt
```

Create a file named `.env` in the repository root with your own API key:

```dotenv
OPENAI_API_KEY=your_actual_api_key_here
```

The existing `.gitignore` excludes `.env`. Never commit or share your key.
An existing `OPENAI_API_KEY` environment variable takes precedence over `.env`.
You need OpenAI API billing and access to the selected model.

## Run

Place a wall/floor photo at `ml/data/test_images/wall.jpg`, then run:

```sh
python ml/experiments/vlm_baseline.py ml/data/test_images/wall.jpg
```

The default is `gpt-4.1-mini-2025-04-14`, a pinned model snapshot with image input
and Structured Outputs support. To choose another compatible model:

```sh
python ml/experiments/vlm_baseline.py ml/data/test_images/wall.jpg --model gpt-4.1-mini
```

Use JPEG or PNG for the first test. Pillow fully decodes the file, corrects EXIF
orientation, converts to RGB, and sends a PNG at the original resolution. The
source file stays unchanged. Animated/multipage files are rejected. HEIC is not
supported by these dependencies; export it as JPEG first.

Each real run uploads the image to OpenAI and incurs API usage. The request uses
`store=False`. The model sees only the image, not its filename or local path.

## Output

The validated prediction is printed as JSON on stdout. The saved-file path is
printed on stderr. Each successful run creates a unique JSON file under
`ml/results/`, resolved relative to the script even when run from another folder.
It includes the prediction, pending review status, UTC timestamp, model, prompt,
schema version, original image hash/path, and oriented dimensions. No image bytes
or secrets are saved in the result.

The prediction contains:

- `assessment`: `damage_present`, `no_visible_damage`, or `uncertain`.
- `findings`: category, wall/floor surface, location, visible evidence, and
  `clear`/`possible` certainty for each issue.
- `limitations`: blur, glare, obstruction, or other visibility issues.

Categories are scratch, scuff, stain, crack, hole, chipped_paint, and dirt.
`damage_present` requires a clear finding; `no_visible_damage` requires no
findings. Unassessable images should produce `uncertain`, not a clean verdict.
Certainty is a qualitative model judgment, not a calibrated probability.

Failures exit with code 1 and do not save a prediction. A refusal or incomplete
response is an error, not `no_visible_damage`. API errors show their exception
type without printing private request/response bodies. Check credentials,
billing, model access, or network connectivity if a request fails.

For later comparisons, run each image separately and join saved predictions to
independent human labels by image hash. Preserve the original AI outputs.
Photos, labels, manifests and results must stay in the Git-ignored data/results folders.

## Offline checks

No API key or network request is needed:

```sh
python -m unittest discover -s ml/tests -v
python ml/experiments/vlm_baseline.py --help
```

The tests use temporary images and a mocked API client; they do not measure
the model's damage-detection accuracy.

API references: [image inputs](https://developers.openai.com/api/docs/guides/images-vision),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[model capabilities](https://developers.openai.com/api/docs/models/gpt-4.1-mini).

## Labeled evaluation

See [the annotation and evaluation guide](evaluation/annotation_guide.md) for
local manifests/labels, development and held-out splits, batch inference, and
metric definitions. The committed [examples](evaluation/examples/) are synthetic
schema examples only; they contain no actual image files.

The local development collection is intentionally paused at 25 images, including
20 labeled records. The six historical single-image sanity-test outputs are not
batch evaluation runs and do not use the batch evaluator's input format. More data
will be added at later model-comparison/reportability-tuning milestones.

Offline evaluation accepts only explicitly versioned `inspection_v1` batch runs.
Unversioned legacy configs and incompatible versions are rejected, as are invalid
or empty splits and changed dataset/label hashes. See the guide for details.

Real `ml/data/` and `ml/results/` contents are now Git-ignored. Keep all private
labels/manifests there. The baseline script remains unchanged. The evaluation
runner uses its existing functions; the evaluator makes no API calls.


The evaluation/data contract `inspection_v1` supports wall, floor, door, trim,
and countertop, with `chip` added for missing/gouged substrate material. This
expansion does **not** change frozen baseline_v1's wall/floor-only prompt or its
seven-category response schema. Broader-scope scores must be interpreted with
that limitation. See the annotation guide for category boundaries and review notes.
