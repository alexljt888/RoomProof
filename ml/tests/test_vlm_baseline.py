"""Offline checks: no credentials, network, or repository result files."""

import base64
from io import BytesIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from pydantic import ValidationError

from ml.experiments import vlm_baseline as baseline


class BaselineTests(unittest.TestCase):
    def test_orientation_and_source_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rotated.jpg"
            exif = Image.Exif()
            exif[274] = 6  # Rotate 90 degrees clockwise when displayed.
            Image.new("RGB", (20, 10), "white").save(path, exif=exif)
            original = path.read_bytes()
            data_url, metadata = baseline.prepare_image(path)
            with Image.open(BytesIO(base64.b64decode(data_url.split(",", 1)[1]))) as sent:
                self.assertEqual(sent.size, (10, 20))
                self.assertEqual(sent.format, "PNG")
                self.assertIsNone(sent.getexif().get(274))
            self.assertEqual((metadata["width"], metadata["height"]), (10, 20))
            self.assertEqual(path.read_bytes(), original)

    def test_invalid_and_missing_images(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.jpg"
            with self.assertRaises(OSError):
                baseline.prepare_image(path)
            path.write_text("not an image")
            with self.assertRaises(OSError):
                baseline.prepare_image(path)

    def test_schema_and_consistency(self):
        finding = dict(category="scuff", surface="wall", location="lower left",
                       evidence="dark streak", certainty="clear")
        baseline.InspectionResult(assessment="damage_present", findings=[finding], limitations=[])
        baseline.InspectionResult(assessment="uncertain", findings=[], limitations=["blur"])
        for assessment, findings in [
            ("damage_present", []), ("no_visible_damage", [finding]),
            ("uncertain", [finding]),
            ("damage_present", [{**finding, "category": "mold"}]),
        ]:
            with self.subTest(assessment=assessment, findings=findings):
                with self.assertRaises(ValidationError):
                    baseline.InspectionResult(assessment=assessment, findings=findings, limitations=[])

    def test_typed_api_result_and_refusal(self):
        result = baseline.InspectionResult(assessment="no_visible_damage", findings=[], limitations=[])
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=result)
        self.assertIs(baseline.inspect_image(client, "data:image/png;base64,test", "test-model"), result)
        self.assertIs(client.responses.parse.call_args.kwargs["text_format"], baseline.InspectionResult)
        for status in ("completed", "incomplete"):
            client.responses.parse.return_value = SimpleNamespace(status=status, output_parsed=None)
            with self.assertRaises(ValueError):
                baseline.inspect_image(client, "unused", "test-model")

    def test_saves_separate_unreviewed_results(self):
        result = baseline.InspectionResult(assessment="no_visible_damage", findings=[], limitations=[])
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(baseline, "ML_DIR", Path(directory)):
                first = baseline.save_result(result, {"sha256": "test"}, "test-model")
                second = baseline.save_result(result, {"sha256": "test"}, "test-model")
            self.assertNotEqual(first, second)
            saved = json.loads(first.read_text())
            self.assertEqual(saved["review_status"], "pending")
            self.assertEqual(saved["result"], result.model_dump())
            self.assertEqual(saved["image"]["sha256"], "test")


if __name__ == "__main__":
    unittest.main()
