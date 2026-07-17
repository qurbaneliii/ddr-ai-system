from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class OCRToken:
    text: str
    confidence: float
    x: float
    y: float
    width: float
    height: float


@lru_cache(maxsize=1)
def _rapidocr() -> Any | None:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return None
    return RapidOCR()


def read_tokens(rgb: np.ndarray) -> list[OCRToken]:
    reader = _rapidocr()
    if reader is None:
        return []
    result, _ = reader(rgb)
    tokens: list[OCRToken] = []
    for box, text, score in result or []:
        points = np.asarray(box, dtype=float)
        x0, y0 = points.min(axis=0)
        x1, y1 = points.max(axis=0)
        tokens.append(OCRToken(
            text=str(text).strip(), confidence=float(score), x=float((x0 + x1) / 2),
            y=float((y0 + y1) / 2), width=float(x1 - x0), height=float(y1 - y0),
        ))
    return tokens

