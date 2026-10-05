"""Local API factory. The default analyzer is fake and offline."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api import router
from .domain import AnalysisOutcome, Category, Certainty, InvalidDomainData, Surface, TransitionConflict
from .inference import AnalysisOutput, FakePhotoAnalyzer, PhotoAnalyzer, ProposedFinding
from .repository import InMemoryInspectionRepository, NotFound
from .services import InspectionService


def create_app(*, analyzer: PhotoAnalyzer | None = None) -> FastAPI:
    app = FastAPI(title="RoomProof — inspection workflow", version="0.1.0",
                  description=("Local, non-durable workflow API. Photos are metadata only; "
                               "the default analyzer is fake. Analyzers may be injected."))
    if analyzer is None:
        analyzer = FakePhotoAnalyzer(AnalysisOutput(
            AnalysisOutcome.FINDINGS_PRESENT,
            (ProposedFinding(Category.SCRATCH, Surface.WALL, "center",
                             "Synthetic example scratch; no image was inspected", Certainty.CLEAR),),
            ("Fake analyzer: no image bytes were inspected.",),
        ))
    app.state.inspection_service = InspectionService(InMemoryInspectionRepository(), analyzer)

    async def not_found(request: Request, exc: NotFound):
        return JSONResponse(status_code=404, content={"error": {
            "code": "not_found", "message": "Resource not found in the requested inspection."}})

    async def conflict(request: Request, exc: TransitionConflict):
        return JSONResponse(status_code=409, content={"error": {
            "code": "transition_conflict", "message": "This operation conflicts with the current state."}})

    async def invalid(request: Request, exc: InvalidDomainData):
        return JSONResponse(status_code=422, content={"error": {
            "code": "invalid_domain_input", "message": "Input violates inspection or evidence rules."}})

    app.add_exception_handler(NotFound, not_found)
    app.add_exception_handler(TransitionConflict, conflict)
    app.add_exception_handler(InvalidDomainData, invalid)
    app.include_router(router)
    return app
