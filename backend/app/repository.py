"""Process-local inspection storage; callbacks are trusted application code."""
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, Protocol
from uuid import UUID

from .domain import Analysis, Finding, Inspection, InvalidDomainData, Photo, Room, TransitionConflict


class NotFound(Exception):
    """Resource is absent from the requested inspection (future HTTP 404)."""


def lookup(records: dict, resource_id: UUID):
    if not isinstance(resource_id, UUID):
        raise InvalidDomainData("resource ID must be a UUID")
    if resource_id not in records:
        raise NotFound("resource not found in requested inspection")
    return records[resource_id]


@dataclass
class InspectionState:
    inspection: Inspection
    rooms: dict[UUID, Room] = field(default_factory=dict)
    photos: dict[UUID, Photo] = field(default_factory=dict)
    analyses: dict[UUID, Analysis] = field(default_factory=dict)
    findings: dict[UUID, Finding] = field(default_factory=dict)

    def validate(self) -> None:
        """All parent/evidence references must be canonical aggregate members."""
        def member(records, value):
            if records.get(value.id) is not value:
                raise InvalidDomainData("reference is not a registered aggregate member")

        for records, expected in ((self.rooms, Room), (self.photos, Photo),
                                  (self.analyses, Analysis), (self.findings, Finding)):
            for key, value in records.items():
                if not isinstance(value, expected) or key != value.id:
                    raise InvalidDomainData("invalid aggregate member")
        for room in self.rooms.values():
            if room.inspection is not self.inspection:
                raise InvalidDomainData("room belongs to another inspection")
        for photo in self.photos.values():
            member(self.rooms, photo.room)
        for analysis in self.analyses.values():
            member(self.photos, analysis.photo)
        for finding in self.findings.values():
            member(self.analyses, finding.source_analysis)
            evidence = finding.original_proposal.evidence_photos
            if finding.review and finding.review.approved:
                evidence += finding.review.approved.evidence_photos
            for photo in evidence:
                member(self.photos, photo)
                if photo.room_id != finding.room_id:
                    raise InvalidDomainData("finding evidence belongs to another room")


class InspectionRepository(Protocol):
    def create(self, inspection: Inspection) -> InspectionState: ...
    def get(self, inspection_id: UUID) -> InspectionState: ...
    def update(self, inspection_id: UUID,
               operation: Callable[[InspectionState], None]) -> InspectionState: ...


class InMemoryInspectionRepository:
    def __init__(self):
        self._states: dict[UUID, InspectionState] = {}
        self._lock = Lock()

    def create(self, inspection: Inspection) -> InspectionState:
        if not isinstance(inspection, Inspection):
            raise InvalidDomainData("inspection required")
        with self._lock:
            if inspection.id in self._states:
                raise TransitionConflict("inspection already exists")
            state = InspectionState(deepcopy(inspection))
            self._states[inspection.id] = state
            return deepcopy(state)

    def get(self, inspection_id: UUID) -> InspectionState:
        with self._lock:
            return deepcopy(lookup(self._states, inspection_id))

    def update(self, inspection_id: UUID,
               operation: Callable[[InspectionState], None]) -> InspectionState:
        # Callback must be short, synchronous, and never call this repository.
        with self._lock:
            state = deepcopy(lookup(self._states, inspection_id))
            operation(state)
            if state.inspection.id != inspection_id:
                raise InvalidDomainData("inspection identity cannot change")
            state.validate()
            self._states[inspection_id] = deepcopy(state)
            return deepcopy(state)
