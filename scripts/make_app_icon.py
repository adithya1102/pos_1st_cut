"""Build the brand assets from the final Gusto Skip app-icon artwork.

    python scripts/make_app_icon.py

Reads  gusto_skip_app_icon_final.jpeg               (repo root, source)
Writes customer_app/assets/brand/gusto_logo.png     (mark on transparency — splash)
       owner_app/assets/brand/gusto_logo.png        (same file, copied — splash)
       customer_app/assets/icon/app_icon.png        (opaque white square, 1024)
       owner_app/assets/icon/app_icon.png           (same file, copied)
       admin_app/app/icon.png                       (same mark, 512px favicon)

Both splash screens take the SAME asset, written from here rather than copied by
hand, so the two apps cannot drift apart the next time the artwork changes.

One mark everywhere
-------------------
This artwork is the stacked lockup: "Gusto" over "Skip", with the stopwatch
serving as the 'o'. It supersedes both earlier attempts — the horizontal
wordmark-and-spork lockup, which was unusable as an icon, and the stopwatch
cropped out of it, which was used as a stand-in while no square artwork existed.

Stacking is what makes it work. The horizontal lockup was a 2.32:1 band that
left the type tiny inside a square; stacked, the mark is 1.49:1 and measures
73.6 RMS contrast at 48dp against the horizontal version's 35.1. The
purpose-drawn stopwatch still scores higher in isolation (90.7), but it is a
detail lifted out of a word rather than the brand's own icon, and this artwork
is what the brand actually ships.

Why this source needs so little work
------------------------------------
Unlike the previous photographed logo — whose field ran 207-255 with a
left-to-right gradient and whose thin strokes carried JPEG chroma tint — this is
a clean vector-style render:

  * 1600x1600, square, background uniform at 253.9-254.0 across all six sampled
    patches (previously a 28-level gradient)
  * ink measures R=1.8 G=1.8 B=1.7, channel spread 0.1 — already neutral black
  * the histogram is a plateau: 12.09% of pixels under 200, 11.99% under 150,
    so only ~0.1% sits in the transition band

So the keying here is a light touch, not a rescue. BG_FLOOR is re-derived for
THIS image rather than inherited: the darkest background pixel outside the
artwork is 236, so the ramp anchors just under that. The previous source needed
205, and reusing that number here would have cut into the antialiasing.

The source's own margins are preserved rather than re-cropped and re-fitted.
This file is the designed app icon, padding included; the only change made is
flattening its near-white field to a true 255 so the downstream
make_adaptive_foreground.py (which keys at WHITE_FLOOR=240) sees clean input.

Rerun this if the source changes, then
`python scripts/make_adaptive_foreground.py`, then
`dart run flutter_launcher_icons` in customer_app and owner_app.
"""

import shutil
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "gusto_skip_app_icon_final.jpeg"

# Darkest background pixel outside the artwork measured 236 on this source, so
# anchor just below it. Re-derive rather than reuse if the artwork is replaced.
BG_FLOOR = 232
# Ramp steeply past the floor so solid strokes reach full opacity and only
# genuinely antialiased edge pixels keep partial alpha.
ALPHA_GAIN = 3.0

OUT_SIZE = 1024
FAVICON_SIZE = 512

# Sanity check: this artwork's mark is the 1.49:1 stacked lockup. A wildly
# different aspect means the source was swapped for something else, and the
# splash layout and icon fills both assume roughly this shape.
EXPECTED_ASPECT = (1.30, 1.70)


def keyed_mark() -> Image.Image:
    """The lockup lifted off its background, cropped to its own bounds."""
    rgb = np.asarray(Image.open(SRC).convert("RGB")).astype(np.int16)
    alpha = np.clip((BG_FLOOR - rgb.min(axis=2)) * ALPHA_GAIN, 0, 255).astype(np.uint8)
    ink = np.zeros_like(rgb, dtype=np.uint8)
    keyed = Image.fromarray(np.dstack([ink, alpha]), "RGBA")
    mark = keyed.crop(keyed.getbbox())
    aspect = mark.size[0] / mark.size[1]
    if not EXPECTED_ASPECT[0] <= aspect <= EXPECTED_ASPECT[1]:
        raise SystemExit(
            f"source aspect {aspect:.2f} is outside the expected "
            f"{EXPECTED_ASPECT} for the stacked lockup — check the artwork "
            f"before trusting the generated assets."
        )
    return mark


def flattened_square() -> Image.Image:
    """The source with its near-white field flattened to a true 255, at OUT_SIZE.

    Keeps the artwork's own padding: this file is the designed icon, and
    re-cropping it would second-guess the composition.
    """
    rgb = np.asarray(Image.open(SRC).convert("RGB")).astype(np.int16)
    alpha = np.clip((BG_FLOOR - rgb.min(axis=2)) * ALPHA_GAIN, 0, 255).astype(np.uint8)
    ink = np.zeros_like(rgb, dtype=np.uint8)
    keyed = Image.fromarray(np.dstack([ink, alpha]), "RGBA")
    canvas = Image.new("RGBA", keyed.size, (255, 255, 255, 255))
    canvas.alpha_composite(keyed)
    return canvas.resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)


def main() -> None:
    mark = keyed_mark()
    brand = ROOT / "customer_app" / "assets" / "brand"
    brand.mkdir(parents=True, exist_ok=True)
    mark.save(brand / "gusto_logo.png")
    owner_brand = ROOT / "owner_app" / "assets" / "brand"
    owner_brand.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(brand / "gusto_logo.png", owner_brand / "gusto_logo.png")
    print(
        f"mark {mark.size[0]}x{mark.size[1]} (aspect {mark.size[0] / mark.size[1]:.2f}) "
        f"-> assets/brand/gusto_logo.png (customer_app + owner_app)"
    )

    icon = flattened_square()
    primary = ROOT / "customer_app" / "assets" / "icon" / "app_icon.png"
    icon.save(primary)
    shutil.copyfile(primary, ROOT / "owner_app" / "assets" / "icon" / "app_icon.png")
    print(f"icon {OUT_SIZE}x{OUT_SIZE} (source padding preserved) -> customer_app + owner_app")

    favicon = ROOT / "admin_app" / "app" / "icon.png"
    icon.resize((FAVICON_SIZE, FAVICON_SIZE), Image.LANCZOS).save(favicon)
    print(f"favicon {FAVICON_SIZE}x{FAVICON_SIZE} -> admin_app/app/icon.png")


if __name__ == "__main__":
    main()
