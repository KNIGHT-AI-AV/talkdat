"""Roman clay / lime wash panel texture.

Utility windows used to be drawn at -alpha 0.965 to look like glass. Tk applies
alpha to the whole window, so 3.5% of whatever sat behind composited straight
through the panel -- and over a bright saturated shape on a near-black theme
that is plainly visible. It read as unexplained coloured lines drawn across the
text, which is what prompted this.

So panels are opaque now, and the tactile quality comes from a painted texture
instead. The first attempt was three sine waves at an amplitude of 9, rendered
into a 192px tile and then stretched across the panel with bicubic smoothing.
Stretching is what killed it: a 3x upscale is a blur, so the only surviving
detail was the broadest wave. It read as a slightly uneven gradient rather than
plaster, which is fair -- it was one.

Real lime wash and Roman clay have three things at once, and all three matter:

  - directional trowel strokes, from the blade being drawn across the wall
  - tonal drift at several scales, because the coat is laid on unevenly
  - fine mineral speckle in the lime itself, visible close up

This builds all three from sums of sinusoids whose frequencies are whole
numbers of cycles per tile. That constraint is the whole trick: every component
completes an exact number of cycles across the tile, so the pattern meets itself
at the edges and the tile can be repeated at 1:1 instead of stretched. Fine
grain survives, because nothing is ever resampled.

No PIL and no tkinter, so it remains testable without a display.  The scalar
functions stay as the reference contract; a NumPy companion renders the exact
same tile in one vectorized pass for interactive UI use.
"""

from __future__ import annotations

import math

import numpy as np

# Panels are fully opaque. See the module docstring: partial alpha is what let
# background windows show through the text.
CLAY_OPACITY = 1.0

# Edge length of the generated tile, in pixels. Every frequency below is a whole
# number of cycles across this distance, which is what makes the tile seamless.
_TILE = 256

# Peak channel shift, in 0-255 units, for each layer.
#
# The old single layer was capped at 9 because anything stronger read as noise.
# That ceiling was a consequence of having no structure: undifferentiated wobble
# does start to look like film grain. Structured plaster does not, so the total
# here is far higher and still reads as a surface rather than as interference.
_STROKE_AMPLITUDE = 11.0
_DRIFT_AMPLITUDE = 9.0
_SPECKLE_AMPLITUDE = 3.5

# Trowel strokes run across the panel at a shallow angle, the way a blade is
# actually drawn. Expressed as cycles per tile: slow along the stroke, quick
# across it, which is what makes a stroke look like a stroke and not a blob.
_STROKES: tuple[tuple[int, int, float], ...] = (
    (2, 7, 1.00),
    (5, 11, 0.62),
    (-3, 9, 0.52),
    (7, 13, 0.34),
    (-6, 17, 0.28),
    (11, 5, 0.24),
    (-9, 23, 0.18),
)

# Broad unevenness in how thickly the coat was laid on. Low frequencies only.
_DRIFT: tuple[tuple[int, int, float], ...] = (
    (1, 1, 1.00),
    (2, 1, 0.55),
    (1, 2, 0.50),
    (3, 2, 0.30),
    (2, 3, 0.26),
    (4, 3, 0.16),
)

# Mineral grain in the lime. High frequency, low amplitude, and the only layer
# that survives being looked at closely.
_SPECKLE: tuple[tuple[int, int, float], ...] = (
    (29, 31, 1.00),
    (37, 29, 0.72),
    (43, 47, 0.55),
    (53, 41, 0.40),
)

_TAU = math.tau


def texture_tile_size() -> int:
    """Edge length of the generated tile.

    Large enough that the repeat is not obvious behind a panel, small enough to
    regenerate instantly when the theme changes. The tile is repeated, never
    scaled, so this is also the resolution the texture is actually seen at.
    """
    return _TILE


def _layer(
    components: tuple[tuple[int, int, float], ...],
    x: int,
    y: int,
    phase: float,
) -> float:
    """Sum one family of sinusoids at a pixel, normalised to roughly -1..1.

    Frequencies are cycles per tile, so `fx * x / _TILE` completes exactly `fx`
    cycles across the width. Every component therefore wraps cleanly and the
    tile has no seam.
    """
    total = 0.0
    weight = 0.0
    for index, (fx, fy, amplitude) in enumerate(components):
        offset = phase + index * 1.2799
        total += amplitude * math.sin(_TAU * ((fx * x + fy * y) / _TILE) + offset)
        weight += amplitude
    return total / weight if weight else 0.0


