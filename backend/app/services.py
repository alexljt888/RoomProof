"""Inspection workflows. No HTTP, storage, authentication, or real inference."""
from uuid import UUID

from .domain import (Analysis, AnalysisStatus, ApprovedContent, Category, Finding,
                     FindingProposal, FindingState, FailureCode, Inspection,
                     InvalidDomainData, Photo, PropertyDetails, Room, Surface,
                     TransitionConflict)
from .inference import AnalysisOutput, AnalyzerContractError, AnalyzerFailure, PhotoAnalyzer
from .repository import InspectionRepository, InspectionState, lookup


class InspectionService:
    def __init__(self, repository: InspectionRepository, analyzer: PhotoAnalyzer):
        self.repository = repository
        self.analyzer = analyzer

    def create_inspection(self, property_details: PropertyDetails,
                          renter_name: str) -> InspectionState:
        return self.repository.create(Inspection(property_details, renter_name))

    def get_inspection(self, inspection_id: UUID) -> InspectionState:
        return self.repository.get(inspection_id)

    def list_inspections(self) -> list[Inspection]:
        return self.repository.list_inspections()

    def add_room(self, inspection_id: UUID, name: str) -> InspectionState:
        def add(state):
            room = Room(state.inspection, name)
            state.rooms[room.id] = room
        return self.repository.update(inspection_id, add)

    def register_photo(self, inspection_id: UUID, room_id: UUID,
                       original_filename: str, declared_media_type: str,
                       capture_surface_hint: Surface | None = None) -> InspectionState:
        def register(state):
            room = lookup(state.rooms, room_id)
            photo = Photo(room, original_filename, declared_media_type, capture_surface_hint)
            state.photos[photo.id] = photo
        return self.repository.update(inspection_id, register)

    def analyze_photo(self, inspection_id: UUID, photo_id: UUID) -> InspectionState:
        analysis_id = None

        def reserve(state):
            nonlocal analysis_id
            photo = lookup(state.photos, photo_id)
            if any(a.photo_id == photo_id and a.status != AnalysisStatus.FAILED
                   for a in state.analyses.values()):
                raise TransitionConflict("photo analysis is pending or already succeeded")
            analysis = Analysis(photo, self.analyzer.analyzer_id, self.analyzer.analyzer_version)
            analysis_id = analysis.id
            state.analyses[analysis.id] = analysis

        reserved = self.repository.update(inspection_id, reserve)
        # No repository lock is held during analyzer execution. Input is a copy.
        try:
            output = self.analyzer.analyze(reserved.photos[photo_id])
        except AnalyzerContractError:
            return self._fail_analysis(inspection_id, analysis_id, FailureCode.INVALID_RESPONSE)
        except AnalyzerFailure as exc:
            return self._fail_analysis(inspection_id, analysis_id, exc.code)
        except Exception:
            # Never store provider exception messages, credentials, or tracebacks.
            return self._fail_analysis(inspection_id, analysis_id, FailureCode.UNAVAILABLE)

        def complete(state):
            analysis = lookup(state.analyses, analysis_id)
            if type(output) is not AnalysisOutput:
                raise InvalidDomainData("analyzer must return AnalysisOutput")
            # Revalidate the boundary, then build everything on a private copy.
            validated = AnalysisOutput(output.outcome, output.findings, output.limitations)
            analysis.complete(validated.outcome, validated.limitations)
            findings = []
            for proposed in validated.findings:
                proposal = FindingProposal(
                    proposed.category, proposed.surface, proposed.location,
                    proposed.description, proposed.certainty, (analysis.photo,),
                )
                findings.append(Finding(analysis, proposal))
            for finding in findings:
                state.findings[finding.id] = finding

        try:
            return self.repository.update(inspection_id, complete)
        except InvalidDomainData:
            return self._fail_analysis(inspection_id, analysis_id, FailureCode.INVALID_RESPONSE)

    def _fail_analysis(self, inspection_id, analysis_id, code) -> InspectionState:
        def fail(state):
            lookup(state.analyses, analysis_id).fail(code)
        return self.repository.update(inspection_id, fail)

    def confirm_finding(self, inspection_id: UUID, finding_id: UUID,
                        *, reportable: bool) -> InspectionState:
        def confirm(state):
            lookup(state.findings, finding_id).confirm(reportable=reportable)
        return self.repository.update(inspection_id, confirm)

    def reject_finding(self, inspection_id: UUID, finding_id: UUID,
                       reason: str | None = None) -> InspectionState:
        def reject(state):
            lookup(state.findings, finding_id).reject(reason)
        return self.repository.update(inspection_id, reject)

    def edit_and_confirm_finding(
        self, inspection_id: UUID, finding_id: UUID, *, category: Category,
        surface: Surface, location: str, description: str, reportable: bool,
        evidence_photo_ids: tuple[UUID, ...] | None = None,
    ) -> InspectionState:
        def review(state):
            finding = lookup(state.findings, finding_id)
            if finding.state != FindingState.PENDING_REVIEW:
                raise TransitionConflict("finding already reviewed")
            # Omission explicitly means retain original evidence. Resolve IDs only
            # against this inspection; never accept caller-owned Photo objects.
            if evidence_photo_ids is None:
                photos = finding.original_proposal.evidence_photos
            else:
                if not isinstance(evidence_photo_ids, (list, tuple)):
                    raise InvalidDomainData("evidence IDs must be a list or tuple")
                photos = tuple(lookup(state.photos, pid) for pid in evidence_photo_ids)
            approved = ApprovedContent(category, surface, location, description, reportable, photos)
            finding.edit_and_confirm(approved)
        return self.repository.update(inspection_id, review)
