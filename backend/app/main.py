"""Local API factory. The default analyzer is fake and offline."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api import router
from .report_api import router as report_router
from .photo_content import router as content_router
from .images import InMemoryImageSource
from .domain import InvalidDomainData, TransitionConflict
from .inference import PhotoAnalyzer
from .runtime import compose_analyzer
from .repository import InMemoryInspectionRepository, NotFound
from .services import InspectionService


def create_app(*, analyzer: PhotoAnalyzer | None = None,
               image_source: InMemoryImageSource | None = None) -> FastAPI:
    analyzer_source = getattr(analyzer, "image_source", None)
    if image_source is not None and analyzer_source is not None and image_source is not analyzer_source:
        raise ValueError("Upload and analyzer must share the same image source")
    image_source = image_source if image_source is not None else analyzer_source
    if image_source is None:
        image_source = InMemoryImageSource()

    owned_client = None
    if analyzer is None:
        analyzer, owned_client = compose_analyzer(image_source)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            if owned_client is not None:
                owned_client.close()

    app = FastAPI(title="RoomProof — inspection workflow", version="0.1.0",
                  lifespan=lifespan,
                  description=("Local, non-durable workflow API with transient photo content. "
                               "The default analyzer is fake; real analysis requires explicit configuration."))
    app.state.image_source = image_source
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
    app.include_router(content_router)
    app.include_router(report_router)
    return app
