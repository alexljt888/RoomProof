"""Synthetic offline fixtures; no private photos and no API calls."""
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError
from PIL import Image
from ml.evaluation.schema import Label, ManifestEntry, Prediction, load_dataset, read_jsonl, file_hash
from ml.evaluation.evaluate import evaluate
from ml.evaluation import run_batch
from ml.evaluation import evaluate as evaluator
from ml.evaluation.schema import DATA_CONTRACT_VERSION
from openai import OpenAIError
from ml.experiments.vlm_baseline import InspectionResult


def label(i, visible='yes', reportable='yes'):
    observations = ([dict(category='dirt', surface='wall', reportable=reportable)]
                    if visible == 'yes' else [])
    return Label(image_id=i, visible_mark=visible, reportable_damage=reportable,
                 observations=observations)


def prediction(i, assessment='damage_present'):
    findings = ([dict(category='dirt', surface='wall', location='left',
                      evidence='specks', certainty='clear')] * 2
                if assessment == 'damage_present' else [])
    return Prediction(image_id=i, status='ok', result=InspectionResult(
        assessment=assessment, findings=findings, limitations=[]))


class LabelTests(unittest.TestCase):
    def test_separate_targets(self):
        self.assertEqual(label('img_001', reportable='no').reportable_damage, 'no')
        label('img_002', 'uncertain', 'uncertain')
        label('img_003', 'no', 'no')

    def test_contradictions_and_bad_category(self):
        base = label('img_001').model_dump()
        for change in [dict(visible_mark='no'), dict(reportable_damage='no'),
                       dict(observations=[]), dict(image_id='private-name'),
                       dict(observations=[dict(category='mold', surface='wall', reportable='yes')])]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                Label.model_validate({**base, **change})

    def test_dataset_duplicates_splits_and_id_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, labels = Path(tmp) / 'manifest.jsonl', Path(tmp) / 'labels.jsonl'
            rows = [dict(image_id=f'img_00{i}', path=f'{i}.jpg', sha256=str(i)*64,
                         split=split, scene_group='same')
                    for i, split in [(1, 'development'), (2, 'held_out')]]
            labels.write_text('\n'.join(label(r['image_id']).model_dump_json() for r in rows))
            def save():
                manifest.write_text('\n'.join(json.dumps(r) for r in rows))
            save()
            with self.assertRaisesRegex(ValueError, 'crosses'):
                load_dataset(manifest, labels)
            rows[1]['scene_group'] = 'different'
            save()
            self.assertEqual(len(load_dataset(manifest, labels)[0]), 2)
            labels.write_text(label('img_001').model_dump_json())
            with self.assertRaisesRegex(ValueError, 'identical'):
                load_dataset(manifest, labels)
            manifest.write_text(json.dumps(rows[0]) + '\n' + json.dumps(rows[0]))
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                read_jsonl(manifest, ManifestEntry)


