"""Read-only, human-approved inspection report projection."""
from uuid import UUID
from pydantic import BaseModel, computed_field
from .images import ImageSource, ImageError, prepare_image
from .domain import FindingState, AnalysisStatus
from .repository import InspectionState


class ReportFinding(BaseModel):
    id: UUID
    category: str
    surface: str
    location: str
    description: str
    evidence_photo_ids: list[UUID]


class RoomReport(BaseModel):
    id: UUID
    name: str
    findings: list[ReportFinding]


class InspectionReport(BaseModel):
    inspection_id: UUID
    address: str
    unit: str | None
    renter: str
    room_count: int
    finding_count: int
    pending_findings: int
    pending_analyses: int
    unanalysed_photos: int
    failed_analyses: int
    photos_needing_analysis: int
    unavailable_evidence: int
    review_complete: bool
    rooms: list[RoomReport]

    @computed_field
    @property
    def export_ready(self) -> bool:
        return not (self.photos_needing_analysis or self.pending_findings
                    or self.pending_analyses or self.unavailable_evidence)


def project_report(state: InspectionState, source: ImageSource) -> InspectionReport:
    # Revalidate evidence membership before projecting even a trusted snapshot.
    state.validate()
    rooms = []
    for room in state.rooms.values():
        findings = []
        for finding in state.findings.values():
            if finding.room_id != room.id or not finding.eligible_for_report:
                continue
            approved = finding.review.approved
            findings.append(ReportFinding(
                id=finding.id, category=approved.category.value, surface=approved.surface.value,
                location=approved.location, description=approved.description,
                evidence_photo_ids=[p.id for p in approved.evidence_photos]))
        rooms.append(RoomReport(id=room.id, name=room.name, findings=findings))
    pending = sum(f.state == FindingState.PENDING_REVIEW for f in state.findings.values())
    running = sum(a.status == AnalysisStatus.PENDING for a in state.analyses.values())
    analysed = {a.photo_id for a in state.analyses.values()}
    successful = {a.photo_id for a in state.analyses.values() if a.status == AnalysisStatus.SUCCEEDED}
    unavailable = 0
    for pid in {pid for room in rooms for finding in room.findings for pid in finding.evidence_photo_ids}:
        try:
            prepare_image(source.read(pid))
        except ImageError:
            unavailable += 1
    return InspectionReport(
        inspection_id=state.inspection.id, address=state.inspection.property_details.address,
        unit=state.inspection.property_details.unit, renter=state.inspection.renter_name,
        room_count=len(rooms), finding_count=sum(len(r.findings) for r in rooms),
        pending_findings=pending, pending_analyses=running,
        unanalysed_photos=sum(p not in analysed for p in state.photos),
        failed_analyses=sum(a.status == AnalysisStatus.FAILED for a in state.analyses.values()),
        photos_needing_analysis=sum(p not in successful for p in state.photos),
        unavailable_evidence=unavailable,
        review_complete=not (pending or running), rooms=rooms)
