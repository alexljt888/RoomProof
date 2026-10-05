"""Synthetic in-memory image tests: no files, network, or provider client."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
import hashlib
from io import BytesIO
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

from PIL import Image, PngImagePlugin

from backend.app import images
from backend.app.images import (ImageAlreadyBound, ImageError, ImageNotFound,
                                ImageTooLarge, InMemoryImageSource, InvalidImage,
                                UnsupportedImage, prepare_image)


def encoded(fmt="PNG", mode="RGB", size=(12, 8), color=None, **save_options):
    with Image.new(mode, size, color) as image, BytesIO() as buffer:
        image.save(buffer, format=fmt, **save_options)
        return buffer.getvalue()


class ImageSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = InMemoryImageSource()
        self.photo_id = uuid4()

    def test_bind_and_read(self):
        raw = encoded()
        self.source.bind(self.photo_id, raw)
        self.assertEqual(self.source.read(self.photo_id), raw)
        self.assertIsInstance(self.source.read(self.photo_id), bytes)

    def test_missing_binding(self):
        with self.assertRaises(ImageNotFound):
            self.source.read(self.photo_id)

    def test_duplicate_cannot_replace(self):
        self.source.bind(self.photo_id, b"original")
        with self.assertRaises(ImageAlreadyBound):
            self.source.bind(self.photo_id, b"replacement")
        self.assertEqual(self.source.read(self.photo_id), b"original")

    def test_bytearray_is_copied(self):
        raw = bytearray(b"original")
        self.source.bind(self.photo_id, raw)
        raw[:] = b"changed"
        self.assertEqual(self.source.read(self.photo_id), b"original")

    def test_instances_are_isolated(self):
        self.source.bind(self.photo_id, b"image")
        with self.assertRaises(ImageNotFound):
            InMemoryImageSource().read(self.photo_id)

    def test_invalid_ids_and_content(self):
        for invalid in ("photo.jpg", str(self.photo_id), None):
            with self.assertRaises(ImageError):
                self.source.bind(invalid, b"image")
            with self.assertRaises(ImageError):
                self.source.read(invalid)
        for invalid in (None, "bytes", b"", 123):
            with self.assertRaises(InvalidImage):
                self.source.bind(self.photo_id, invalid)
        with patch.object(images, "MAX_INPUT_BYTES", 2):
            with self.assertRaises(ImageTooLarge):
                self.source.bind(self.photo_id, b"large")

    def test_competing_bindings_have_one_winner(self):
        barrier = Barrier(2)
        def bind(raw):
            barrier.wait(timeout=3)
            try:
                self.source.bind(self.photo_id, raw)
                return raw
            except ImageAlreadyBound:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(bind, (b"first", b"second")))
        winners = [r for r in results if r is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(self.source.read(self.photo_id), winners[0])


class PreparationTests(unittest.TestCase):
    def test_jpeg_and_png_decode_to_rgb_png(self):
        for fmt in ("JPEG", "PNG"):
            with self.subTest(fmt=fmt):
                result = prepare_image(encoded(fmt=fmt))
                self.assertEqual((result.width, result.height), (12, 8))
                self.assertEqual(result.media_type, "image/png")
                with Image.open(BytesIO(result.encoded_bytes)) as image:
                    image.load()
                    self.assertEqual((image.format, image.mode), ("PNG", "RGB"))

    def test_actual_content_controls_format(self):
        # No declaration/extension/path is an input to this boundary.
        self.assertEqual(prepare_image(encoded("PNG")).media_type, "image/png")
        with self.assertRaises(UnsupportedImage):
            prepare_image(encoded("GIF"))
        with self.assertRaises(UnsupportedImage):
            prepare_image(encoded("BMP"))

    def test_empty_random_and_wrong_type(self):
        for raw in (b"", b"not an image", None, "image.jpeg", 42):
            with self.subTest(raw=raw), self.assertRaises(InvalidImage):
                prepare_image(raw)

    def test_encoded_limit_precedes_open(self):
        with patch.object(images, "MAX_INPUT_BYTES", 4), patch.object(images.Image, "open") as opened:
            with self.assertRaises(ImageTooLarge):
                prepare_image(b"12345")
            opened.assert_not_called()

    def test_pixel_limit_precedes_decode(self):
        raw = encoded(size=(20, 10))
        with patch.object(images, "MAX_PIXELS", 199), patch.object(PngImagePlugin.PngImageFile, "load") as load:
            with self.assertRaises(ImageTooLarge):
                prepare_image(raw)
            load.assert_not_called()

    def test_pixel_limit_inclusive(self):
        with patch.object(images, "MAX_PIXELS", 96):
            self.assertEqual(prepare_image(encoded()).width, 12)

    def test_pillow_bomb_error_is_safe(self):
        raw = encoded()
        # Lower Pillow's threshold only inside this synthetic test.
        with patch.object(Image, "MAX_IMAGE_PIXELS", 1):
            with self.assertRaises(ImageTooLarge):
                prepare_image(raw)

    def test_exif_orientation_changes_dimensions_and_pixels(self):
        exif = Image.Exif()
        exif[274] = 6
        with Image.new("RGB", (3, 2), "black") as image, BytesIO() as buffer:
            image.putpixel((0, 0), (255, 0, 0))
            image.save(buffer, format="PNG", exif=exif)
            result = prepare_image(buffer.getvalue())
        self.assertEqual((result.width, result.height), (2, 3))
        with Image.open(BytesIO(result.encoded_bytes)) as image:
            self.assertEqual(image.getpixel((1, 0)), (255, 0, 0))
            self.assertFalse(image.getexif())

    def test_metadata_removed(self):
        exif = Image.Exif()
        exif[271] = "Synthetic private device"
        exif[306] = "2000:01:01 00:00:00"
        text = PngImagePlugin.PngInfo()
        text.add_text("Comment", "Synthetic private note")
        for fmt in ("JPEG", "PNG"):
            options = dict(exif=exif, icc_profile=b"synthetic profile")
            if fmt == "PNG":
                options["pnginfo"] = text
            result = prepare_image(encoded(fmt, **options))
            with Image.open(BytesIO(result.encoded_bytes)) as image:
                image.load()
                self.assertEqual(image.info, {})
                self.assertFalse(image.getexif())
            self.assertNotIn(b"Synthetic private", result.encoded_bytes)

    def test_grayscale(self):
        result = prepare_image(encoded(mode="L", color=128))
        with Image.open(BytesIO(result.encoded_bytes)) as image:
            self.assertEqual(image.getpixel((0, 0)), (128, 128, 128))

    def test_rgba_composited_on_white(self):
        for color, expected in (((0, 0, 0, 0), (255, 255, 255)),
                                ((0, 0, 0, 128), (127, 127, 127))):
            result = prepare_image(encoded(mode="RGBA", color=color))
            with Image.open(BytesIO(result.encoded_bytes)) as image:
                self.assertEqual(image.getpixel((0, 0)), expected)

    def test_palette_transparency(self):
        result = prepare_image(encoded(mode="P", transparency=0))
        with Image.open(BytesIO(result.encoded_bytes)) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))

    def test_resize_preserves_aspect_ratio_and_never_upscales(self):
        with patch.object(images, "MAX_OUTPUT_SIDE", 10):
            result = prepare_image(encoded(size=(40, 20)))
            self.assertEqual((result.width, result.height), (10, 5))
            small = prepare_image(encoded(size=(4, 2)))
            self.assertEqual((small.width, small.height), (4, 2))

    def test_output_byte_limit(self):
        with patch.object(images, "MAX_OUTPUT_BYTES", 10):
            with self.assertRaises(ImageTooLarge):
                prepare_image(encoded())

    def test_hashes_and_encoding_repeat(self):
        raw = encoded()
        first, second = prepare_image(raw), prepare_image(raw)
        self.assertEqual(first, second)
        self.assertEqual(first.original_sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(first.prepared_sha256, hashlib.sha256(first.encoded_bytes).hexdigest())
        self.assertEqual(first.preparation_version, images.PREPARATION_VERSION)

    def test_value_frozen_and_bytes_hidden(self):
        result = prepare_image(encoded())
        with self.assertRaises(InvalidImage):
            replace(result, encoded_bytes=bytearray(result.encoded_bytes))
        with self.assertRaises(FrozenInstanceError):
            result.width = 1
        self.assertNotIn("encoded_bytes", repr(result))
        self.assertNotIn(repr(result.encoded_bytes), repr(result))

    def test_truncated_jpeg_full_decode(self):
        raw = encoded("JPEG", size=(30, 20))[:-10]
        # Header still opens: preparation must go further and load pixel data.
        with Image.open(BytesIO(raw)) as header:
            self.assertEqual(header.size, (30, 20))
        with self.assertRaises(InvalidImage):
            prepare_image(raw)

    def test_corrupt_png_integrity(self):
        raw = encoded()[:-15]
        with self.assertRaises(InvalidImage):
            prepare_image(raw)

    def test_png_terminal_chunk_must_be_complete_and_valid(self):
        raw = encoded()
        for damaged in (raw[:-1], raw[:-4], raw[:-12],
                        raw[:-1] + bytes([raw[-1] ^ 1]),
                        raw[:-12] + b"\x00\x00\x00\x01" + raw[-8:]):
            with self.subTest(tail=damaged[-12:]), self.assertRaises(InvalidImage):
                prepare_image(damaged)

    def test_png_end_marker_inside_metadata_is_not_terminal_chunk(self):
        text = PngImagePlugin.PngInfo()
        text.add_text("Comment", "IEND")
        raw = encoded(pnginfo=text)
        self.assertEqual(prepare_image(raw).width, 12)
        with self.assertRaises(InvalidImage):
            prepare_image(raw[:-4])

    def test_animation_rejected(self):
        with Image.new("RGB", (2, 2), "red") as first, Image.new("RGB", (2, 2), "blue") as second, BytesIO() as buffer:
            first.save(buffer, format="PNG", save_all=True, append_images=[second])
            with self.assertRaises(UnsupportedImage):
                prepare_image(buffer.getvalue())

    def test_decoder_message_not_exposed(self):
        with patch.object(images.Image, "open", side_effect=OSError("synthetic sensitive detail")):
            with self.assertRaises(InvalidImage) as raised:
                prepare_image(b"image")
        self.assertEqual(str(raised.exception), "Image could not be decoded")
        self.assertTrue(raised.exception.__suppress_context__)
