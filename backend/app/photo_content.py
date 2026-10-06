"""Transient, inspection-scoped photo bytes. No filesystem or provider access."""
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from .images import (MAX_INPUT_BYTES, ImageAlreadyBound, ImageError,
                     ImageNotFound, ImageTooLarge, prepare_image)
from .repository import lookup

router = APIRouter()


def check_photo(request: Request, inspection_id: UUID, photo_id: UUID):
    state = request.app.state.inspection_service.get_inspection(inspection_id)
    lookup(state.photos, photo_id)


def safe_error(status: int, code: str):
    return HTTPException(status, detail={"code": code, "message": {
        "image_too_large": "Image or transient storage limit exceeded.",
        "invalid_image": "Choose a valid, single-frame JPEG or PNG image.",
        "content_exists": "Photo content is already bound and cannot be replaced.",
        "content_missing": "Photo content has not been uploaded.",
    }[code]})


@router.put('/inspections/{inspection_id}/photos/{photo_id}/content', status_code=204)
async def upload_content(inspection_id: UUID, photo_id: UUID, request: Request):
    check_photo(request, inspection_id, photo_id)
    source = request.app.state.image_source
    try:
        source.read(photo_id)
    except ImageNotFound:
        pass
    else:
        raise safe_error(409, 'content_exists')
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_INPUT_BYTES:
            raise safe_error(413, 'image_too_large')
        raw.extend(chunk)
    source = request.app.state.image_source
    try:
        # Validate before binding: a rejected upload leaves the UUID available.
        await run_in_threadpool(prepare_image, bytes(raw))
        source.bind(photo_id, bytes(raw))
    except ImageAlreadyBound:
        raise safe_error(409, 'content_exists') from None
    except ImageTooLarge:
        raise safe_error(413, 'image_too_large') from None
    except ImageError:
        raise safe_error(422, 'invalid_image') from None
    return Response(status_code=204, headers={'Cache-Control': 'no-store'})


@router.get('/inspections/{inspection_id}/photos/{photo_id}/content')
def read_content(inspection_id: UUID, photo_id: UUID, request: Request):
    check_photo(request, inspection_id, photo_id)
    try:
        prepared = prepare_image(request.app.state.image_source.read(photo_id))
    except ImageNotFound:
        raise safe_error(404, 'content_missing') from None
    except ImageError:
        raise safe_error(422, 'invalid_image') from None
    return Response(prepared.encoded_bytes, media_type='image/png',
                    headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