class MetricTests(unittest.TestCase):
    def test_specks_true_visual_positive_false_reportable_positive(self):
        metrics = evaluate({'img_001': label('img_001', reportable='no')},
                           {'img_001': prediction('img_001')})['targets']
        self.assertEqual(metrics['visible_mark']['counts']['TP'], 1)
        self.assertEqual(metrics['reportable_damage']['counts']['FP'], 1)
        # Duplicate findings must not double-count category presence.
        self.assertEqual(metrics['visible_mark']['categories']['dirt']['TP'], 1)
        self.assertEqual(metrics['reportable_damage']['categories']['dirt']['FP'], 1)

    def test_confusion_rates_and_missing_predictions(self):
        labels = {f'img_00{i}': label(f'img_00{i}', 'yes' if i != 3 and i != 4 else 'no',
                                    'yes' if i != 3 and i != 4 else 'no') for i in range(1, 8)}
        predictions = {f'img_00{i}': prediction(f'img_00{i}', assessment)
                       for i, assessment in [(1, 'damage_present'), (2, 'no_visible_damage'),
                                             (3, 'damage_present'), (4, 'no_visible_damage'),
                                             (5, 'uncertain')]}
        predictions['img_006'] = Prediction(image_id='img_006', status='api_error')
        report = evaluate(labels, predictions)
        metrics = report['targets']['visible_mark']
        self.assertEqual(metrics['counts'], dict(TP=1, FP=1, TN=1, FN=1, uncertain=1, error=2, human_uncertain=0))
        for name in ['precision', 'recall', 'F1', 'false_positive_rate']:
            self.assertEqual(metrics[name]['value'], 0.5)
        self.assertEqual(metrics['coverage']['denominator'], 7)
        self.assertEqual(metrics['coverage']['numerator'], 4)
        self.assertEqual(report['api_failure_rate']['denominator'], 6)
        self.assertEqual(report['missing'], 1)
        self.assertEqual(metrics['categories']['dirt']['support'], 2)

    def test_undefined_and_human_uncertainty(self):
        report = evaluate({'img_001': label('img_001', 'uncertain', 'uncertain')}, {})
        metric = report['targets']['visible_mark']
        self.assertEqual(metric['counts']['human_uncertain'], 1)
        self.assertEqual(metric['precision']['value'], 'N/A')
        self.assertEqual(metric['coverage']['denominator'], 0)
        with self.assertRaises(ValueError):
            evaluate({}, {'img_001': prediction('img_001')})

    def test_category_unknown_reportability_excluded(self):
        truth = label('img_001')
        # Image has one reportable category and another whose significance is unknown.
        from ml.evaluation.schema import Observation
        truth.observations.append(Observation(category='scratch', surface='wall', reportable='uncertain'))
        report = evaluate({'img_001': truth}, {'img_001': prediction('img_001')})
        categories = report['targets']['reportable_damage']['categories']
        self.assertEqual(categories['scratch']['evaluated'], 0)
        self.assertEqual(categories['dirt']['evaluated'], 1)


class BatchTests(unittest.TestCase):
    def test_mocked_batch_then_offline_evaluation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = root / 'photo.png'
            Image.new('RGB', (8, 8), 'white').save(photo)
            manifest, labels = root / 'manifest.jsonl', root / 'labels.jsonl'
            manifest.write_text(json.dumps(dict(image_id='img_001', path='photo.png',
                sha256=file_hash(photo), split='development', scene_group='scene_001')) + '\n')
            labels.write_text(label('img_001', 'no', 'no').model_dump_json() + '\n')
            result = prediction('img_001', 'no_visible_damage').result
            client = Mock()
            client.__enter__ = Mock(return_value=client)
            client.__exit__ = Mock(return_value=False)
            with patch.object(run_batch.baseline, 'ML_DIR', root), \
                 patch.object(run_batch, 'load_dotenv'), \
                 patch.dict('os.environ', {'OPENAI_API_KEY': 'offline-dummy'}), \
                 patch.object(run_batch, 'OpenAI', return_value=client), \
                 patch.object(run_batch.baseline, 'inspect_image', return_value=result):
                output = run_batch.run(manifest, labels, 'development')
            config = json.loads((output / 'config.json').read_text())
            self.assertEqual(config['labels_hash'], file_hash(labels))
            self.assertEqual(config['prompt_hash'], run_batch.digest(run_batch.baseline.PROMPT))
            saved = read_jsonl(output / 'predictions.jsonl', Prediction)
            self.assertEqual(evaluate({'img_001': label('img_001', 'no', 'no')}, saved)
                             ['targets']['visible_mark']['counts']['TN'], 1)


