from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True, slots=True)
class PlotBounds:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Component:
    x: float
    y: float
    width: int
    height: int
    area: int

    @property
    def bbox(self) -> dict[str, float]:
        return {
            "x0": self.x - self.width / 2,
            "y0": self.y - self.height / 2,
            "x1": self.x + self.width / 2,
            "y1": self.y + self.height / 2,
        }


def load_rgb(path: str | Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"))


def _group_indices(indices: np.ndarray) -> list[np.ndarray]:
    if not len(indices):
        return []
    return np.split(indices, np.where(np.diff(indices) > 1)[0] + 1)


def detect_plot_bounds(rgb: np.ndarray) -> PlotBounds:
    height, width = rgb.shape[:2]
    dark = np.all(rgb < 70, axis=2)
    col_counts = dark[int(height * 0.04) : int(height * 0.96)].sum(axis=0)
    row_counts = dark[:, int(width * 0.03) : int(width * 0.98)].sum(axis=1)
    vertical = np.where(col_counts > height * 0.30)[0]
    horizontal = np.where(row_counts > width * 0.30)[0]
    vgroups = _group_indices(vertical)
    hgroups = _group_indices(horizontal)
    vcenters = [int(np.median(group)) for group in vgroups if len(group)]
    hcenters = [int(np.median(group)) for group in hgroups if len(group)]
    plausible_x = [x for x in vcenters if width * 0.01 < x < width * 0.995]
    plausible_y = [y for y in hcenters if height * 0.03 < y < height * 0.96]
    if len(plausible_x) < 2 or len(plausible_y) < 2:
        raise ValueError("Unable to detect plot spines")
    return PlotBounds(min(plausible_x), min(plausible_y), max(plausible_x), max(plausible_y))


def color_mask(rgb: np.ndarray, target: tuple[int, int, int], tolerance: float) -> np.ndarray:
    delta = rgb.astype(np.int32) - np.asarray(target, dtype=np.int32)
    return np.sqrt(np.sum(delta * delta, axis=2)) <= tolerance


def connected_components(
    mask: np.ndarray,
    bounds: PlotBounds,
    *,
    min_area: int,
    max_area: int,
    margin: int = 4,
) -> list[Component]:
    crop = mask[bounds.top + margin : bounds.bottom - margin,
                bounds.left + margin : bounds.right - margin].astype(np.uint8)
    count, _, stats, centroids = cv2.connectedComponentsWithStats(crop, connectivity=8)
    components: list[Component] = []
    for index in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[index])
        if area < min_area or area > max_area:
            continue
        cx, cy = centroids[index]
        components.append(Component(
            x=float(cx + bounds.left + margin),
            y=float(cy + bounds.top + margin),
            width=width,
            height=height,
            area=area,
        ))
    return components


def fit_linear_axis(samples: list[tuple[float, float]]) -> dict[str, float] | None:
    if len(samples) < 2:
        return None
    pixels = np.asarray([sample[0] for sample in samples], dtype=float)
    values = np.asarray([sample[1] for sample in samples], dtype=float)
    if np.ptp(pixels) < 5 or np.ptp(values) == 0:
        return None
    slope, intercept = np.polyfit(pixels, values, 1)
    predicted = pixels * slope + intercept
    rmse = float(np.sqrt(np.mean((values - predicted) ** 2)))
    return {"slope": float(slope), "intercept": float(intercept), "rmse": rmse,
            "sample_count": len(samples)}


def apply_axis(calibration: dict[str, float] | None, pixel: float) -> float | None:
    if not calibration:
        return None
    return float(calibration["slope"] * pixel + calibration["intercept"])
