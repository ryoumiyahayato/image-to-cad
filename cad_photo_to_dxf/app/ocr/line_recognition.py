"""Chinese/English OCR at the detected line level.

No character splitting, page identity, development-image vocabulary or saved
recognition certificate participates in this route.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

import cv2
import numpy as np

from app.core.cancellation import checkpoint, report_progress


@dataclass(frozen=True)
class RecognizedLine:
    text: str
    confidence: float
    quad: tuple[tuple[float, float], ...]

    @property
    def bbox(self):
        p = np.asarray(self.quad)
        lo, hi = p.min(axis=0), p.max(axis=0)
        return float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1])


_ENGINE: Any = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from app.core.offline_runtime import private_onnxruntime
        private_onnxruntime()
        from rapidocr import RapidOCR
        params = {
            "Global.text_score": 0.50,
            "Global.max_side_len": 2560,
            "Global.return_word_box": False,
            "Global.return_single_char_box": False,
            "Global.log_level": "warning",
            "Det.limit_side_len": 1536,
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        }
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        models = base / "resources" / "ocr" / "rapidocr"
        names = {"Det":"PP-OCRv6_det_small.onnx", "Cls":"ch_ppocr_mobile_v2.0_cls_mobile.onnx",
                 "Rec":"PP-OCRv6_rec_small.onnx"}
        if models.is_dir() or getattr(sys, "frozen", False):
            missing = [name for name in names.values() if not (models/name).is_file()]
            if missing:
                raise FileNotFoundError("Offline OCR models are missing: " + ", ".join(missing))
            params.update({role+".model_path":str(models/name) for role,name in names.items()})
        _ENGINE = RapidOCR(params=params)
    return _ENGINE


def _same_area(a: RecognizedLine, b: RecognizedLine) -> bool:
    ax0, ay0, ax1, ay1 = a.bbox
    bx0, by0, bx1, by1 = b.bbox
    overlap = max(0, min(ax1, bx1)-max(ax0, bx0)) * max(0, min(ay1, by1)-max(ay0, by0))
    area = min((ax1-ax0)*(ay1-ay0), (bx1-bx0)*(by1-by0))
    return area > 0 and overlap / area > 0.70


def recognize_lines(image, *, cancellation_token=None, progress_callback=None):
    """Return full OCR lines, including low-confidence lines for source retention.

    Large sheets use an overview plus overlapping original-resolution tiles.
    The overview retains sentences that cross tile boundaries. Confidence is
    reported rather than being converted into a fabricated certainty.
    """
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise ValueError("OCR input must be an 8-bit grayscale or BGR image")
    height, width = image.shape[:2]
    jobs = [(0, 0, width, height)]
    if max(width, height) > 2560:
        side, overlap = 2048, 256
        def starts(size):
            last = max(0, size - side)
            return [*range(0, last, side-overlap), last]

        for top in starts(height):
            for left in starts(width):
                jobs.append((left, top, min(width, left+side), min(height, top+side)))
    candidates = []
    engine = _engine()
    for index, (left, top, right, bottom) in enumerate(jobs):
        checkpoint(cancellation_token)
        tile = np.ascontiguousarray(image[top:bottom, left:right])
        if tile.size == 0 or int(np.count_nonzero(tile.min(axis=2) < 220)) < 6:
            continue
        result = engine(tile, use_det=True, use_cls=True, use_rec=True)
        if result is None:
            continue
        boxes, texts, scores = result.boxes, result.txts, result.scores
        if boxes is None or texts is None or scores is None:
            continue
        for box, text, score in zip(boxes, texts, scores):
            text = " ".join(str(text).replace("\r", " ").replace("\n", " ").split())
            points = np.asarray(box, dtype=float).reshape(-1, 2)
            if not text or points.shape != (4, 2) or not np.isfinite(points).all():
                continue
            if not np.isfinite(score) or float(score) < 0.5:
                continue
            # Partial text at an internal tile edge has a full-page/overlap copy.
            if index and (points[:, 0].min() < 8 and left > 0
                          or points[:, 0].max() > right-left-8 and right < width
                          or points[:, 1].min() < 8 and top > 0
                          or points[:, 1].max() > bottom-top-8 and bottom < height):
                continue
            points += (left, top)
            candidates.append(RecognizedLine(text, float(score), tuple(map(tuple, points.tolist()))))
        report_progress(progress_callback, "ocr", (index+1)/len(jobs))
    # Prefer a complete longer observation over its overlapping partial copy.
    kept = []
    for candidate in sorted(candidates, key=lambda c: (len(c.text), c.confidence), reverse=True):
        if not any(_same_area(candidate, old) for old in kept):
            kept.append(candidate)
    return sorted(kept, key=lambda c: (round(c.bbox[1]/8), c.bbox[0]))
