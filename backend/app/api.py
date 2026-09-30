"""Thin inspection-scoped HTTP routes; workflow rules stay in services."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from .domain import PropertyDetails
from .schemas import (ConfirmReview, CreateInspection, CreateRoom, EditReview,
                      ErrorResponse, HTTPValidationError, InspectionResponse, InspectionSummary,
                      RegisterPhoto, ReviewRequest, inspection_response, inspection_summary)
from .services import InspectionService

router = APIRouter(responses={
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
})
DOMAIN_VALIDATION_RESPONSES = {
    422: {
        "model": HTTPValidationError | ErrorResponse,
        "description": "Request-schema validation or RoomProof domain validation failed.",
    },
}


def get_service(request: Request) -> InspectionService:
    return request.app.state.inspection_service


Service = Annotated[InspectionService, Depends(get_service)]


@router.post("/inspections", response_model=InspectionResponse, status_code=201,
             responses=DOMAIN_VALIDATION_RESPONSES)
def create_inspection(body: CreateInspection, service: Service):
    return inspection_response(service.create_inspection(
        PropertyDetails(body.property_details.address, body.property_details.unit), body.renter_name))


@router.get("/inspections", response_model=list[InspectionSummary])
def list_inspections(service: Service):
    return [inspection_summary(i) for i in service.list_inspections()]


@router.get("/inspections/{inspection_id}", response_model=InspectionResponse)
def get_inspection(inspection_id: UUID, service: Service):
    return inspection_response(service.get_inspection(inspection_id))


@router.post("/inspections/{inspection_id}/rooms", response_model=InspectionResponse, status_code=201,
             responses=DOMAIN_VALIDATION_RESPONSES)
def add_room(inspection_id: UUID, body: CreateRoom, service: Service):
    return inspection_response(service.add_room(inspection_id, body.name))


@router.post("/inspections/{inspection_id}/rooms/{room_id}/photos",
             response_model=InspectionResponse, status_code=201,
             responses=DOMAIN_VALIDATION_RESPONSES)
def register_photo(inspection_id: UUID, room_id: UUID, body: RegisterPhoto, service: Service):
    return inspection_response(service.register_photo(
        inspection_id, room_id, body.original_filename,
        body.declared_media_type, body.capture_surface_hint))


@router.post("/inspections/{inspection_id}/photos/{photo_id}/analyses", response_model=InspectionResponse)
def analyze_photo(inspection_id: UUID, photo_id: UUID, service: Service):
    return inspection_response(service.analyze_photo(inspection_id, photo_id))


@router.post("/inspections/{inspection_id}/findings/{finding_id}/review",
             response_model=InspectionResponse, responses=DOMAIN_VALIDATION_RESPONSES)
def review_finding(inspection_id: UUID, finding_id: UUID, body: ReviewRequest, service: Service):
    if isinstance(body, ConfirmReview):
        state = service.confirm_finding(inspection_id, finding_id, reportable=body.reportable)
    elif isinstance(body, EditReview):
        state = service.edit_and_confirm_finding(
            inspection_id, finding_id, **body.model_dump(exclude={"action"}))
    else:
        state = service.reject_finding(inspection_id, finding_id, body.reason)
    return inspection_response(state)
