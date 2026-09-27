"""Local dataset and prediction schemas. Run as a module to validate labels."""
import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Category = Literal['scratch', 'scuff', 'stain', 'crack', 'hole', 'chipped_paint', 'dirt', 'chip']
Surface = Literal['wall', 'floor', 'door', 'trim', 'countertop']
DATA_CONTRACT_VERSION = 'inspection_v1'
IMAGE_ID_PATTERN = r'^img_?[0-9]+$'
Verdict = Literal['yes', 'no', 'uncertain']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ManifestEntry(StrictModel):
    image_id: str = Field(pattern=IMAGE_ID_PATTERN)
    path: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    split: Literal['development', 'held_out']
    scene_group: str

    @model_validator(mode='after')
    def relative_path(self) -> Self:
        if Path(self.path).is_absolute() or '..' in Path(self.path).parts:
            raise ValueError('Image path must be relative to the manifest directory')
        return self


class Observation(StrictModel):
    category: Category
    surface: Surface
    reportable: Verdict
    note: str = ''


class Label(StrictModel):
    image_id: str = Field(pattern=IMAGE_ID_PATTERN)
    visible_mark: Verdict
    reportable_damage: Verdict
    observations: list[Observation]
    quality_issues: list[str] = Field(default_factory=list)
    note: str = ''

    @model_validator(mode='after')
    def consistent(self) -> Self:
        if self.observations and self.visible_mark != 'yes':
            raise ValueError('Confirmed observations require visible_mark=yes')
        if self.visible_mark == 'yes' and not self.observations:
            raise ValueError('visible_mark=yes requires a categorized observation')
        expected = ('yes' if any(o.reportable == 'yes' for o in self.observations)
                    else 'uncertain' if self.visible_mark == 'uncertain' or
                    any(o.reportable == 'uncertain' for o in self.observations) else 'no')
        if self.reportable_damage != expected:
            raise ValueError('Reportable label contradicts observations/visibility')
        return self


class EvaluationFinding(StrictModel):
    """Saved prediction vocabulary; does not change any model request schema."""
    category: Category
    surface: Surface
    location: str
    evidence: str
    certainty: Literal['clear', 'possible']


class EvaluationResult(StrictModel):
    assessment: Literal['damage_present', 'no_visible_damage', 'uncertain']
    findings: list[EvaluationFinding]
    limitations: list[str]

    @model_validator(mode='after')
    def consistent(self) -> Self:
        has_clear = any(f.certainty == 'clear' for f in self.findings)
        if (self.assessment == 'damage_present') != has_clear:
            raise ValueError('damage_present must correspond to a clear finding')
        if self.assessment == 'no_visible_damage' and self.findings:
            raise ValueError('no_visible_damage must have no findings')
        return self


class Prediction(StrictModel):
    image_id: str = Field(pattern=IMAGE_ID_PATTERN)
    status: Literal['ok', 'api_error', 'invalid_response', 'image_error']
    result: EvaluationResult | None = None
    error_type: str | None = None
    review_status: Literal['pending'] = 'pending'

    @field_validator('result', mode='before')
    @classmethod
    def accept_baseline_result(cls, value):
        # Accept the original typed baseline output without altering its vocabulary.
        return value.model_dump() if isinstance(value, BaseModel) else value

    @model_validator(mode='after')
    def consistent(self) -> Self:
        if (self.status == 'ok') != (self.result is not None):
            raise ValueError('Only successful predictions may contain a result')
        return self


def read_jsonl(path: Path, model) -> dict:
    records = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = model.model_validate_json(line)
            if item.image_id in records:
                raise ValueError('Duplicate image_id')
            records[item.image_id] = item
        except ValueError as error:
            raise ValueError(f'{path.name}, line {number}: {error}') from error
    return records


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dataset(manifest: Path, labels: Path, check_images=False):
    images = read_jsonl(manifest, ManifestEntry)
    truth = read_jsonl(labels, Label)
    if not images or images.keys() != truth.keys():
        raise ValueError('Manifest and labels must have identical, nonempty ID sets')
    groups, hashes = {}, set()
    for entry in images.values():
        if entry.scene_group in groups and groups[entry.scene_group] != entry.split:
            raise ValueError('A scene_group crosses dataset splits')
        groups[entry.scene_group] = entry.split
        if entry.sha256 in hashes:
            raise ValueError('Duplicate image content in manifest')
        hashes.add(entry.sha256)
        if check_images:
            path = (manifest.parent / entry.path).resolve()
            if not path.is_relative_to(manifest.parent.resolve()):
                raise ValueError('Image resolves outside dataset directory')
            if file_hash(path) != entry.sha256:
                raise ValueError(f'Image hash mismatch: {entry.image_id}')
    return images, truth


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--check-images', action='store_true')
    args = parser.parse_args()
    images, _ = load_dataset(args.manifest, args.labels, args.check_images)
    print(f'Validated {len(images)} labels and manifest records.')
