"""Transient image access/preparation; no domain, filesystem, or provider coupling."""
from dataclasses import dataclass, field
import hashlib
from io import BytesIO
from threading import Lock
from typing import Protocol
from uuid import UUID

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_OUTPUT_SIDE = 4096
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
SUPPORTED_FORMATS = ("JPEG", "PNG")
PREPARATION_VERSION = "rgb-png-v1"


class ImageError(ValueError):
    """Safe image-layer failure; messages never include input or decoder details."""


class ImageNotFound(ImageError):
    pass


class ImageAlreadyBound(ImageError):
    pass


class InvalidImage(ImageError):
    pass


class UnsupportedImage(ImageError):
    pass


class ImageTooLarge(ImageError):
    """Encoded input, decoded pixels, or prepared output exceeds policy."""


def _photo_id(photo_id: UUID) -> None:
    if not isinstance(photo_id, UUID):
        raise ImageError("photo_id must be a UUID")


def _raw_bytes(value: bytes | bytearray) -> bytes:
    if not isinstance(value, (bytes, bytearray)) or not value:
        raise InvalidImage("Nonempty image bytes required")
    if len(value) > MAX_INPUT_BYTES:
        raise ImageTooLarge("Encoded image exceeds input limit")
    return bytes(value)


class ImageSource(Protocol):
    def read(self, photo_id: UUID) -> bytes: ...


class InMemoryImageSource:
    """Instance-local development storage. Binding is write-once, not an upload API."""

    def __init__(self, max_total_bytes: int = 100 * 1024 * 1024):
        if type(max_total_bytes) is not int or max_total_bytes <= 0:
            raise ValueError("Storage bound must be a positive integer")
        self.max_total_bytes = max_total_bytes
        self._total_bytes = 0
        self._images: dict[UUID, bytes] = {}
        self._lock = Lock()

    def bind(self, photo_id: UUID, content: bytes | bytearray) -> None:
        _photo_id(photo_id)
        content = _raw_bytes(content)
        with self._lock:
            if photo_id in self._images:
                raise ImageAlreadyBound("Image already bound to photo")
            if self._total_bytes + len(content) > self.max_total_bytes:
                raise ImageTooLarge("Transient storage limit exceeded")
            self._images[photo_id] = content
            self._total_bytes += len(content)

    def read(self, photo_id: UUID) -> bytes:
        _photo_id(photo_id)
        with self._lock:
            if photo_id not in self._images:
                raise ImageNotFound("No image bound to photo")
            return self._images[photo_id]  # Immutable bytes can safely be shared.


@dataclass(frozen=True)
class PreparedImage:
    encoded_bytes: bytes = field(repr=False)
    media_type: str
    width: int
    height: int
    original_sha256: str
    prepared_sha256: str
    preparation_version: str

    def __post_init__(self):
        if not isinstance(self.encoded_bytes, bytes):
            raise InvalidImage("Prepared image requires immutable bytes")


class _OutputBuffer(BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_OUTPUT_BYTES:
            raise ImageTooLarge("Prepared image exceeds output limit")
        return super().write(data)


def _check_png_end(raw: bytes) -> None:
    # Pillow verify() stops at the IEND header without checking its CRC.
    # Walk chunk boundaries so an IEND-like sequence inside pixels cannot pass.
    offset = 8  # PNG signature; format has already been identified by Pillow.
    while offset + 12 <= len(raw):
        length = int.from_bytes(raw[offset:offset + 4], "big")
        end = offset + 12 + length
        if end > len(raw):
            break
        if raw[offset + 4:offset + 8] == b"IEND":
            if raw[offset:end] == b"\x00\x00\x00\x00IEND\xaeB`\x82":
                return
            break
        offset = end
    raise InvalidImage("Image could not be decoded")


def prepare_image(raw_bytes: bytes) -> PreparedImage:
    """Decode JPEG/PNG, orient, flatten transparency on white, and strip metadata.

    Reject oversized inputs before decoding; resize only above the longest-side
    bound. PNG avoids additional lossy compression. Hashes describe bytes, not
    model reproducibility. No Pillow global safety settings are changed.
    """
    raw = _raw_bytes(raw_bytes)
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format not in SUPPORTED_FORMATS:
                raise UnsupportedImage("Only JPEG and PNG images are supported")
            if image.width * image.height > MAX_PIXELS:
                raise ImageTooLarge("Decoded image exceeds pixel limit")
            if getattr(image, "n_frames", 1) != 1:
                raise UnsupportedImage("Only single-frame images are supported")
            image.verify()  # Check PNG integrity, including ancillary chunks.
            if image.format == "PNG":
                _check_png_end(raw)
        # verify invalidates the decoder; reopen and force pixel decoding too.
        with Image.open(BytesIO(raw)) as image:
            image.load()
            oriented = ImageOps.exif_transpose(image)
            try:
                rgba = oriented.convert("RGBA")
                try:
                    # Fresh canvas prevents EXIF, ICC, text, and other info copying.
                    with Image.new("RGB", rgba.size, "white") as clean:
                        with rgba.getchannel("A") as alpha:
                            clean.paste(rgba, mask=alpha)
                        clean.thumbnail((MAX_OUTPUT_SIDE, MAX_OUTPUT_SIDE), Image.Resampling.LANCZOS)
                        with _OutputBuffer() as buffer:
                            clean.save(buffer, format="PNG", compress_level=6)
                            encoded = buffer.getvalue()
                        width, height = clean.size
                finally:
                    rgba.close()
            finally:
                oriented.close()
    except ImageError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageTooLarge("Decoded image exceeds safety limit") from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError):
        raise InvalidImage("Image could not be decoded") from None
    return PreparedImage(
        encoded, "image/png", width, height,
        hashlib.sha256(raw).hexdigest(), hashlib.sha256(encoded).hexdigest(),
        PREPARATION_VERSION,
    )
