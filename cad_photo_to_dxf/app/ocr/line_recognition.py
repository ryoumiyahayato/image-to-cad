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


def _normalized_text(text):
    return " ".join(str(text).split())


def _tile_starts(size, side, overlap):
    last = max(0, size - side)
    return [*range(0, last, side-overlap), last]


def _small_line_regions(ink, cancellation_token):
    """Find horizontal groups of glyph-sized ink at the scan's native scale."""
    _, labels, stats, _ = cv2.connectedComponentsWithStats(ink)
    widths, heights, areas = stats[:, 2:].T
    regions = []
    for size in (9, 16, 28, 48):
        checkpoint(cancellation_token)
        glyphs = ((heights >= 0.55*size) & (heights <= 1.30*size)
                  & (widths >= 2) & (widths <= 6*heights) & (areas >= 0.08*size**2))
        glyphs[0] = False
        ink_at_size = np.uint8(glyphs[labels])
        expanded = cv2.dilate(ink_at_size, np.ones((3, 2*size+1), np.uint8))
        boxes, _ = cv2.findContours(expanded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for box in boxes:
            x, y, w, h = cv2.boundingRect(box)
            if h > 1.6*size or w < 4*size or w > 38*size:
                continue
            local = ink_at_size[y:y+h, x:x+w]
            ys, xs = np.nonzero(local)
            used = np.unique(labels[y+ys, x+xs])
            if len(used) < 3 or not 0.09 <= xs.size / (np.ptp(xs)+1) / (np.ptp(ys)+1) <= 0.75:
                continue
            x0, y0 = x+xs.min(), y+ys.min()
            x1, y1 = x+xs.max()+1, y+ys.max()+1
            regions.append((x0, y0, x1, y1))
    return regions


def _recover_small_lines(engine, image, ink, *, cancellation_token=None):
    """Recognize native-resolution crops after the page detector has missed them."""
    height, width = ink.shape
    side, overlap = 1536, 256
    regions = set()
    for top in _tile_starts(height, side, overlap):
        for left in _tile_starts(width, side, overlap):
            checkpoint(cancellation_token)
            local = ink[top:top+side, left:left+side]
            gray = image[top:top+side, left:left+side]
            # Detached bright haloes can join nearby rows in the delivery
            # mask. Only use the darker source cores to seed OCR regions.
            cores = np.uint8((local > 0) & (gray < 200))
            h, w = cores.shape
            for x0, y0, x1, y1 in _small_line_regions(cores, cancellation_token):
                if (left and x0 < 8 or left+w < width and x1 > w-8
                        or top and y0 < 8 or top+h < height and y1 > h-8):
                    continue
                regions.add((x0+left, y0+top, x1+left, y1+top))

    for x0, y0, x1, y1 in sorted(regions):
        checkpoint(cancellation_token)
        pad = max(2, round((y1-y0)*0.16))
        x0, y0 = max(0, x0-pad), max(0, y0-pad)
        x1, y1 = min(width, x1+pad), min(height, y1+pad)
        crop = np.ascontiguousarray(image[y0:y1, x0:x1])
        h, w = crop.shape
        # Try a mild de-slant for right-leaning lettering. The saved box
        # stays in unwarped page coordinates.
        upright = cv2.warpAffine(crop, np.float32([[1, 0.4, 0], [0, 1, 0]]),
                                 (w+round(0.4*h), h), flags=cv2.INTER_CUBIC, borderValue=255)
        observations = []
        for view in (crop, upright):
            result = engine(view, use_det=False, use_cls=False, use_rec=True)
            if (result is not None and result.txts is not None and result.scores is not None
                    and len(result.txts) and len(result.scores)):
                text = _normalized_text(result.txts[0])
                score = float(result.scores[0])
                # Exclude isolated recognition fragments from proposed lines.
                if sum(c.isalnum() for c in text) >= 4 and np.isfinite(score) and score >= 0.65:
                    observations.append((score, text))
        if observations:
            score, text = max(observations)
            quad = ((float(x0), float(y0)), (float(x1), float(y0)),
                    (float(x1), float(y1)), (float(x0), float(y1)))
            yield RecognizedLine(text, score, quad)


def recognize_lines(image, *, recovery=None, min_text_confidence=0.70,
                    cancellation_token=None, progress_callback=None):
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
        for top in _tile_starts(height, side, overlap):
            for left in _tile_starts(width, side, overlap):
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
            text = _normalized_text(text)
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
    if recovery is not None and max(width, height) > 2560:
        recovered = _recover_small_lines(engine, *recovery, cancellation_token=cancellation_token)
        for candidate in sorted(recovered, key=lambda c: c.confidence, reverse=True):
            duplicates = [old for old in kept if _same_area(candidate, old)]
            if duplicates and (candidate.confidence < min_text_confidence
                               or any(old.confidence >= min_text_confidence for old in duplicates)):
                continue
            kept = [old for old in kept if old not in duplicates]
            kept.append(candidate)
    return sorted(kept, key=lambda c: (round(c.bbox[1]/8), c.bbox[0]))
