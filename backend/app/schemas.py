"""Explicit HTTP contracts and one-way domain-to-response mapping."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .domain import (AnalysisOutcome, AnalysisStatus, Category, Certainty,
                     FailureCode, FindingState, ReviewAction, Surface)
from .repository import InspectionState


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PropertyInput(RequestModel):
    address: str
    unit: str | None = None


class CreateInspection(RequestModel):
    property_details: PropertyInput
    renter_name: str


class CreateRoom(RequestModel):
    name: str


class RegisterPhoto(RequestModel):
    original_filename: str
    declared_media_type: str
    capture_surface_hint: Surface | None = None


class ConfirmReview(RequestModel):
    action: Literal["confirm"]
    reportable: StrictBool


class EditReview(RequestModel):
    action: Literal["edit_and_confirm"]
    category: Category
    surface: Surface
    location: str
    description: str
    reportable: StrictBool
    evidence_photo_ids: list[UUID] | None = None


class RejectReview(RequestModel):
    action: Literal["reject"]
    reason: str | None = None


ReviewRequest = Annotated[ConfirmReview | EditReview | RejectReview, Field(discriminator="action")]


class PropertyResponse(BaseModel):
    address: str
    unit: str | None


class InspectionSummary(BaseModel):
    id: UUID
    created_at: datetime
    property_details: PropertyResponse
    renter_name: str


class RoomResponse(BaseModel):
    id: UUID
    inspection_id: UUID
    created_at: datetime
    name: str


class PhotoResponse(BaseModel):
    id: UUID
    inspection_id: UUID
    room_id: UUID
    created_at: datetime
    original_filename: str
    declared_media_type: str
    capture_surface_hint: Surface | None


class AnalysisResponse(BaseModel):
    id: UUID
    inspection_id: UUID
    photo_id: UUID
    created_at: datetime
    analyzer_id: str
    analyzer_version: str
    status: AnalysisStatus
    outcome: AnalysisOutcome | None
    completed_at: datetime | None
    limitations: list[str]
    failure_code: FailureCode | None


class ContentResponse(BaseModel):
    category: Category
    surface: Surface
    location: str
    description: str
    evidence_photo_ids: list[UUID]


class ProposalResponse(ContentResponse):
    certainty: Certainty


class ApprovedResponse(ContentResponse):
    reportable: bool


class ReviewResponse(BaseModel):
    action: ReviewAction
    reviewed_at: datetime
    approved: ApprovedResponse | None
    reason: str | None


class FindingResponse(BaseModel):
    id: UUID
    inspection_id: UUID
    room_id: UUID
    created_at: datetime
    source_analysis_id: UUID
    state: FindingState
    original_proposal: ProposalResponse
    review: ReviewResponse | None
    eligible_for_report: bool


class InspectionResponse(InspectionSummary):
    rooms: list[RoomResponse]
    photos: list[PhotoResponse]
    analyses: list[AnalysisResponse]
    findings: list[FindingResponse]


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class ValidationError(BaseModel):
    """Documentation model for FastAPI's standard validation-error fields."""
    loc: list[str | int]
    msg: str
    type: str


class HTTPValidationError(BaseModel):
    # Documentation only; FastAPI's request-validation handler is unchanged.
    detail: list[ValidationError]


def inspection_summary(inspection) -> InspectionSummary:
    return InspectionSummary(
        id=inspection.id, created_at=inspection.created_at,
        property_details=PropertyResponse(address=inspection.property_details.address,
                                          unit=inspection.property_details.unit),
        renter_name=inspection.renter_name,
    )


def _content(content) -> dict:
    return dict(category=content.category, surface=content.surface,
                location=content.location, description=content.description,
                evidence_photo_ids=[photo.id for photo in content.evidence_photos])


def inspection_response(state: InspectionState) -> InspectionResponse:
    """Select fields explicitly; never serialize the parent-reference graph."""
    analyses = []
    for analysis in state.analyses.values():
        result = analysis.result
        analyses.append(AnalysisResponse(
            id=analysis.id, inspection_id=analysis.inspection_id,
            photo_id=analysis.photo_id, created_at=analysis.created_at,
            analyzer_id=analysis.analyzer_id, analyzer_version=analysis.analyzer_version,
            status=analysis.status, outcome=result.outcome if result else None,
            completed_at=result.completed_at if result else None,
            limitations=list(result.limitations) if result else [],
            failure_code=result.failure_code if result else None,
        ))
    findings = []
    for finding in state.findings.values():
        review = finding.review
        approved = review.approved if review else None
        findings.append(FindingResponse(
            id=finding.id, inspection_id=finding.inspection_id, room_id=finding.room_id,
            created_at=finding.created_at, source_analysis_id=finding.source_analysis_id,
            state=finding.state,
            original_proposal=ProposalResponse(**_content(finding.original_proposal),
                                              certainty=finding.original_proposal.certainty),
            review=ReviewResponse(
                action=review.action, reviewed_at=review.reviewed_at, reason=review.reason,
                approved=ApprovedResponse(**_content(approved), reportable=approved.reportable)
                if approved else None,
            ) if review else None,
            eligible_for_report=finding.eligible_for_report,
        ))
    return InspectionResponse(
        **inspection_summary(state.inspection).model_dump(),
        rooms=[RoomResponse(id=r.id, inspection_id=r.inspection_id,
                            created_at=r.created_at, name=r.name) for r in state.rooms.values()],
        photos=[PhotoResponse(
            id=p.id, inspection_id=p.inspection_id, room_id=p.room_id, created_at=p.created_at,
            original_filename=p.original_filename, declared_media_type=p.declared_media_type,
            capture_surface_hint=p.capture_surface_hint,
        ) for p in state.photos.values()],
        analyses=analyses, findings=findings,
    )
