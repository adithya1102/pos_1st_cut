"""OCR a photographed menu into candidate dishes.

## Nothing here writes to the menu
This module reads images and returns suggestions. Approved candidates are
created by the app through the EXISTING `POST /pos/menu-items` path
(CarevoService.create_menu_item) — there is deliberately no second creation
route, so ownership scoping, category validation and the returned item shape
have exactly one implementation.

## Nothing is persisted
Candidates are derived data with a lifetime of minutes: the owner shoots
photos, reviews the list and approves. They live in the response and then in
the app's screen state. See the endpoint docstring for the full reasoning; the
short version is that the source of truth is the photograph, which the owner
still has, and re-running OCR reproduces the list.

## The dependency is heavy and therefore gated
RapidOCR pulls onnxruntime + OpenCV + numpy — roughly 350 MB installed. It is
imported LAZILY and behind `OCR_ENABLED`, exactly as PushService imports
google-auth lazily and PUSH_ENABLED gates FCM. Consequences that matter:

  * the app still boots, and every other route still works, on a deploy where
    the package is not installed at all;
  * the models (~15 MB, bundled in the wheel — nothing is downloaded at
    runtime) are loaded once into a module-level engine and reused, because
    building a session per request would dominate the request time.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

from fastapi import HTTPException

from app.core.config import settings
from app.modules.menu_ocr.parser import parse_lines

logger = logging.getLogger(__name__)

# Bounds on one request. Ten images is the product cap; the per-image byte cap
# is what stops ten full-resolution photos becoming a ~100 MB request on a
# 512 MB instance.
MAX_IMAGES = 10
MAX_IMAGE_BYTES = 8 * 1024 * 1024        # 8 MB per image
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}

# Whole-request ceiling on the OCR work itself. Inference is CPU-bound and
# runs on a shared free-tier core; without a bound, ten dense pages could hold
# a worker for minutes.
OCR_TIMEOUT_SECONDS = 120

_engine = None
_engine_lock = threading.Lock()


def ocr_available() -> bool:
    """Whether this deploy can OCR at all: the flag AND the package.

    A property of the DEPLOYMENT. The app surfaces it so the empty state can
    offer manual entry rather than a button that cannot work.
    """
    if not settings.OCR_ENABLED:
        return False
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def _get_engine():
    """Build the RapidOCR session once, on first use.

    Double-checked under a lock: two concurrent first requests would otherwise
    each build a session and briefly double the model memory on an instance
    that has none to spare.
    """
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR
            logger.info("Loading RapidOCR models (first OCR request)")
            _engine = RapidOCR()
    return _engine


def _ocr_image_blocking(data: bytes) -> list[str]:
    """Recognised text lines from one image, top-to-bottom.

    Blocking and CPU-bound; [extract_candidates] runs it off the event loop.
    A single unreadable image returns nothing rather than failing the batch —
    one blurry photo out of ten must not lose the other nine.
    """
    try:
        import numpy as np
        from PIL import Image
        import io

        # Decoded here rather than handing RapidOCR a path: the bytes never
        # touch disk, which matters on an ephemeral filesystem and avoids
        # writing customer-supplied files anywhere.
        image = Image.open(io.BytesIO(data))
        # EXIF orientation is not applied by default, and a phone photo taken
        # in portrait is frequently stored rotated — OCR of a sideways menu
        # returns nothing at all.
        try:
            from PIL import ImageOps
            image = ImageOps.exif_transpose(image)
        except Exception:
            pass
        image = image.convert("RGB")

        result, _elapsed = _get_engine()(np.array(image))
    except Exception:
        logger.exception("OCR failed for one image; continuing with the rest")
        return []

    if not result:
        return []

    # RapidOCR returns [box, text, confidence] per detected span. Spans are
    # regrouped into LINES by vertical position: the parser's core rule is
    # "the price is at the end of the line", and a menu's name and price are
    # separate spans that must be rejoined before that rule can apply.
    spans = []
    for item in result:
        try:
            box, text, _conf = item[0], item[1], item[2]
            ys = [float(p[1]) for p in box]
            xs = [float(p[0]) for p in box]
            spans.append((sum(ys) / len(ys), min(xs), str(text)))
        except Exception:
            continue

    spans.sort(key=lambda s: (s[0], s[1]))

    lines: list[str] = []
    current: list[tuple[float, str]] = []
    current_y: Optional[float] = None
    # Two spans within this many pixels vertically are the same row. A fixed
    # tolerance is crude, but the alternative (deriving it from box heights)
    # is not obviously better on a photo taken at an angle.
    row_tolerance = 12.0

    for y, x, text in spans:
        if current_y is None or abs(y - current_y) <= row_tolerance:
            current.append((x, text))
            current_y = y if current_y is None else (current_y + y) / 2
        else:
            current.sort(key=lambda s: s[0])
            lines.append(" ".join(t for _x, t in current))
            current = [(x, text)]
            current_y = y

    if current:
        current.sort(key=lambda s: s[0])
        lines.append(" ".join(t for _x, t in current))

    return lines


async def extract_candidates(images: list[bytes]) -> dict:
    """OCR every image and parse the combined text into candidates.

    Returns the candidate list plus how many images were actually readable, so
    the app can say "3 of 5 photos could not be read" instead of showing a
    short list with no explanation.
    """
    if not ocr_available():
        raise HTTPException(
            status_code=503,
            detail="Menu photo import is not enabled on this server.",
        )
    if not images:
        raise HTTPException(status_code=422, detail="No images provided")
    if len(images) > MAX_IMAGES:
        raise HTTPException(
            status_code=422,
            detail=f"At most {MAX_IMAGES} images per request",
        )

    def _run() -> tuple[list[str], int]:
        all_lines: list[str] = []
        readable = 0
        for data in images:
            lines = _ocr_image_blocking(data)
            if lines:
                readable += 1
            all_lines.extend(lines)
        return all_lines, readable

    try:
        # to_thread + a hard deadline: inference is CPU-bound, and running it
        # on the event loop would stall every other request on the instance.
        lines, readable = await asyncio.wait_for(
            asyncio.to_thread(_run), timeout=OCR_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Reading the photos took too long. Try fewer or smaller images.",
        )

    candidates = parse_lines(lines)
    return {
        "candidates": candidates,
        "images_received": len(images),
        "images_read": readable,
    }
