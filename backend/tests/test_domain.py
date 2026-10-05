"""Synthetic, offline tests; no ML or service dependencies."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from itertools import product
import unittest
from uuid import UUID

from backend.app.domain import (
    Analysis, AnalysisOutcome, AnalysisResult, AnalysisStatus, ApprovedContent,
    Category, Certainty, FailureCode, Finding, FindingProposal, FindingReview,
    FindingState, Inspection, InvalidDomainData, Photo, PropertyDetails,
    ReviewAction, Room, Surface, TransitionConflict,
)


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.inspection = Inspection(PropertyDetails("123 Example Street", "A"), "Example Renter")
        self.room = Room(self.inspection, "Living room")
        self.photo = Photo(self.room, "example.jpg", "image/jpeg", Surface.FLOOR)
        self.analysis = Analysis(self.photo, "synthetic", "v1")
        self.analysis.complete(AnalysisOutcome.FINDINGS_PRESENT)
        self.proposal = FindingProposal(Category.SCRATCH, Surface.WALL, "center", "large scratch", Certainty.CLEAR, (self.photo,))

    def finding(self, **kwargs):
        return Finding(self.analysis, replace(self.proposal, evidence_photos=kwargs["photos"]) if "photos" in kwargs else self.proposal)

    def edited(self, reportable=True):
        return ApprovedContent(Category.SCUFF, Surface.WALL, "lower center", "small scuff", reportable, self.proposal.evidence_photos)

    def test_new_clear_finding_requires_review(self):
        finding = self.finding()
        self.assertEqual(finding.state, FindingState.PENDING_REVIEW)
        self.assertIsNone(finding.review)
        self.assertFalse(finding.eligible_for_report)
        self.assertEqual(finding.original_proposal.certainty, Certainty.CLEAR)

    def test_confirm_copies_original_and_requires_reportability(self):
        for reportable in (True, False):
            with self.subTest(reportable=reportable):
                finding = self.finding()
                finding.confirm(reportable=reportable)
                self.assertEqual(finding.state, FindingState.CONFIRMED)
                self.assertEqual(finding.review.action, ReviewAction.CONFIRM)
                self.assertEqual(finding.review.approved, ApprovedContent(Category.SCRATCH, Surface.WALL, "center", "large scratch", reportable, (self.photo,)))
                self.assertIs(finding.original_proposal, self.proposal)
                self.assertEqual(finding.eligible_for_report, reportable)
        with self.assertRaises(TypeError):
            self.finding().confirm()

    def test_edit_preserves_original_and_records_action(self):
        finding = self.finding()
        finding.edit_and_confirm(self.edited())
        self.assertEqual(finding.state, FindingState.CONFIRMED)
        self.assertEqual(finding.review.action, ReviewAction.EDIT_AND_CONFIRM)
        self.assertEqual(finding.review.approved, self.edited())
        self.assertEqual(finding.original_proposal.description, "large scratch")
        self.assertEqual(finding.original_proposal.category, Category.SCRATCH)
        self.assertTrue(finding.eligible_for_report)
        other = self.finding()
        other.edit_and_confirm(self.edited(False))
        self.assertFalse(other.eligible_for_report)

    def test_reject_with_and_without_reason(self):
        for reason in (None, "Insignificant mark"):
            finding = self.finding()
            finding.reject(reason)
            self.assertEqual(finding.state, FindingState.REJECTED)
            self.assertEqual(finding.review.reason, reason)
            self.assertIsNone(finding.review.approved)
            self.assertFalse(finding.eligible_for_report)

    def test_all_second_review_transitions_conflict(self):
        actions = (lambda f: f.confirm(reportable=True), lambda f: f.edit_and_confirm(self.edited()), lambda f: f.reject())
        for first, second in product(actions, repeat=2):
            finding = self.finding()
            first(finding)
            review = finding.review
            with self.assertRaisesRegex(TransitionConflict, "already reviewed"):
                second(finding)
            self.assertIs(finding.review, review)

    def test_ids_and_timestamps_are_generated_and_frozen(self):
        finding = self.finding()
        finding.confirm(reportable=True)
        for entity in (self.inspection, self.room, self.photo, self.analysis, finding):
            self.assertIsInstance(entity.id, UUID)
            self.assertEqual(entity.created_at.utcoffset(), timedelta(0))
            for attr in ("id", "created_at"):
                with self.assertRaises(FrozenInstanceError):
                    setattr(entity, attr, None)
        self.assertEqual(finding.review.reviewed_at.utcoffset(), timedelta(0))
        self.assertEqual(self.analysis.result.completed_at.utcoffset(), timedelta(0))
        self.assertNotEqual(self.finding().id, finding.id)
        with self.assertRaises(TypeError):
            Inspection(PropertyDetails("Example"), "Renter", id=finding.id)

    def test_history_cannot_be_reassigned(self):
        finding = self.finding()
        finding.edit_and_confirm(self.edited())
        for obj, attr in ((finding.original_proposal, "description"), (finding.review.approved, "reportable"), (finding.review, "reviewed_at"), (finding, "original_proposal"), (finding, "_review"), (finding.original_proposal, "evidence_photos"), (finding.review.approved, "evidence_photos"), (self.analysis, "_result"), (self.analysis.result, "completed_at")):
            with self.subTest(attribute=attr):
                with self.assertRaises(FrozenInstanceError):
                    setattr(obj, attr, None)

    def test_multiple_evidence_and_defensive_copy(self):
        other = Photo(self.room, "second.png", "image/png")
        photos = [self.photo, other]
        finding = self.finding(photos=photos)
        photos.clear()
        self.assertEqual(finding.original_proposal.evidence_photos, (self.photo, other))
        self.assertEqual(finding.source_analysis_id, self.analysis.id)
        self.assertEqual(finding.inspection_id, self.inspection.id)
        self.assertEqual(finding.room_id, self.room.id)

    def test_invalid_evidence(self):
        different_room = Photo(Room(self.inspection, "Kitchen"), "room.jpg", "image/jpeg")
        different_inspection = Photo(Room(Inspection(PropertyDetails("Other Example"), "Other Renter"), "Living room"), "other.jpg", "image/jpeg")
        same_room = Photo(self.room, "other.jpg", "image/jpeg")
        for photos in ((), (self.photo, self.photo), (same_room,), (self.photo, different_room), (self.photo, different_inspection), ("not a photo",)):
            with self.subTest(photos=photos):
                with self.assertRaises(InvalidDomainData):
                    self.finding(photos=photos)

    def test_photo_without_findings_and_hint_is_not_classification(self):
        self.assertEqual(self.photo.capture_surface_hint, Surface.FLOOR)
        self.assertEqual(self.finding().original_proposal.surface, Surface.WALL)
        self.assertEqual(self.photo.inspection_id, self.inspection.id)
        self.assertEqual(self.photo.room_id, self.room.id)

    def test_no_paths_urls_or_bytes_as_photo_metadata(self):
        for filename in ("/tmp/private.jpg", "../private.jpg", "https://example.test/image", "C:\\private.jpg", b"image", ""):
            with self.assertRaises(InvalidDomainData):
                Photo(self.room, filename, "image/jpeg")
        with self.assertRaises(InvalidDomainData):
            Photo(self.room, "file.txt", "text/plain")

    def test_empty_success_differs_from_failure(self):
        empty = Analysis(self.photo, "synthetic", "v1")
        failed = Analysis(self.photo, "synthetic", "v1")
        self.assertEqual(empty.status, AnalysisStatus.PENDING)
        empty.complete(AnalysisOutcome.NO_VISIBLE_FINDINGS)
        failed.fail(FailureCode.UNAVAILABLE)
        self.assertEqual(empty.status, AnalysisStatus.SUCCEEDED)
        self.assertEqual(empty.result.outcome, AnalysisOutcome.NO_VISIBLE_FINDINGS)
        self.assertIsNone(empty.result.failure_code)
        self.assertEqual(failed.status, AnalysisStatus.FAILED)
        self.assertIsNone(failed.result.outcome)
        self.assertEqual(failed.result.failure_code, FailureCode.UNAVAILABLE)
        for analysis in (empty, failed, Analysis(self.photo, "synthetic", "v1")):
            with self.assertRaises(InvalidDomainData):
                Finding(analysis, self.proposal)

    def test_analysis_terminal_and_limitations_copied(self):
        limitations = ["Low light"]
        analysis = Analysis(self.photo, "synthetic", "v1")
        analysis.complete(AnalysisOutcome.UNCERTAIN, limitations)
        limitations.clear()
        self.assertEqual(analysis.result.limitations, ("Low light",))
        self.assertEqual(Finding(analysis, self.proposal).state, FindingState.PENDING_REVIEW)
        for operation in (lambda: analysis.complete(AnalysisOutcome.NO_VISIBLE_FINDINGS), lambda: analysis.fail(FailureCode.UNAVAILABLE)):
            with self.assertRaises(TransitionConflict):
                operation()
        with self.assertRaises(InvalidDomainData):
            AnalysisResult(AnalysisStatus.FAILED, analysis.attempt_provenance, failure_code="raw provider exception")
        with self.assertRaises(InvalidDomainData):
            AnalysisResult(AnalysisStatus.SUCCEEDED, analysis.attempt_provenance, AnalysisOutcome.NO_VISIBLE_FINDINGS, failure_code=FailureCode.UNAVAILABLE)

    def test_invalid_content_and_review_combinations(self):
        cases = (
            lambda: PropertyDetails(" "),
            lambda: Inspection("address", "Renter"),
            lambda: Room("inspection-id", "Living room"),
            lambda: Photo("room-id", "image.jpg", "image/jpeg"),
            lambda: FindingProposal("scratch", Surface.WALL, "center", "mark", Certainty.CLEAR, (self.photo,)),
            lambda: ApprovedContent(Category.SCUFF, Surface.WALL, "center", "mark", 1, (self.photo,)),
            lambda: FindingReview(ReviewAction.REJECT, self.edited()),
            lambda: FindingReview(ReviewAction.CONFIRM),
            lambda: FindingReview(ReviewAction.CONFIRM, self.edited(), "reason"),
        )
        for case in cases:
            with self.assertRaises(InvalidDomainData):
                case()
        finding = self.finding()
        with self.assertRaises(InvalidDomainData):
            finding.confirm(reportable="yes")
        self.assertEqual(finding.state, FindingState.PENDING_REVIEW)

    def test_original_source_required_and_confirm_copies_evidence(self):
        other = Photo(self.room, "clearer.jpg", "image/jpeg")
        with self.assertRaises(InvalidDomainData):
            Finding(self.analysis, replace(self.proposal, evidence_photos=(other,)))
        finding = self.finding(photos=[self.photo, other])
        original = finding.original_proposal
        finding.confirm(reportable=True)
        self.assertEqual(finding.review.approved.evidence_photos, (self.photo, other))
        self.assertIs(finding.original_proposal, original)
        self.assertEqual(original.evidence_photos, (self.photo, other))

    def test_replacement_evidence_preserves_original_and_provenance(self):
        other = Photo(self.room, "clearer.jpg", "image/jpeg")
        original_photos = [self.photo]
        approved_photos = [other]
        finding = self.finding(photos=original_photos)
        approved = replace(self.edited(), evidence_photos=approved_photos)
        finding.edit_and_confirm(approved)
        original_photos.clear()
        approved_photos.clear()
        self.assertEqual(finding.review.approved, approved)
        self.assertEqual(finding.review.approved.evidence_photos, (other,))
        self.assertEqual(finding.original_proposal.evidence_photos, (self.photo,))
        self.assertIs(finding.source_analysis, self.analysis)
        self.assertEqual(finding.source_analysis.photo_id, self.photo.id)
        self.assertEqual(finding.state, FindingState.CONFIRMED)

    def test_edit_retains_evidence_when_snapshot_copies_original(self):
        finding = self.finding()
        approved = ApprovedContent(
            Category.SCUFF, Surface.WALL, "center", "small mark", False,
            finding.original_proposal.evidence_photos,
        )
        finding.edit_and_confirm(approved)
        self.assertEqual(finding.review.approved, approved)
        self.assertEqual(finding.review.approved.evidence_photos, (self.photo,))
        self.assertFalse(finding.eligible_for_report)

    def test_foreign_approved_evidence_rejected_without_review(self):
        rooms = (Room(self.inspection, "Kitchen"),
                 Room(Inspection(PropertyDetails("Other example"), "Renter"), "Room"))
        for room in rooms:
            with self.subTest(room=room.name):
                foreign = Photo(room, "foreign.jpg", "image/jpeg")
                finding = self.finding()
                with self.assertRaises(InvalidDomainData):
                    finding.edit_and_confirm(replace(self.edited(), evidence_photos=(foreign,)))
                self.assertIsNone(finding.review)
                self.assertEqual(finding.state, FindingState.PENDING_REVIEW)

    def test_evidence_collection_validation_for_both_snapshots(self):
        invalid = (None, {}, {"photo": self.photo}, "photo", b"photo", 1,
                   {self.photo}, iter([self.photo]), (), [],
                   (self.photo, self.photo), [None], ["photo"], [[self.photo]])
        for value in invalid:
            for snapshot in (self.proposal, self.edited()):
                with self.subTest(container=type(value).__name__, snapshot=type(snapshot).__name__):
                    with self.assertRaises(InvalidDomainData):
                        replace(snapshot, evidence_photos=value)

    def test_limitations_container_and_member_validation(self):
        invalid = (None, {}, {"low light": "discarded"}, "low light", b"light",
                   1, {"light"}, iter(["light"]), [None], [1], [["light"]], [""])
        for value in invalid:
            with self.subTest(container=type(value).__name__):
                analysis = Analysis(self.photo, "synthetic", "v1")
                with self.assertRaises(InvalidDomainData):
                    analysis.complete(AnalysisOutcome.UNCERTAIN, value)
                self.assertEqual(analysis.status, AnalysisStatus.PENDING)
                self.assertIsNone(analysis.result)

    def test_invalid_second_review_payloads_always_conflict(self):
        first_actions = (lambda f: f.confirm(reportable=True),
                         lambda f: f.edit_and_confirm(self.edited()),
                         lambda f: f.reject())
        invalid_actions = (lambda f: f.confirm(reportable="yes"),
                           lambda f: f.edit_and_confirm(None),
                           lambda f: f.reject(123))
        for first, second in product(first_actions, invalid_actions):
            finding = self.finding()
            first(finding)
            review = finding.review
            with self.assertRaises(TransitionConflict):
                second(finding)
            self.assertIs(finding.review, review)
        for action in invalid_actions:
            finding = self.finding()
            with self.assertRaises(InvalidDomainData):
                action(finding)
            self.assertIsNone(finding.review)


class ProvenanceTests(unittest.TestCase):
    def test_validation_and_terminal_consistency(self):
        from dataclasses import FrozenInstanceError, replace
        from backend.app.domain import AnalysisProvenance
        configured = AnalysisProvenance('synthetic', '1', requested_model='model',
                                        prompt_version='p1', prompt_sha256='a' * 64)
        for changes in ({'analyzer_id': ' '}, {'requested_model': ''},
                        {'prompt_sha256': 'x' * 64}, {'schema_version': 's1'},
                        {'original_sha256': 'a' * 64}, {'prompt_version': None}):
            with self.subTest(changes=changes), self.assertRaises(InvalidDomainData):
                replace(configured, **changes)
        photo = Photo(Room(Inspection(PropertyDetails('Example'), 'Renter'), 'Room'), 'a.png', 'image/png')
        analysis = Analysis(photo, 'synthetic', '1', configured)
        self.assertEqual(analysis.attempt_provenance, configured)
        with self.assertRaises(FrozenInstanceError):
            configured.requested_model = 'other'
        for bad in (replace(configured, analyzer_id='other'),
                    replace(configured, requested_model='different'),
                    replace(configured, requested_model=None)):
            with self.assertRaises(InvalidDomainData):
                analysis.complete(AnalysisOutcome.NO_VISIBLE_FINDINGS, provenance=bad)
            self.assertEqual(analysis.status, AnalysisStatus.PENDING)
        final = replace(configured, provider_model='reported')
        analysis.complete(AnalysisOutcome.NO_VISIBLE_FINDINGS, provenance=final)
        with self.assertRaises(FrozenInstanceError):
            analysis.result.provenance = configured
        with self.assertRaises(TransitionConflict):
            analysis.fail(FailureCode.UNAVAILABLE, provenance=final)


if __name__ == "__main__":
    unittest.main()