class ExpandedContractTests(unittest.TestCase):
    def test_all_surfaces_and_new_chip_category(self):
        from ml.evaluation.schema import Surface, Observation
        from typing import get_args
        self.assertEqual(set(get_args(Surface)), {'wall', 'floor', 'door', 'trim', 'countertop'})
        for surface in get_args(Surface):
            with self.subTest(surface=surface):
                observation = Observation(category='chip', surface=surface, reportable='yes',
                                          note='Synthetic substrate loss')
                value = Label(image_id='img006', visible_mark='yes', reportable_damage='yes',
                              observations=[observation])
                self.assertEqual(value.observations[0].note, 'Synthetic substrate loss')
        for field, value in [('category', 'gouge'), ('surface', 'ceiling')]:
            with self.assertRaises(ValidationError):
                Observation.model_validate({**observation.model_dump(), field: value})

    def test_expanded_saved_prediction_and_per_image_presence(self):
        from ml.evaluation.schema import Observation
        truth = Label(image_id='img006', visible_mark='yes', reportable_damage='yes',
                      observations=[Observation(category='chip', surface=s, reportable='yes')
                                    for s in ('door', 'trim')])
        data = dict(assessment='damage_present', limitations=[], findings=[
            dict(category='chip', surface=s, location='edge', evidence='missing fragment', certainty='clear')
            for s in ('door', 'trim')])
        pred = Prediction(image_id='img006', status='ok', result=data)
        report = evaluate({'img006': truth}, {'img006': pred})
        metric = report['targets']['reportable_damage']['categories']['chip']
        self.assertEqual((metric['TP'], metric['support']), (1, 1))
        # Original model response type stays narrow, independent of evaluation types.
        with self.assertRaises(ValidationError):
            InspectionResult.model_validate(data)

    def test_legacy_predictions_and_frozen_schema(self):
        original = prediction('img_001').result.model_dump()
        parsed = Prediction(image_id='img_001', status='ok', result=original)
        self.assertEqual(parsed.result.model_dump(), original)
        from ml.experiments import vlm_baseline
        import hashlib
        baseline_path = Path(vlm_baseline.__file__)
        self.assertEqual(hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
                         '56fa0970c2bd35cb542fdded418da3f3095cbd864ef67bb95ac6f8e29487341d')

    def test_public_examples_validate_without_private_images(self):
        base = Path(__file__).resolve().parents[1] / 'evaluation' / 'examples'
        images, truth = load_dataset(base / 'manifest.jsonl', base / 'labels.jsonl')
        self.assertEqual(len(images), 5)
        self.assertEqual(truth['img004'].observations[0].category, 'chip')

    def test_material_damage_not_remapped_to_paint(self):
        from ml.evaluation.schema import Observation
        truth = Label(image_id='img006', visible_mark='yes', reportable_damage='yes',
                      observations=[Observation(category='chip', surface='floor', reportable='yes')])
        data = dict(assessment='damage_present', limitations=[], findings=[dict(
            category='chipped_paint', surface='floor', location='middle', evidence='light patch', certainty='clear')])
        report = evaluate({'img006': truth}, {'img006': Prediction(image_id='img006', status='ok', result=data)})
        categories = report['targets']['visible_mark']['categories']
        self.assertEqual(categories['chip']['FN'], 1)
        self.assertEqual(categories['chipped_paint']['FP'], 1)


class EvaluatorEntryPointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = self.root / 'manifest.jsonl'
        self.labels = self.root / 'labels.jsonl'
        self.manifest.write_text(json.dumps(dict(
            image_id='img001', path='synthetic.png', sha256='0' * 64,
            split='development', scene_group='synthetic')) + '\n')
        self.labels.write_text(label('img001', 'no', 'no').model_dump_json() + '\n')
        (self.root / 'predictions.jsonl').write_text(
            prediction('img001', 'no_visible_damage').model_dump_json() + '\n')
        self.config = dict(data_contract_version=DATA_CONTRACT_VERSION,
                           dataset_hash=file_hash(self.manifest),
                           labels_hash=file_hash(self.labels), split='development')

    def invoke(self):
        (self.root / 'config.json').write_text(json.dumps(self.config))
        with patch('sys.argv', ['evaluate', '--manifest', str(self.manifest),
                              '--labels', str(self.labels), '--run', str(self.root)]), \
             redirect_stdout(StringIO()):
            evaluator.main()

    def assert_rejected(self, message):
        with self.assertRaisesRegex(ValueError, message):
            self.invoke()
        self.assertFalse((self.root / 'metrics.json').exists())

    def test_compatible_run_writes_metrics(self):
        self.invoke()
        report = json.loads((self.root / 'metrics.json').read_text())
        self.assertEqual(report['total'], 1)
        self.assertEqual(report['targets']['visible_mark']['counts']['TN'], 1)
        self.assertEqual(report['data_contract_version'], DATA_CONTRACT_VERSION)

    def test_incompatible_version_rejected(self):
        self.config['data_contract_version'] = 'inspection_v999'
        self.assert_rejected('Incompatible data_contract_version')

    def test_missing_version_rejected_as_legacy(self):
        del self.config['data_contract_version']
        self.assert_rejected('missing data_contract_version; legacy unversioned')

    def test_empty_split_rejected(self):
        self.config['split'] = 'held_out'
        self.assert_rejected('held_out has no images')

    def test_invalid_or_missing_split_rejected(self):
        for value in ('test', None):
            with self.subTest(split=value):
                self.config['split'] = value
                self.assert_rejected('split must be development or held_out')
        del self.config['split']
        self.assert_rejected('split must be development or held_out')

    def test_dataset_hash_mismatch_rejected(self):
        # Even a formatting-only change must invalidate the frozen manifest hash.
        with self.manifest.open('a') as stream:
            stream.write('\n')
        self.assert_rejected('Dataset/labels changed since inference')

    def test_label_hash_mismatch_rejected(self):
        with self.labels.open('a') as stream:
            stream.write('\n')
        self.assert_rejected('Dataset/labels changed since inference')


