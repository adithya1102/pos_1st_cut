"""Generate the Android adaptive-icon foreground from the brand square.

    python scripts/make_adaptive_foreground.py

Reads  customer_app/assets/icon/app_icon.png   (opaque white square + logo)
Writes customer_app/assets/icon/app_icon_foreground.png  (logo on transparency)

Why this exists
---------------
`app_icon.png` is a full-bleed white square with the logo in the middle. Handing
that to flutter_launcher_icons as `adaptive_icon_foreground` looks fine at a
glance but leaves a faint rounded-square ghost inside Android's circular mask:
the square's "white" field is actually 244-255 (mostly 254) while the adaptive
background layer is pure #FFFFFF, so the image's baked-in rounded corners read as
a ~1-11/255 seam. Keying the logo onto transparency removes the square entirely,
so no mask shape can reveal it.

Rerun this whenever app_icon.png changes, then `dart run flutter_launcher_icons`.
"""

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "customer_app" / "assets" / "icon" / "app_icon.png"
DST = ROOT / "customer_app" / "assets" / "icon" / "app_icon_foreground.png"

# The outermost pixels carry encoder ringing (a handful of 233-239 values that
# are not artwork); trimming a thin frame keeps them out of the bounding box.
FRAME_TRIM = 8
# Field measured 244-255, so anything at/above this is background, not artwork.
WHITE_FLOOR = 240
# Ramp steeply past the floor so solid strokes land at full opacity and only
# genuinely antialiased edge pixels keep partial alpha.
ALPHA_GAIN = 3.5
# Artwork fills this much of the square foreground canvas.
#
# This used to be 0.92, on the stated assumption that `adaptive_icon_foreground_
# inset: 12` in pubspec.yaml would bring the result inside Android's safe zone.
# It does not — flutter_launcher_icons 0.14.4 ignores the option, and the
# generated density assets measure out at whatever fill this constant sets. The
# icon that shipped under 0.92 landed at 99dp of the 108dp canvas and lost 5.2%
# of its ink to the circular launcher mask.
#
# 0.60 puts the mark at 64.8dp, inside the published 66dp-of-108dp safe zone
# (and well inside the 76.4dp at which a centred square would start to clip a
# circle, S*sqrt(2) <= 108). It matters more now than it did: the icon mark is
# the near-square stopwatch, which unlike the old wide lockup has corners for a
# round mask to cut.
FILL = 0.60
OUT_SIZE = 1024


def main() -> None:
    im = Image.open(SRC).convert("RGB")
    w, h = im.size
    im = im.crop((FRAME_TRIM, FRAME_TRIM, w - FRAME_TRIM, h - FRAME_TRIM))

    rgb = np.asarray(im).astype(np.int16)
    alpha = np.clip((WHITE_FLOOR - rgb.min(axis=2)) * ALPHA_GAIN, 0, 255).astype(np.uint8)
    keyed = Image.fromarray(np.dstack([rgb.astype(np.uint8), alpha]), "RGBA")

    art = keyed.crop(keyed.getbbox())
    aw, ah = art.size
    side = int(max(aw, ah) / FILL)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(art, ((side - aw) // 2, (side - ah) // 2))
    canvas.resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS).save(DST)

    print(f"artwork {aw}x{ah} -> canvas {side} -> {DST.name} {OUT_SIZE}x{OUT_SIZE}")


if __name__ == "__main__":
    main()
