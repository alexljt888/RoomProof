from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import unittest
from uuid import uuid4

from backend.app.domain import (AnalysisProvenance, AnalysisOutcome, AnalysisStatus, Category, Certainty,
                               FailureCode, FindingState, InvalidDomainData,
                               PropertyDetails, Surface, TransitionConflict)
from backend.app.inference import AnalyzerExecution, AnalysisOutput, AnalyzerFailure, FakePhotoAnalyzer, ProposedFinding
from backend.app.repository import InMemoryInspectionRepository, NotFound
from backend.app.services import InspectionService


def proposal():
    return ProposedFinding(Category.SCRATCH, Surface.WALL, "center", "Synthetic scratch", Certainty.CLEAR)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryInspectionRepository()
        self.service = InspectionService(self.repo, FakePhotoAnalyzer(
            AnalysisOutput(AnalysisOutcome.FINDINGS_PRESENT, (proposal(),))))
        state = self.service.create_inspection(PropertyDetails("Example address"), "Example renter")
        self.iid = state.inspection.id
        state = self.service.add_room(self.iid, "Room")
        self.rid = next(iter(state.rooms))
        state = self.service.register_photo(self.iid, self.rid, "example.jpg", "image/jpeg")
        self.pid = next(iter(state.photos))

    def analyze(self):
        return self.service.analyze_photo(self.iid, self.pid)

    def edit(self, fid, **changes):
        values = dict(category=Category.SCUFF, surface=Surface.WALL,
                      location="lower", description="Small mark", reportable=True)
        values.update(changes)
        return self.service.edit_and_confirm_finding(self.iid, fid, **values)

    def test_full_workflow_and_snapshot_isolation(self):
        state = self.analyze()
        finding = next(iter(state.findings.values()))
        self.assertEqual(finding.state, FindingState.PENDING_REVIEW)
        self.assertFalse(finding.eligible_for_report)
        finding.confirm(reportable=True)  # Returned copy cannot approve stored state.
        stored = self.service.get_inspection(self.iid)
        self.assertEqual(stored.findings[finding.id].state, FindingState.PENDING_REVIEW)
        state = self.service.confirm_finding(self.iid, finding.id, reportable=True)
        self.assertTrue(state.findings[finding.id].eligible_for_report)
        with self.assertRaises(TransitionConflict):
            self.service.reject_finding(self.iid, finding.id)

    def test_zero_uncertain_and_multiple(self):
        for output in (AnalysisOutput(AnalysisOutcome.NO_VISIBLE_FINDINGS),
                       AnalysisOutput(AnalysisOutcome.UNCERTAIN, limitations=("Low visibility",)),
                       AnalysisOutput(AnalysisOutcome.FINDINGS_PRESENT, (proposal(), proposal()))):
            with self.subTest(outcome=output.outcome):
                self.setUp()
                self.service.analyzer = FakePhotoAnalyzer(output)
                state = self.analyze()
                analysis = next(iter(state.analyses.values()))
                self.assertEqual(analysis.status, AnalysisStatus.SUCCEEDED)
                self.assertEqual(analysis.result.outcome, output.outcome)
                self.assertEqual(len(state.findings), len(output.findings))
                self.assertTrue(all(f.state == FindingState.PENDING_REVIEW for f in state.findings.values()))
                with self.assertRaises(TransitionConflict):
                    self.analyze()

    def test_failed_analysis_allows_retry(self):
        self.service.analyzer = FakePhotoAnalyzer(FailureCode.UNAVAILABLE)
        state = self.analyze()
        self.assertEqual(state.findings, {})
        failed = next(iter(state.analyses.values()))
        self.assertEqual(failed.status, AnalysisStatus.FAILED)
        self.service.analyzer = FakePhotoAnalyzer(AnalysisOutput(AnalysisOutcome.FINDINGS_PRESENT, (proposal(),)))
        state = self.analyze()
        self.assertEqual(len(state.analyses), 2)
        self.assertEqual(state.analyses[failed.id].status, AnalysisStatus.FAILED)
        self.assertEqual(len(state.findings), 1)

    def test_invalid_later_proposal_rolls_back_all_findings(self):
        invalid = ProposedFinding(Category.SCRATCH, Surface.WALL, "", "Invalid", Certainty.CLEAR)
        self.service.analyzer = FakePhotoAnalyzer(AnalysisOutput(
            AnalysisOutcome.FINDINGS_PRESENT, (proposal(), invalid)))
        state = self.analyze()
        self.assertEqual(state.findings, {})
        result = next(iter(state.analyses.values())).result
        self.assertEqual(result.failure_code, FailureCode.INVALID_RESPONSE)

    def test_unexpected_provider_exception_is_safe(self):
        class Broken:
            analyzer_id = "broken"
            analyzer_version = "1"
            configured_provenance = AnalysisProvenance(analyzer_id, analyzer_version)
            def analyze(self, photo):
                raise RuntimeError("synthetic private provider diagnostic")
        self.service.analyzer = Broken()
        state = self.analyze()
        self.assertEqual(state.findings, {})
        self.assertEqual(next(iter(state.analyses.values())).result.failure_code, FailureCode.UNAVAILABLE)
        self.assertNotIn("diagnostic", repr(state))

    def test_cross_inspection_resources_are_not_found(self):
        other = self.service.create_inspection(PropertyDetails("Other example"), "Renter").inspection.id
        fid = next(iter(self.analyze().findings))
        for call in (lambda: self.service.register_photo(other, self.rid, "image.jpg", "image/jpeg"),
                     lambda: self.service.analyze_photo(other, self.pid),
                     lambda: self.service.confirm_finding(other, fid, reportable=True),
                     lambda: self.service.add_room(uuid4(), "Room")):
            with self.assertRaises(NotFound):
                call()

    def test_edit_evidence_and_preserve_provenance(self):
        fid = next(iter(self.analyze().findings))
        state = self.service.register_photo(self.iid, self.rid, "clearer.jpg", "image/jpeg")
        replacement = next(pid for pid in state.photos if pid != self.pid)
        state = self.edit(fid, evidence_photo_ids=[replacement])
        finding = state.findings[fid]
        self.assertEqual(finding.original_proposal.category, Category.SCRATCH)
        self.assertEqual(finding.original_proposal.evidence_photos[0].id, self.pid)
        self.assertEqual(finding.source_analysis.photo_id, self.pid)
        self.assertEqual(finding.review.approved.evidence_photos[0].id, replacement)
        self.assertEqual(finding.review.approved.category, Category.SCUFF)
        self.assertTrue(finding.eligible_for_report)

    def test_invalid_evidence_does_not_review(self):
        fid = next(iter(self.analyze().findings))
        state = self.service.add_room(self.iid, "Other room")
        rid = next(rid for rid in state.rooms if rid != self.rid)
        state = self.service.register_photo(self.iid, rid, "other.jpg", "image/jpeg")
        foreign = next(pid for pid in state.photos if pid != self.pid)
        for evidence, error in (([uuid4()], NotFound), ([foreign], InvalidDomainData),
                                ([], InvalidDomainData), ([self.pid, self.pid], InvalidDomainData),
                                ({}, InvalidDomainData), ([[]], InvalidDomainData)):
            with self.assertRaises(error):
                self.edit(fid, evidence_photo_ids=evidence)
        self.assertEqual(self.service.get_inspection(self.iid).findings[fid].state, FindingState.PENDING_REVIEW)

    def test_nonreportable_rejected_and_retained_evidence(self):
        fid = next(iter(self.analyze().findings))
        state = self.edit(fid, reportable=False)
        self.assertFalse(state.findings[fid].eligible_for_report)
        self.assertEqual(state.findings[fid].review.approved.evidence_photos[0].id, self.pid)
        self.setUp()
        fid = next(iter(self.analyze().findings))
        state = self.service.reject_finding(self.iid, fid, "Not damage")
        self.assertFalse(state.findings[fid].eligible_for_report)
        self.assertIsNone(state.findings[fid].review.approved)
        with self.assertRaises(TransitionConflict):
            self.edit(fid, evidence_photo_ids={})

    def test_competing_reviews_only_one_succeeds(self):
        fid = next(iter(self.analyze().findings))
        barrier = Barrier(2)
        def review():
            barrier.wait(timeout=3)
            try:
                self.service.confirm_finding(self.iid, fid, reportable=True)
                return "confirmed"
            except TransitionConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: review(), range(2)))
        self.assertCountEqual(results, ["confirmed", "conflict"])

    def test_in_progress_reservation_and_analyzer_outside_lock(self):
        started, release = Event(), Event()
        class Blocking:
            analyzer_id = "blocking-fake"
            analyzer_version = "1"
            configured_provenance = AnalysisProvenance(analyzer_id, analyzer_version)
            def analyze(self, photo):
                started.set()
                if not release.wait(timeout=5):
                    raise RuntimeError("test release timed out")
                return AnalyzerExecution(AnalysisOutput(AnalysisOutcome.NO_VISIBLE_FINDINGS), self.configured_provenance)
        self.service.analyzer = Blocking()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.analyze)
            try:
                self.assertTrue(started.wait(timeout=3))
                # This must finish before releasing the analyzer, proving no lock held.
                duplicate = pool.submit(self.analyze)
                with self.assertRaises(TransitionConflict):
                    duplicate.result(timeout=3)
                state = self.service.get_inspection(self.iid)
                self.assertEqual(next(iter(state.analyses.values())).status, AnalysisStatus.PENDING)
            finally:
                release.set()
            self.assertEqual(len(first.result(timeout=3).analyses), 1)


    def test_wrong_return_type_is_invalid_response(self):
        class WrongType:
            analyzer_id = "wrong-type"
            analyzer_version = "1"
            configured_provenance = AnalysisProvenance(analyzer_id, analyzer_version)
            def analyze(self, photo):
                return {"outcome": "synthetic private invalid object"}
        self.service.analyzer = WrongType()
        state = self.analyze()
        self.assertEqual(state.findings, {})
        result = next(iter(state.analyses.values())).result
        self.assertEqual(result.status, AnalysisStatus.FAILED)
        self.assertEqual(result.failure_code, FailureCode.INVALID_RESPONSE)
        self.assertNotIn("private invalid object", repr(state))

    def test_output_construction_failure_is_invalid_response(self):
        class InvalidConstruction:
            analyzer_id = "invalid-construction"
            analyzer_version = "1"
            configured_provenance = AnalysisProvenance(analyzer_id, analyzer_version)
            def analyze(self, photo):
                return AnalysisOutput(AnalysisOutcome.FINDINGS_PRESENT, findings=None)
        self.service.analyzer = InvalidConstruction()
        state = self.analyze()
        self.assertEqual(state.findings, {})
        result = next(iter(state.analyses.values())).result
        self.assertEqual(result.status, AnalysisStatus.FAILED)
        self.assertEqual(result.failure_code, FailureCode.INVALID_RESPONSE)

    def test_explicit_failure_code_preserved(self):
        class ExplicitFailure:
            analyzer_id = "explicit-failure"
            analyzer_version = "1"
            configured_provenance = AnalysisProvenance(analyzer_id, analyzer_version)
            def analyze(self, photo):
                raise AnalyzerFailure(FailureCode.UNREADABLE_IMAGE)
        self.service.analyzer = ExplicitFailure()
        state = self.analyze()
        self.assertEqual(state.findings, {})
        result = next(iter(state.analyses.values())).result
        self.assertEqual(result.status, AnalysisStatus.FAILED)
        self.assertEqual(result.failure_code, FailureCode.UNREADABLE_IMAGE)

    def test_cross_inspection_replacement_evidence_rejected(self):
        fid = next(iter(self.analyze().findings))
        other = self.service.create_inspection(PropertyDetails("Other example"), "Renter")
        iid = other.inspection.id
        room = next(iter(self.service.add_room(iid, "Other room").rooms))
        photo = next(iter(self.service.register_photo(iid, room, "other.jpg", "image/jpeg").photos))
        with self.assertRaises(NotFound):
            self.edit(fid, evidence_photo_ids=[photo])
        finding = self.service.get_inspection(self.iid).findings[fid]
        self.assertEqual(finding.state, FindingState.PENDING_REVIEW)
        self.assertIsNone(finding.review)

    def test_nested_snapshot_collections_after_approval_are_detached(self):
        fid = next(iter(self.analyze().findings))
        self.service.confirm_finding(self.iid, fid, reportable=True)
        snapshot = self.service.get_inspection(self.iid)
        finding = snapshot.findings[fid]
        evidence = list(finding.review.approved.evidence_photos)
        evidence.clear()
        snapshot.photos.pop(self.pid)
        snapshot.rooms.clear()
        snapshot.analyses.clear()
        snapshot.findings.clear()
        stored = self.service.get_inspection(self.iid)
        approved = stored.findings[fid]
        self.assertEqual(approved.state, FindingState.CONFIRMED)
        self.assertTrue(approved.eligible_for_report)
        self.assertEqual(approved.review.approved, finding.review.approved)
        self.assertEqual(approved.review.approved.evidence_photos[0].id, self.pid)
        self.assertIs(approved.review.approved.evidence_photos[0], stored.photos[self.pid])
        self.assertIs(approved.source_analysis, stored.analyses[approved.source_analysis_id])
        self.assertEqual(len(stored.rooms), 1)

    def test_failure_provenance_and_invalid_success_are_safe(self):
        from dataclasses import replace
        from backend.app.inference import AnalyzerContractError
        configured = AnalysisProvenance('test', '1', requested_model='requested')
        enriched = replace(configured, provider_model='reported')
        malformed = replace(configured)
        object.__setattr__(malformed, 'requested_model', '')
        for error_type, code in ((AnalyzerContractError, FailureCode.INVALID_RESPONSE),
                                 (AnalyzerFailure, FailureCode.UNAVAILABLE)):
            for provenance in (enriched, malformed, {'private': 'data'},
                               replace(configured, requested_model='contradiction')):
                with self.subTest(error=error_type, provenance=provenance):
                    self.setUp()
                    error = (error_type(provenance=provenance) if error_type is AnalyzerContractError
                             else error_type(code, provenance=provenance))
                    # Service must also handle a malformed value assigned after construction.
                    error.provenance = provenance
                    class Broken:
                        configured_provenance = configured
                        def analyze(self, photo):
                            raise error
                    self.service.analyzer = Broken()
                    state = self.analyze()
                    analysis = next(iter(state.analyses.values()))
                    self.assertEqual(analysis.result.failure_code, code)
                    self.assertEqual(analysis.result.provenance,
                                     enriched if provenance is enriched else configured)
                    self.assertFalse(state.findings)
        for bad in (None, malformed, replace(configured, analyzer_id='different')):
            self.setUp()
            execution = AnalyzerExecution(AnalysisOutput(AnalysisOutcome.NO_VISIBLE_FINDINGS), configured)
            object.__setattr__(execution, 'provenance', bad)
            class InvalidSuccess:
                configured_provenance = configured
                def analyze(self, photo):
                    return execution
            self.service.analyzer = InvalidSuccess()
            state = self.analyze()
            result = next(iter(state.analyses.values())).result
            self.assertEqual(result.failure_code, FailureCode.INVALID_RESPONSE)
            self.assertEqual(result.provenance, configured)
            self.assertFalse(state.findings)

    def test_captured_analyzer_and_provenance_snapshot(self):
        from dataclasses import FrozenInstanceError, replace
        configured = AnalysisProvenance('captured', '1', requested_model='requested')
        calls = []
        service = self.service
        class Swapping:
            @property
            def configured_provenance(self):
                service.analyzer = FakePhotoAnalyzer(FailureCode.UNAVAILABLE)
                return configured
            def analyze(self, photo):
                pending = next(iter(service.get_inspection(service_id).analyses.values()))
                self_outer.assertEqual(pending.attempt_provenance, configured)
                self_outer.assertIsNone(pending.result)
                calls.append(photo.id)
                return AnalyzerExecution(AnalysisOutput(AnalysisOutcome.NO_VISIBLE_FINDINGS),
                                         replace(configured, provider_model='reported'))
        self_outer, service_id = self, self.iid
        self.service.analyzer = Swapping()
        state = self.analyze()
        analysis = next(iter(state.analyses.values()))
        self.assertEqual(calls, [self.pid])
        self.assertEqual(analysis.result.provenance.provider_model, 'reported')
        with self.assertRaises(FrozenInstanceError):
            analysis.result.provenance.requested_model = 'mutated'
        object.__setattr__(analysis.result.provenance, 'provider_model', 'mutated snapshot')
        stored = self.service.get_inspection(self.iid).analyses[analysis.id]
        self.assertEqual(stored.result.provenance.provider_model, 'reported')

    def test_out_of_order_completions_keep_provenance_separate(self):
        from dataclasses import replace
        state = self.service.register_photo(self.iid, self.rid, 'second.png', 'image/png')
        second = next(pid for pid in state.photos if pid != self.pid)
        started, release = Event(), Event()
        first = self.pid
        class Concurrent:
            configured_provenance = AnalysisProvenance('concurrent', '1')
            def analyze(self, photo):
                if photo.id == first:
                    started.set()
                    if not release.wait(3):
                        raise RuntimeError('test timeout')
                return AnalyzerExecution(AnalysisOutput(AnalysisOutcome.NO_VISIBLE_FINDINGS),
                                         replace(self.configured_provenance, provider_model=str(photo.id)))
        self.service.analyzer = Concurrent()
        with ThreadPoolExecutor(max_workers=2) as pool:
            waiting = pool.submit(self.analyze)
            try:
                self.assertTrue(started.wait(3))
                completed = self.service.analyze_photo(self.iid, second)
                self.assertEqual(sum(a.status == AnalysisStatus.SUCCEEDED for a in completed.analyses.values()), 1)
            finally:
                release.set()
            waiting.result(3)
        for analysis in self.service.get_inspection(self.iid).analyses.values():
            self.assertEqual(analysis.result.provenance.provider_model, str(analysis.photo_id))
