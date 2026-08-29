"""Build the brand assets from the raw Gusto Skip logo.

    python scripts/make_app_icon.py

Reads  gusto_skip_logo.jpeg                       (repo root, raw source)
Writes customer_app/assets/brand/gusto_logo.png   (full lockup, transparent — splash)
       customer_app/assets/icon/app_icon.png      (SYMBOL only, opaque white square)
       owner_app/assets/icon/app_icon.png         (same file, copied)
       admin_app/app/icon.png                     (same mark, 512px favicon)

Two different marks, on purpose
------------------------------
The splash gets the FULL LOCKUP — wordmark plus spork — because it has the room
and the app should say its own name on launch.

The launcher icon gets the STOPWATCH ONLY. The lockup is a 2.32:1 horizontal
band; dropped into a square icon it fills 82% of the width but 35% of the
height, so at the 48dp most launchers actually draw, "Gusto Skip" is an
unreadable smudge. The spork is no rescue — on its own it is 4.56:1, WIDER than
the lockup, and its hairline stroke vanishes entirely at 48dp. The stopwatch
that serves as the 'o' in "Gusto" is the only element of this lockup that is
near-square (0.81:1) and heavy enough to survive being drawn 48 pixels across.

Why the photograph needs pre-processing
---------------------------------------
The source is a PHOTOGRAPH of the logo, not flat vector art. Its "white" field
runs 207-255 with a strong left-to-right gradient (left edge ~216, right ~245)
plus corner vignetting. That breaks the downstream keying step:
`make_adaptive_foreground.py` treats anything under WHITE_FLOOR=240 as artwork,
and 59.6% of the raw photo falls under 240 — it would key the background itself
in and yield a grey blob instead of a logo.

The saving grace is a clean separation: the darkest background pixel anywhere is
207, while every pixel of actual ink is under 200. So a ramp anchored just below
207 isolates the mark exactly, with antialiased edges preserved, and writes a
genuinely pure-white square — after which the WHITE_FLOOR=240 pipeline works
unmodified.

Ink is forced to pure black rather than kept as-is, because JPEG chroma noise
tints the thin strokes a muddy blue-grey that shows at large icon sizes.

Known limitation
----------------
The stopwatch is only 73x90 pixels in the source photo, so the 1920px icon
master is an ~11x upscale. It downsamples cleanly to real launcher sizes
(48-96dp), which is what ships, but it is visibly soft at the 1024px App Store
size. Replace SRC with vector art or a high-resolution original when one exists
and rerun; nothing else needs to change.

Rerun this if gusto_skip_logo.jpeg changes, then
`python scripts/make_adaptive_foreground.py`, then
`dart run flutter_launcher_icons` in customer_app and owner_app.
"""

import shutil
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "gusto_skip_logo.jpeg"

# Darkest background pixel measured at 207; ink is all below 200. Anchor the
# ramp just under the background floor so no field pixel survives keying.
BG_FLOOR = 205
# Ramp steeply past the floor so solid strokes reach full opacity and only
# genuinely antialiased edge pixels keep partial alpha.
ALPHA_GAIN = 3.0

# The stopwatch's box within the keyed lockup, in lockup pixel coordinates.
# Derived by connected-component analysis: the lockup splits into a wordmark
# band (rows 0-110) and the spork (rows 138-280); within the wordmark the
# components are G / u / s / t / STOPWATCH / S / k / i / p, and the stopwatch is
# the one spanning x[286..358]. Hardcoded rather than re-derived at runtime
# because every "pick the round glyph" heuristic also matches the capital G
# (0.94:1, nearly as square). SYMBOL_SHAPE below turns a stale box into a loud
# failure instead of a silently wrong icon.
SYMBOL_BOX = (286, 0, 359, 111)  # left, upper, right, lower
SYMBOL_SHAPE = (73, 90)

# Artwork fills this much of the opaque square. The mark is near-square, so
# unlike the old wide lockup it has corners that a circular launcher mask can
# actually cut — 0.72 keeps it clear of that while still reading as an icon
# rather than a stamp floating in white.
FILL = 0.72
OUT_SIZE = 1920
FAVICON_SIZE = 512


def keyed_lockup() -> Image.Image:
    """The full logo lifted off its photographed background, cropped to bounds."""
    rgb = np.asarray(Image.open(SRC).convert("RGB")).astype(np.int16)
    alpha = np.clip((BG_FLOOR - rgb.min(axis=2)) * ALPHA_GAIN, 0, 255).astype(np.uint8)
    ink = np.zeros_like(rgb, dtype=np.uint8)
    keyed = Image.fromarray(np.dstack([ink, alpha]), "RGBA")
    return keyed.crop(keyed.getbbox())


def symbol_of(lockup: Image.Image) -> Image.Image:
    """The stopwatch alone — the only near-square element of the lockup."""
    mark = lockup.crop(SYMBOL_BOX)
    mark = mark.crop(mark.getbbox())
    if mark.size != SYMBOL_SHAPE:
        raise SystemExit(
            f"SYMBOL_BOX no longer isolates the stopwatch: got {mark.size}, "
            f"expected {SYMBOL_SHAPE}. The source art changed — re-derive the "
            f"box before trusting the generated icons."
        )
    return mark


def square_icon(mark: Image.Image, size: int) -> Image.Image:
    """Centre `mark` on an opaque white square, scaled to FILL of the canvas."""
    mw, mh = mark.size
    if mw >= mh:
        width = int(size * FILL)
        height = int(mh * width / mw)
    else:
        height = int(size * FILL)
        width = int(mw * height / mh)
    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    canvas.alpha_composite(
        mark.resize((width, height), Image.LANCZOS),
        ((size - width) // 2, (size - height) // 2),
    )
    return canvas


def main() -> None:
    lockup = keyed_lockup()
    brand = ROOT / "customer_app" / "assets" / "brand"
    brand.mkdir(parents=True, exist_ok=True)
    lockup.save(brand / "gusto_logo.png")
    print(
        f"lockup {lockup.size[0]}x{lockup.size[1]} "
        f"(aspect {lockup.size[0] / lockup.size[1]:.2f}) -> assets/brand/gusto_logo.png"
    )

    mark = symbol_of(lockup)
    print(f"symbol {mark.size[0]}x{mark.size[1]} (aspect {mark.size[0] / mark.size[1]:.2f}) — stopwatch")

    icon = square_icon(mark, OUT_SIZE)
    primary = ROOT / "customer_app" / "assets" / "icon" / "app_icon.png"
    icon.save(primary)
    shutil.copyfile(primary, ROOT / "owner_app" / "assets" / "icon" / "app_icon.png")
    print(f"icon {OUT_SIZE}x{OUT_SIZE}, mark at {FILL:.0%} -> customer_app + owner_app")

    favicon = ROOT / "admin_app" / "app" / "icon.png"
    icon.resize((FAVICON_SIZE, FAVICON_SIZE), Image.LANCZOS).save(favicon)
    print(f"favicon {FAVICON_SIZE}x{FAVICON_SIZE} -> admin_app/app/icon.png")


if __name__ == "__main__":
    main()
