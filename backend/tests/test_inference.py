from dataclasses import fields
import unittest

from backend.app.domain import AnalysisOutcome, Category, Certainty, FailureCode, InvalidDomainData, Surface
from backend.app.inference import AnalysisOutput, AnalyzerFailure, FakePhotoAnalyzer, ProposedFinding


class InferenceTests(unittest.TestCase):
    def test_explicit_deterministic_scenarios(self):
        proposal = ProposedFinding(Category.SCRATCH, Surface.WALL, "center", "Synthetic scratch", Certainty.CLEAR)
        for outcome, findings in ((AnalysisOutcome.FINDINGS_PRESENT, [proposal]),
                                  (AnalysisOutcome.FINDINGS_PRESENT, [proposal, proposal]),
                                  (AnalysisOutcome.NO_VISIBLE_FINDINGS, []),
                                  (AnalysisOutcome.UNCERTAIN, [])):
            output = AnalysisOutput(outcome, findings, ["Synthetic limitation"])
            fake = FakePhotoAnalyzer(output)
            self.assertEqual(fake.analyze(None), output)
            self.assertEqual(fake.analyze(None), output)
            findings.clear()
            self.assertIsInstance(output.findings, tuple)
        with self.assertRaises(AnalyzerFailure):
            FakePhotoAnalyzer(FailureCode.UNAVAILABLE).analyze(None)

    def test_output_has_no_human_review_fields(self):
        self.assertEqual({f.name for f in fields(ProposedFinding)},
                         {"category", "surface", "location", "description", "certainty"})
        self.assertEqual({f.name for f in fields(AnalysisOutput)}, {"outcome", "findings", "limitations"})
        with self.assertRaises(TypeError):
            AnalysisOutput(AnalysisOutcome.UNCERTAIN, approved=True)

    def test_invalid_output_shapes(self):
        for findings in (None, {}, "text", [object()]):
            with self.assertRaises(InvalidDomainData):
                AnalysisOutput(AnalysisOutcome.UNCERTAIN, findings)
        with self.assertRaises(InvalidDomainData):
            AnalysisOutput(AnalysisOutcome.FINDINGS_PRESENT)