class BatchFailureTests(unittest.TestCase):
    def test_failures_are_saved_and_later_images_continue(self):
        for kind, error, expected_status in [
            ('inference', OpenAIError('synthetic API failure'), 'api_error'),
            ('inference', ValueError('synthetic invalid structured output'), 'invalid_response'),
            ('image', OSError('synthetic decode failure'), 'image_error'),
        ]:
            with self.subTest(status=expected_status), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifest, labels = root / 'manifest.jsonl', root / 'labels.jsonl'
                entries = []
                for number, color in [(1, 'white'), (2, 'black')]:
                    photo = root / f'synthetic_{number}.png'
                    Image.new('RGB', (8, 8), color).save(photo)
                    entries.append(dict(image_id=f'img00{number}', path=photo.name,
                                        sha256=file_hash(photo), split='development',
                                        scene_group=f'synthetic_{number}'))
                manifest.write_text(''.join(json.dumps(row) + '\n' for row in entries))
                labels.write_text(''.join(label(row['image_id'], 'no', 'no').model_dump_json()
                                          + '\n' for row in entries))
                result = InspectionResult(assessment='no_visible_damage', findings=[], limitations=[])
                client = Mock()
                client.__enter__ = Mock(return_value=client)
                client.__exit__ = Mock(return_value=False)
                prepared = ('data:image/png;base64,synthetic', {})
                with patch.object(run_batch.baseline, 'ML_DIR', root), \
                     patch.object(run_batch, 'load_dotenv'), \
                     patch.dict('os.environ', {'OPENAI_API_KEY': 'offline-dummy'}), \
                     patch.object(run_batch, 'OpenAI', return_value=client), \
                     patch.object(run_batch.baseline, 'prepare_image',
                                  side_effect=[error, prepared] if kind == 'image'
                                  else [prepared, prepared]) as prepare, \
                     patch.object(run_batch.baseline, 'inspect_image',
                                  side_effect=[error, result] if kind == 'inference'
                                  else [result]) as inspect, redirect_stdout(StringIO()):
                    output = run_batch.run(manifest, labels, 'development')
                saved = read_jsonl(output / 'predictions.jsonl', Prediction)
                self.assertEqual(list(saved), ['img001', 'img002'])
                self.assertEqual(saved['img001'].status, expected_status)
                self.assertEqual(saved['img001'].error_type, type(error).__name__)
                self.assertIsNone(saved['img001'].result)
                self.assertEqual(saved['img002'].status, 'ok')
                self.assertEqual(saved['img002'].result.assessment, 'no_visible_damage')
                self.assertEqual(prepare.call_count, 2)
                self.assertEqual(inspect.call_count, 1 if kind == 'image' else 2)


if __name__ == '__main__':
    unittest.main()
