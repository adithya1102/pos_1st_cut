"""Menu photo import (staff-authenticated). Mounted under /api/v1.

Reads photographs of a printed menu and SUGGESTS dishes. It never creates one:
approved candidates go back through `POST /pos/menu-items`, the same endpoint
the Add-dish form has always used.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.modules.carevo_customer.deps import get_current_staff
from app.modules.menu_ocr import schema as s
from app.modules.menu_ocr import service as ocr
from app.modules.users.model import User

router = APIRouter(prefix="/pos/menu-import", tags=["Gusto Skip — POS"])


def _require_outlet(staff: User):
    """Same guard the rest of the POS routes use.

    OCR touches no outlet row, but the endpoint is only meaningful for an
    account that has a menu to import INTO, and an unassigned staff account
    should not be able to spend a shared instance's CPU on inference.
    """
    if not staff.outlet_id:
        raise HTTPException(
            status_code=403, detail="Staff account is not assigned to an outlet"
        )
    return staff.outlet_id


@router.get("/status", response_model=s.OcrStatusOut)
async def ocr_status(staff: User = Depends(get_current_staff)):
    """Can this server OCR? Flag plus package, both required.

    The app asks before showing the photo button, so a deploy without the
    dependency shows manual entry rather than a button that only 503s.
    """
    _require_outlet(staff)
    return {"enabled": ocr.ocr_available(), "max_images": ocr.MAX_IMAGES}


@router.post("/ocr", response_model=s.MenuOcrOut)
async def ocr_menu_images(
    images: list[UploadFile] = File(...),
    staff: User = Depends(get_current_staff),
):
    """OCR up to 10 menu photos and return candidate {name, price} pairs.

    ## Candidates are BEST-EFFORT and are not saved anywhere
    The parse is a line-and-regex heuristic over OCR output (see parser.py).
    It misses dishes and mis-reads prices. Every candidate is editable in the
    app and reaches the menu only on an explicit approve.

    ## Why there is no candidates table
    They are derived data with a lifetime of one sitting — shoot, review,
    approve — and the source of truth is the photograph, which the owner still
    has. Re-running OCR reproduces them. A table would buy only "resume a
    half-finished review after killing the app", and would cost a migration, a
    cleanup policy for rows that are garbage the moment they are approved, and
    another outlet-scoped surface to get wrong. Adding persistence later is
    purely additive; starting with a table and removing it is not.

    The APPROVED output is of course persisted — by the ordinary
    POST /pos/menu-items path, which the app calls per approved candidate.
    """
    _require_outlet(staff)

    if len(images) > ocr.MAX_IMAGES:
        raise HTTPException(
            status_code=422,
            detail=f"At most {ocr.MAX_IMAGES} images per request",
        )

    payloads: list[bytes] = []
    for upload in images:
        # Content type is the cheap check; a decode failure in the service is
        # the real one, since the header is client-supplied.
        if upload.content_type and upload.content_type.lower() not in ocr.ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported image type: {upload.content_type}",
            )
        data = await upload.read()
        if len(data) > ocr.MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"'{upload.filename}' is larger than "
                    f"{ocr.MAX_IMAGE_BYTES // (1024 * 1024)} MB"
                ),
            )
        if data:
            payloads.append(data)

    result = await ocr.extract_candidates(payloads)
    return {**result, "best_effort": True}
