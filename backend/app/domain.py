"""Independent domain objects. AI proposes; only an explicit human action approves."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4


class InvalidDomainData(ValueError):
    """Invalid content or ownership; suitable for a future 422 response."""


class TransitionConflict(Exception):
    """An already completed operation; suitable for a future 409 response."""


class Surface(StrEnum):
    WALL = "wall"
    FLOOR = "floor"
    DOOR = "door"
    TRIM = "trim"
    COUNTERTOP = "countertop"


class Category(StrEnum):
    SCRATCH = "scratch"
    SCUFF = "scuff"
    STAIN = "stain"
    CRACK = "crack"
    HOLE = "hole"
    CHIPPED_PAINT = "chipped_paint"
    DIRT = "dirt"
    CHIP = "chip"


class Certainty(StrEnum):
    CLEAR = "clear"
    POSSIBLE = "possible"


class FindingState(StrEnum):
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ReviewAction(StrEnum):
    CONFIRM = "confirm"
    EDIT_AND_CONFIRM = "edit_and_confirm"
    REJECT = "reject"


class AnalysisOutcome(StrEnum):
    FINDINGS_PRESENT = "findings_present"
    NO_VISIBLE_FINDINGS = "no_visible_findings"
    UNCERTAIN = "uncertain"


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class FailureCode(StrEnum):
    """Safe codes only: never persist raw provider exceptions or credentials."""

    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"
    UNREADABLE_IMAGE = "unreadable_image"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidDomainData(f"{name} must be nonempty text")


def _type(value, expected, name: str) -> None:
    if not isinstance(value, expected):
        raise InvalidDomainData(f"{name} must be {expected.__name__}")


def _collection(value, name: str) -> tuple:
    if not isinstance(value, (list, tuple)):
        raise InvalidDomainData(f"{name} must be a list or tuple")
    return tuple(value)


def _evidence(value) -> tuple["Photo", ...]:
    photos = _collection(value, "evidence_photos")
    if not photos:
        raise InvalidDomainData("evidence must contain photos")
    for photo in photos:
        _type(photo, Photo, "evidence photo")
    if len({photo.id for photo in photos}) != len(photos):
        raise InvalidDomainData("duplicate evidence photo")
    first = photos[0]
    for photo in photos:
        if photo.room_id != first.room_id or photo.inspection_id != first.inspection_id:
            raise InvalidDomainData("evidence must belong to one room and inspection")
    return photos


def _content(value) -> None:
    _type(value.category, Category, "category")
    _type(value.surface, Surface, "surface")
    _text(value.location, "location")
    _text(value.description, "description")


@dataclass(frozen=True)
class PropertyDetails:
    address: str
    unit: str | None = None

    def __post_init__(self):
        _text(self.address, "address")
        if self.unit is not None:
            _text(self.unit, "unit")


@dataclass(frozen=True)
class Inspection:
    property_details: PropertyDetails
    renter_name: str
    id: UUID = field(default_factory=uuid4, init=False)
    created_at: datetime = field(default_factory=_now, init=False)

    def __post_init__(self):
        _type(self.property_details, PropertyDetails, "property_details")
        _text(self.renter_name, "renter_name")


@dataclass(frozen=True)
class Room:
    inspection: Inspection
    name: str
    id: UUID = field(default_factory=uuid4, init=False)
    created_at: datetime = field(default_factory=_now, init=False)

    def __post_init__(self):
        _type(self.inspection, Inspection, "inspection")
        _text(self.name, "name")

    @property
    def inspection_id(self) -> UUID:
        return self.inspection.id


@dataclass(frozen=True)
class Photo:
    """Registered metadata, not a verified uploaded image or storage locator."""

    room: Room
    original_filename: str
    declared_media_type: str
    capture_surface_hint: Surface | None = None
    id: UUID = field(default_factory=uuid4, init=False)
    created_at: datetime = field(default_factory=_now, init=False)

    def __post_init__(self):
        _type(self.room, Room, "room")
        _text(self.original_filename, "original_filename")
        if any(c in self.original_filename for c in ("/", "\\", ":", "\0")) or self.original_filename in (".", ".."):
            raise InvalidDomainData("original_filename must be a basename, not a path or URL")
        if self.declared_media_type not in ("image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"):
            raise InvalidDomainData("unsupported declared image media type")
        if self.capture_surface_hint is not None:
            _type(self.capture_surface_hint, Surface, "capture_surface_hint")

    @property
    def room_id(self) -> UUID:
        return self.room.id

    @property
    def inspection_id(self) -> UUID:
        return self.room.inspection_id


@dataclass(frozen=True)
class AnalysisResult:
    status: AnalysisStatus
    outcome: AnalysisOutcome | None = None
    limitations: tuple[str, ...] = ()
    failure_code: FailureCode | None = None
    completed_at: datetime = field(default_factory=_now, init=False)

    def __post_init__(self):
        _type(self.status, AnalysisStatus, "status")
        object.__setattr__(self, "limitations", _collection(self.limitations, "limitations"))
        for limitation in self.limitations:
            _text(limitation, "limitation")
        if self.status == AnalysisStatus.SUCCEEDED:
            _type(self.outcome, AnalysisOutcome, "outcome")
            if self.failure_code is not None:
                raise InvalidDomainData("successful analysis cannot have a failure code")
        elif self.status == AnalysisStatus.FAILED:
            _type(self.failure_code, FailureCode, "failure_code")
            if self.outcome is not None:
                raise InvalidDomainData("failed analysis cannot have an outcome")
        else:
            raise InvalidDomainData("result must be terminal")


@dataclass(frozen=True)
class Analysis:
    photo: Photo
    analyzer_id: str
    analyzer_version: str
    id: UUID = field(default_factory=uuid4, init=False)
    created_at: datetime = field(default_factory=_now, init=False)
    _result: AnalysisResult | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        _type(self.photo, Photo, "photo")
        _text(self.analyzer_id, "analyzer_id")
        _text(self.analyzer_version, "analyzer_version")

    @property
    def photo_id(self) -> UUID:
        return self.photo.id

    @property
    def inspection_id(self) -> UUID:
        return self.photo.inspection_id

    @property
    def result(self) -> AnalysisResult | None:
        return self._result

    @property
    def status(self) -> AnalysisStatus:
        return self._result.status if self._result else AnalysisStatus.PENDING

    def _finish(self, result: AnalysisResult) -> None:
        if self._result is not None:
            raise TransitionConflict("analysis already completed")
        object.__setattr__(self, "_result", result)

    def complete(self, outcome: AnalysisOutcome, limitations: tuple[str, ...] = ()) -> None:
        self._finish(AnalysisResult(AnalysisStatus.SUCCEEDED, outcome, limitations))

    def fail(self, code: FailureCode) -> None:
        self._finish(AnalysisResult(AnalysisStatus.FAILED, failure_code=code))


@dataclass(frozen=True)
class FindingProposal:
    category: Category
    surface: Surface
    location: str
    description: str
    certainty: Certainty
    evidence_photos: tuple[Photo, ...]

    def __post_init__(self):
        _content(self)
        _type(self.certainty, Certainty, "certainty")
        object.__setattr__(self, "evidence_photos", _evidence(self.evidence_photos))


@dataclass(frozen=True)
class ApprovedContent:
    category: Category
    surface: Surface
    location: str
    description: str
    reportable: bool
    evidence_photos: tuple[Photo, ...]

    def __post_init__(self):
        _content(self)
        if type(self.reportable) is not bool:
            raise InvalidDomainData("reportable must be a boolean")
        object.__setattr__(self, "evidence_photos", _evidence(self.evidence_photos))


@dataclass(frozen=True)
class FindingReview:
    action: ReviewAction
    approved: ApprovedContent | None = None
    reason: str | None = None
    reviewed_at: datetime = field(default_factory=_now, init=False)

    def __post_init__(self):
        _type(self.action, ReviewAction, "action")
        if self.action == ReviewAction.REJECT:
            if self.approved is not None:
                raise InvalidDomainData("rejected review cannot approve content")
            if self.reason is not None:
                _text(self.reason, "reason")
        else:
            _type(self.approved, ApprovedContent, "approved")
            if self.reason is not None:
                raise InvalidDomainData("rejection reason requires rejection")


@dataclass(frozen=True)
class Finding:
    source_analysis: Analysis
    original_proposal: FindingProposal
    id: UUID = field(default_factory=uuid4, init=False)
    created_at: datetime = field(default_factory=_now, init=False)
    _review: FindingReview | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        _type(self.source_analysis, Analysis, "source_analysis")
        _type(self.original_proposal, FindingProposal, "original_proposal")
        result = self.source_analysis.result
        if result is None or result.status != AnalysisStatus.SUCCEEDED or result.outcome == AnalysisOutcome.NO_VISIBLE_FINDINGS:
            raise InvalidDomainData("finding requires a successful analysis that permits findings")
        photos = self.original_proposal.evidence_photos
        self._validate_evidence_ownership(photos)
        if self.source_analysis.photo_id not in {photo.id for photo in photos}:
            raise InvalidDomainData("original evidence must include the analyzed photo")

    def _validate_evidence_ownership(self, photos: tuple[Photo, ...]) -> None:
        for photo in photos:
            if photo.room_id != self.room_id or photo.inspection_id != self.inspection_id:
                raise InvalidDomainData("evidence must belong to the source room and inspection")

    @property
    def inspection_id(self) -> UUID:
        return self.source_analysis.inspection_id

    @property
    def room_id(self) -> UUID:
        return self.source_analysis.photo.room_id

    @property
    def source_analysis_id(self) -> UUID:
        return self.source_analysis.id

    @property
    def review(self) -> FindingReview | None:
        return self._review

    @property
    def state(self) -> FindingState:
        if self._review is None:
            return FindingState.PENDING_REVIEW
        return FindingState.REJECTED if self._review.action == ReviewAction.REJECT else FindingState.CONFIRMED

    @property
    def eligible_for_report(self) -> bool:
        return self.state == FindingState.CONFIRMED and self._review.approved.reportable

    def _require_pending_review(self) -> None:
        if self._review is not None:
            raise TransitionConflict("finding already reviewed")

    def _review_once(self, review: FindingReview) -> None:
        self._require_pending_review()
        object.__setattr__(self, "_review", review)

    def confirm(self, *, reportable: bool) -> None:
        self._require_pending_review()
        proposal = self.original_proposal
        approved = ApprovedContent(
            proposal.category, proposal.surface, proposal.location,
            proposal.description, reportable, proposal.evidence_photos,
        )
        self._review_once(FindingReview(ReviewAction.CONFIRM, approved))

    def edit_and_confirm(self, approved: ApprovedContent) -> None:
        self._require_pending_review()
        _type(approved, ApprovedContent, "approved")
        self._validate_evidence_ownership(approved.evidence_photos)
        self._review_once(FindingReview(ReviewAction.EDIT_AND_CONFIRM, approved))

    def reject(self, reason: str | None = None) -> None:
        self._require_pending_review()
        self._review_once(FindingReview(ReviewAction.REJECT, reason=reason))
