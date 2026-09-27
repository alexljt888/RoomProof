"""Run unchanged baseline_v1 sequentially; each invocation creates a new run."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError
from PIL import Image
from ml.experiments import vlm_baseline as baseline
from ml.evaluation.schema import DATA_CONTRACT_VERSION, Prediction, file_hash, load_dataset


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def run(manifest: Path, labels: Path, split: str) -> Path:
    images, _ = load_dataset(manifest, labels, check_images=True)
    selected = [entry for entry in images.values() if entry.split == split]
    if not selected:
        raise ValueError('Selected split has no images')
    load_dotenv(baseline.ML_DIR.parent / '.env', override=False)
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key:
        raise ValueError('Set OPENAI_API_KEY before running inference')
    now = datetime.now(timezone.utc)
    schema = baseline.InspectionResult.model_json_schema()
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=baseline.ML_DIR,
            stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    config = {
        'data_contract_version': DATA_CONTRACT_VERSION,
        'experiment': 'baseline_v1', 'timestamp': now.isoformat(),
        'model': baseline.DEFAULT_MODEL, 'prompt': baseline.PROMPT,
        'prompt_hash': digest(baseline.PROMPT), 'output_schema': schema,
        'output_schema_hash': digest(json.dumps(schema, sort_keys=True)),
        'dataset_hash': file_hash(manifest), 'labels_hash': file_hash(labels),
        'git_commit': commit, 'split': split,
    }
    output = baseline.ML_DIR / 'results' / f'{now:%Y%m%dT%H%M%S}_{uuid4().hex[:8]}'
    output.mkdir(parents=True)
    (output / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
    with OpenAI(api_key=key, timeout=90.0, max_retries=2) as client:
        with (output / 'predictions.jsonl').open('x') as stream:
            for entry in selected:
                try:
                    data_url, _ = baseline.prepare_image(manifest.parent / entry.path)
                except (OSError, ValueError, Image.DecompressionBombError) as error:
                    prediction = Prediction(image_id=entry.image_id, status='image_error',
                                            error_type=type(error).__name__)
                else:
                    try:
                        result = baseline.inspect_image(client, data_url, baseline.DEFAULT_MODEL)
                        prediction = Prediction(image_id=entry.image_id, status='ok', result=result)
                    except OpenAIError as error:
                        prediction = Prediction(image_id=entry.image_id, status='api_error',
                                                error_type=type(error).__name__)
                    except ValueError as error:
                        prediction = Prediction(image_id=entry.image_id, status='invalid_response',
                                                error_type=type(error).__name__)
                stream.write(prediction.model_dump_json() + '\n')
                stream.flush()
                print(f'{entry.image_id}: {prediction.status}', flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--split', choices=['development', 'held_out'], required=True)
    args = parser.parse_args()
    print(f'Saved run: {run(args.manifest, args.labels, args.split)}')


if __name__ == '__main__':
    main()
