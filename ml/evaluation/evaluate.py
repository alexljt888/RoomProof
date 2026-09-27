"""Offline metrics: binary decisions and per-image category presence."""
import argparse
import json
from pathlib import Path
from typing import get_args

from ml.evaluation.schema import DATA_CONTRACT_VERSION, Category, Prediction, file_hash, load_dataset, read_jsonl


def ratio(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'value': numerator / denominator if denominator else 'N/A'}


def evaluate(labels, predictions):
    """Missing predictions are errors, not clean images. No API calls."""
    if predictions.keys() - labels.keys():
        raise ValueError('Predictions contain unexpected image IDs')
    total = len(labels)
    api_errors = sum(p.status == 'api_error' for p in predictions.values())
    invalid = sum(p.status == 'invalid_response' for p in predictions.values())
    image_errors = sum(p.status == 'image_error' for p in predictions.values())
    missing = total - len(predictions)
    report = {
        'data_contract_version': DATA_CONTRACT_VERSION,
        'scope': 'All labeled surfaces; baseline_v1 only supports wall/floor and cannot emit chip. No remapping.',
        'total': total, 'missing': missing, 'api_errors': api_errors,
        'invalid_responses': invalid, 'image_errors': image_errors,
        'api_failure_rate': ratio(api_errors, len(predictions) - image_errors),
        'targets': {},
    }
    for target in ('visible_mark', 'reportable_damage'):
        counts = dict(TP=0, FP=0, TN=0, FN=0, uncertain=0, error=0, human_uncertain=0)
        ids = {key: [] for key in counts}
        categories = {category: dict(TP=0, FP=0, FN=0, support=0, evaluated=0)
                      for category in get_args(Category)}
        for image_id, label in labels.items():
            truth = getattr(label, target)
            prediction = predictions.get(image_id)
            if truth == 'uncertain':
                outcome = 'human_uncertain'
            elif prediction is None or prediction.status != 'ok':
                outcome = 'error'
            elif prediction.result.assessment == 'uncertain':
                outcome = 'uncertain'
            else:
                positive = prediction.result.assessment == 'damage_present'
                outcome = ('TP' if truth == 'yes' else 'FP') if positive else (
                    'FN' if truth == 'yes' else 'TN')
            counts[outcome] += 1
            ids[outcome].append(image_id)
            # Category scores use only decisive successful predictions and known labels.
            if outcome not in ('TP', 'FP', 'TN', 'FN'):
                continue
            predicted = {f.category for f in prediction.result.findings if f.certainty == 'clear'}
            actual = {o.category for o in label.observations
                      if target == 'visible_mark' or o.reportable == 'yes'}
            ambiguous = {o.category for o in label.observations if o.reportable == 'uncertain'}
            for category, metric in categories.items():
                if target == 'reportable_damage' and category in ambiguous and category not in actual:
                    continue
                metric['evaluated'] += 1
                metric['support'] += category in actual
                metric['TP'] += category in actual and category in predicted
                metric['FP'] += category not in actual and category in predicted
                metric['FN'] += category in actual and category not in predicted
        tp, fp, tn, fn = (counts[k] for k in ('TP', 'FP', 'TN', 'FN'))
        eligible = total - counts['human_uncertain']
        decided = tp + fp + tn + fn
        metrics = {
            'counts': counts, 'image_ids': ids, 'eligible': eligible,
            'precision': ratio(tp, tp + fp), 'recall': ratio(tp, tp + fn),
            'F1': ratio(2 * tp, 2 * tp + fp + fn),
            'false_positive_rate': ratio(fp, fp + tn),
            'coverage': ratio(decided, eligible),
            'abstention_rate': ratio(counts['uncertain'], eligible),
            'error_rate': ratio(counts['error'], eligible),
        }
        for metric in categories.values():
            metric['precision'] = ratio(metric['TP'], metric['TP'] + metric['FP'])
            metric['recall'] = ratio(metric['TP'], metric['support'])
        metrics['categories'] = categories
        report['targets'][target] = metrics
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    images, labels = load_dataset(args.manifest, args.labels)
    config = json.loads((args.run / 'config.json').read_text())
    if 'data_contract_version' not in config:
        raise ValueError('Run config is missing data_contract_version; legacy unversioned runs are not supported')
    if config['data_contract_version'] != DATA_CONTRACT_VERSION:
        raise ValueError(f'Incompatible data_contract_version; expected {DATA_CONTRACT_VERSION}')
    split = config.get('split')
    if split not in ('development', 'held_out'):
        raise ValueError('Run config split must be development or held_out')
    if config['dataset_hash'] != file_hash(args.manifest) or config['labels_hash'] != file_hash(args.labels):
        raise ValueError('Dataset/labels changed since inference; use the frozen original files')
    selected = {key: label for key, label in labels.items() if images[key].split == split}
    if not selected:
        raise ValueError(f'Selected evaluation split {split} has no images')
    predictions = read_jsonl(args.run / 'predictions.jsonl', Prediction)
    report = evaluate(selected, predictions)
    report['definitions'] = {
        'binary': 'Precision/recall/F1/FPR use decided cases only; inspect coverage alongside them.',
        'rates': 'Coverage, abstention and error rates use human-known labels; human-uncertain excluded.',
        'api_failure': 'API exceptions / attempted API calls; missing and image errors excluded; invalid responses separate.',
        'category': 'Per-image category presence on decided cases, not localization. Support is positive evaluated images.',
    }
    rendered = json.dumps(report, indent=2)
    (args.run / 'metrics.json').write_text(rendered + '\n')
    print(rendered)


if __name__ == '__main__':
    main()
