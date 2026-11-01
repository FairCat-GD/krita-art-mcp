import math
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

# sRGB to CIE XYZ (D65) with the 7-digit matrix, and the D65 white.
SRGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]
)
WHITE = np.array([0.95047, 1.0, 1.08883])
# Profiles whose stored bytes are sRGB, so L*a*b* describes the colour, not just the bytes.
SRGB_PROFILES = frozenset({"sRGB-elle-V2-srgbtrc.icc", "sRGB built-in"})
DECIMALS = 4

Floats = NDArray[np.float64]


def lab(rgb: ArrayLike) -> Floats:
    # (..., 3) values 0-255 to (..., 3) L*, a*, b*.
    c = np.asarray(rgb, dtype=np.float64) / 255
    linear = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = linear @ SRGB_TO_XYZ.T / WHITE
    delta = 6 / 29
    f = np.where(xyz > delta**3, np.cbrt(xyz), xyz / (3 * delta**2) + 4 / 29)
    return np.stack(
        [116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])],
        axis=-1,
    )


def lch(values: Floats) -> Floats:
    chroma = np.hypot(values[..., 1], values[..., 2])
    hue = np.degrees(np.arctan2(values[..., 2], values[..., 1])) % 360
    return np.stack([values[..., 0], chroma, hue], axis=-1)


def half_up(value: float) -> int:
    # Python's round() and NumPy's rint round half to even; every byte here rounds half up.
    return math.floor(value + 0.5)


def hex_of(rgb: ArrayLike) -> str:
    red, green, blue = (half_up(float(channel)) for channel in np.asarray(rgb))
    return f"#{red:02X}{green:02X}{blue:02X}"


def number(value: float) -> int | float:
    # Integers stay integers, so a stored byte reads back as itself; -0.0 becomes 0.
    if float(value).is_integer():
        return int(value)
    return round(float(value), DECIMALS) + 0.0


def disc(
    square: NDArray[np.uint8],
    origin: tuple[int, int],
    point: tuple[int, int],
    radius: float,
    srgb: bool,
) -> dict[str, Any]:
    # The pixels whose offset from the point is within the radius, of a square read around it.
    height, width = square.shape[:2]
    ys, xs = np.ogrid[origin[1] : origin[1] + height, origin[0] : origin[0] + width]
    inside = (xs - point[0]) ** 2 + (ys - point[1]) ** 2 <= radius * radius
    pixels = square[inside].astype(np.int64)
    count = len(pixels)
    alpha = pixels[:, 3]
    weight = int(alpha.sum())
    # Alpha-weighted, so colour under transparency does not count; the plain mean when all is.
    if weight > 0:
        rgb = (pixels[:, :3] * alpha[:, None]).sum(axis=0) / weight
    else:
        rgb = pixels[:, :3].sum(axis=0) / count
    sample: dict[str, Any] = {
        "pixel_count": count,
        "rgba": [number(channel) for channel in rgb] + [number(weight / count)],
        "hex": None,
        "lab": None,
        "lch": None,
        "stdev_l": None,
    }
    if weight == 0:
        return sample
    sample["hex"] = hex_of(rgb)
    if not srgb:
        return sample
    mean = lab(rgb)
    lightness = lab(pixels[:, :3])[:, 0]
    centre = float((lightness * alpha).sum() / weight)
    variance = float((alpha * (lightness - centre) ** 2).sum() / weight)
    polar = lch(mean)
    sample["lab"] = [number(value) for value in mean]
    hue = polar[2] if round(float(polar[1]), DECIMALS) != 0 else 0.0
    sample["lch"] = [number(polar[0]), number(polar[1]), number(hue)]
    sample["stdev_l"] = number(math.sqrt(max(variance, 0.0)))
    return sample
