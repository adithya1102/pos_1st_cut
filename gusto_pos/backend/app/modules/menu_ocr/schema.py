"""Schemas for menu photo import."""
from __future__ import annotations

from pydantic import BaseModel, Field


class MenuCandidateOut(BaseModel):
    """One suggested dish. NOT a menu item — nothing exists in the database
    for this until the owner approves it and the app calls the ordinary
    POST /pos/menu-items."""
    name: str
    price: float


class MenuOcrOut(BaseModel):
    candidates: list[MenuCandidateOut] = Field(default_factory=list)

    # How many photos were sent versus how many yielded any text at all, so
    # the app can explain a short list ("2 of 5 photos could not be read")
    # rather than leaving the owner to guess whether OCR ran.
    images_received: int = 0
    images_read: int = 0

    # Always true in a 200 — restated in the payload because this is the one
    # field the review screen must not lose sight of. These are guesses.
    best_effort: bool = True


class OcrStatusOut(BaseModel):
    """Whether this DEPLOY can OCR at all (flag + package present).

    Lets the empty state offer manual entry instead of a photo button that
    would only ever answer 503.
    """
    enabled: bool = False
    max_images: int = 10