def mottle(x: int, y: int, *, seed: int = 0) -> float:
    """Smooth pseudo-random variation in -1..1 for a pixel position.

    Deterministic for a given position and seed, so a panel redrawn on resize
    does not shimmer. Combines the three plaster layers in the proportions they
    appear on a real wall: strokes dominate, drift shifts them around, and
    speckle sits on top too finely to read as pattern.
    """
    phase = seed * 0.7391
    strokes = _layer(_STROKES, x, y, phase)
    drift = _layer(_DRIFT, x, y, phase * 1.7 + 0.9)
    speckle = _layer(_SPECKLE, x, y, phase * 2.9 + 2.1)

    # Strokes are modulated by the drift rather than added alongside it. Summing
    # them independently made every stroke run the full width at equal strength,
    # which reads as corduroy -- regular parallel banding, the one thing plaster
    # never looks like. A trowel pass instead presses hard somewhere and lifts
    # away, so the strokes have to fade in and out across the surface, and the
    # thickness of the coat is exactly what decides where.
    envelope = 0.45 + 0.55 * (drift * 0.5 + 0.5)

    total = (
        strokes * envelope * _STROKE_AMPLITUDE
        + drift * _DRIFT_AMPLITUDE
        + speckle * _SPECKLE_AMPLITUDE
    )
    scale = _STROKE_AMPLITUDE + _DRIFT_AMPLITUDE + _SPECKLE_AMPLITUDE
    return max(-1.0, min(1.0, total / scale))


def clay_pixel(base: tuple[int, int, int], x: int, y: int, *, seed: int = 0) -> tuple[int, int, int]:
    """The theme's panel colour, varied for this pixel.

    Lit areas warm slightly and shaded areas cool, because lime plaster holds
    pigment unevenly and a purely neutral lightness ramp reads as grey noise
    laid over a colour rather than as the colour itself having depth. The
    differential is deliberately small: the panel must still read as the
    selected theme, never as beige.
    """
    amount = mottle(x, y, seed=seed)
    shift = amount * (_STROKE_AMPLITUDE + _DRIFT_AMPLITUDE + _SPECKLE_AMPLITUDE)
    warmth = amount * 1.8
    deltas = (shift + warmth, shift, shift - warmth)
    return tuple(  # type: ignore[return-value]
        max(0, min(255, int(round(channel + delta))))
        for channel, delta in zip(base, deltas)
    )


def clay_tile_rgb(base: tuple[int, int, int], *, seed: int = 0) -> np.ndarray:
    """Return the complete seamless tile, pixel-identical to ``clay_pixel``.

    A utility window used to call the scalar reference 65,536 times on the Tk
    thread whenever a new theme tile was needed.  The equations are naturally
    array-shaped; evaluating them together preserves float64 and banker's
    rounding semantics while reducing the cold render from hundreds of
    milliseconds to roughly one display frame on ordinary hardware.
    """

    x = np.arange(_TILE, dtype=np.float64)[None, :]
    y = np.arange(_TILE, dtype=np.float64)[:, None]

    def layer(
        components: tuple[tuple[int, int, float], ...],
        phase: float,
    ) -> np.ndarray:
        total = np.zeros((_TILE, _TILE), dtype=np.float64)
        weight = 0.0
        for index, (fx, fy, amplitude) in enumerate(components):
            offset = phase + index * 1.2799
            total += amplitude * np.sin(
                _TAU * ((fx * x + fy * y) / _TILE) + offset
            )
            weight += amplitude
        return total / weight if weight else total

    phase = seed * 0.7391
    strokes = layer(_STROKES, phase)
    drift = layer(_DRIFT, phase * 1.7 + 0.9)
    speckle = layer(_SPECKLE, phase * 2.9 + 2.1)
    envelope = 0.45 + 0.55 * (drift * 0.5 + 0.5)
    scale = _STROKE_AMPLITUDE + _DRIFT_AMPLITUDE + _SPECKLE_AMPLITUDE
    amount = np.clip(
        (
            strokes * envelope * _STROKE_AMPLITUDE
            + drift * _DRIFT_AMPLITUDE
            + speckle * _SPECKLE_AMPLITUDE
        )
        / scale,
        -1.0,
        1.0,
    )
    shift = amount * scale
    warmth = amount * 1.8
    deltas = np.stack((shift + warmth, shift, shift - warmth), axis=-1)
    return np.clip(
        np.rint(np.asarray(base, dtype=np.float64) + deltas),
        0,
        255,
    ).astype(np.uint8)
