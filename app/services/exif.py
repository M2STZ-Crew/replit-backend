"""EXIF GPS extraction + image validation (v8 Section 3.1).

The uploaded photo is validated as a real JPEG/PNG (Pillow) and its EXIF GPS, if
present, is extracted (exifread). Gallery uploads usually strip EXIF, so absence
is normal and yields a NO-EXIF state rather than a rejection.
"""

from __future__ import annotations

import io
from typing import Any

import exifread
from PIL import Image, UnidentifiedImageError

from app.core.exceptions import BadRequestError
from app.core.logging import get_logger

log = get_logger(__name__)


def validate_image(content: bytes) -> tuple[int, int]:
    """Confirm bytes are a valid image and return (width, height); raise on invalid."""
    try:
        with Image.open(io.BytesIO(content)) as img:
            img.verify()
        with Image.open(io.BytesIO(content)) as img2:
            return img2.size
    except (UnidentifiedImageError, OSError) as exc:
        raise BadRequestError("Uploaded file is not a valid image.") from exc


def extract_gps(content: bytes) -> tuple[float, float] | None:
    """Return (lat, lng) decimal degrees from the image EXIF GPS, or None if absent."""
    try:
        tags = exifread.process_file(io.BytesIO(content), details=False)
    except Exception:
        log.warning("exif_parse_failed", exc_info=True)
        return None
    lat = _dms_to_decimal(tags.get("GPS GPSLatitude"), tags.get("GPS GPSLatitudeRef"))
    lng = _dms_to_decimal(tags.get("GPS GPSLongitude"), tags.get("GPS GPSLongitudeRef"))
    if lat is None or lng is None:
        return None
    return (lat, lng)


def _dms_to_decimal(value: Any, ref: Any) -> float | None:
    """Convert an exifread degrees/minutes/seconds GPS value + hemisphere ref to decimal."""
    if value is None or ref is None:
        return None
    try:
        parts = value.values
        degrees = float(parts[0].num) / float(parts[0].den)
        minutes = float(parts[1].num) / float(parts[1].den)
        seconds = float(parts[2].num) / float(parts[2].den)
        decimal = degrees + minutes / 60.0 + seconds / 3600.0
        if str(ref.values).strip().upper() in ("S", "W"):
            decimal = -decimal
        return decimal
    except (AttributeError, IndexError, ValueError, TypeError, ZeroDivisionError):
        return None