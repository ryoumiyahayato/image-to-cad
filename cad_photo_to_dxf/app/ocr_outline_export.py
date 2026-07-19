from __future__ import annotations

from collections.abc import Callable, Sequence
from hashlib import sha1
from math import atan2, degrees, hypot
import os
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .auxiliary_recognition import TextCandidate


PointTransform = Callable[[float, float], tuple[float, float]]
_RENDER_FONT_SIZE = 320
_MIN_CONTOUR_AREA = 3.0
_XDATA_APP = "OCR_LINE_TEXT"


def _contains_cjk(text: str) -> bool:
    return any(
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in text
    )


def _font_paths() -> tuple[Path, ...]:
    configured = os.environ.get("CAD_PHOTO_CJK_FONT")
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [
        *( [Path(configured)] if configured else [] ),
        windows / "msyh.ttc",
        windows / "msyhbd.ttc",
        windows / "simhei.ttf",
        windows / "simsun.ttc",
        windows / "Deng.ttf",
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    return tuple(path for path in candidates if path.exists())


def _load_font(text: str) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _font_paths():
        try:
            font = ImageFont.truetype(str(path), _RENDER_FONT_SIZE)
            if _contains_cjk(text) and path.name.lower() == "dejavusans.ttf":
                continue
            return font
        except OSError:
            continue
    return ImageFont.load_default()


def _render_text_mask(content: str) -> np.ndarray:
    font = _load_font(content)
    try:
        left, top, right, bottom = font.getbbox(content)
    except AttributeError:
        left, top, right, bottom = 0, 0, max(1, len(content) * 12), 16
    width = max(1, int(right - left))
    height = max(1, int(bottom - top))
    padding = max(8, _RENDER_FONT_SIZE // 20)
    image = Image.new("L", (width + padding * 2, height + padding * 2), 0)
    draw = ImageDraw.Draw(image)
    draw.text(
        (padding - left, padding - top),
        content,
        fill=255,
        font=font,
        stroke_width=0,
    )
    mask = np.asarray(image, dtype=np.uint8)
    points = cv2.findNonZero(mask)
    if points is None:
        return np.empty((0, 0), dtype=np.uint8)
    x, y, crop_width, crop_height = cv2.boundingRect(points)
    return np.ascontiguousarray(mask[y : y + crop_height, x : x + crop_width])


def _candidate_quad(text: TextCandidate) -> tuple[tuple[float, float], ...]:
    if text.quad and len(text.quad) == 4:
        return text.quad
    x, y, width, height = text.bbox
    return (
        (float(x), float(y)),
        (float(x + width), float(y)),
        (float(x + width), float(y + height)),
        (float(x), float(y + height)),
    )


def _block_name(prefix: str, index: int, content: str) -> str:
    digest = sha1(content.encode("utf-8")).hexdigest()[:10]
    cleaned_prefix = "".join(
        character if character.isalnum() or character in "_-" else "_"
        for character in prefix
    )[:32]
    return f"{cleaned_prefix}_{index:05d}_{digest}"


def _xdata_chunks(content: str) -> list[tuple[int, str]]:
    encoded = content.encode("utf-8")
    chunks: list[tuple[int, str]] = []
    start = 0
    while start < len(encoded):
        end = min(start + 240, len(encoded))
        while end > start:
            try:
                chunks.append((1000, encoded[start:end].decode("utf-8")))
                break
            except UnicodeDecodeError:
                end -= 1
        start = max(end, start + 1)
    return chunks


def add_ocr_outline_blocks(
    doc,
    layout,
    texts: Sequence[TextCandidate],
    *,
    transform: PointTransform,
    layer_name: str = "OCR_TEXT",
    block_prefix: str = "OCR_LINE",
    minimum_confidence: float = 0.58,
) -> tuple[int, list[object], list[tuple[float, float]]]:
    """Add one font-independent vector block for each accepted OCR text line.

    LibreCAD does not reliably render arbitrary TTF/SHX text styles. This path
    uses a locally installed system font only while exporting, converts the
    complete OCR line into vector contours, and places those contours in one
    INSERT. The original Unicode text is preserved as XDATA on that INSERT.
    """

    if _XDATA_APP not in doc.appids:
        doc.appids.add(_XDATA_APP)

    entities: list[object] = []
    bounds: list[tuple[float, float]] = []
    for index, candidate in enumerate(texts, start=1):
        content = " ".join(
            candidate.text.replace("\r", " ").replace("\n", " ").split()
        )
        if not content or candidate.confidence < minimum_confidence:
            continue
        mask = _render_text_mask(content)
        if mask.size == 0:
            continue
        mask_height, mask_width = mask.shape[:2]
        contours, _hierarchy = cv2.findContours(
            mask,
            cv2.RETR_CCOMP,
            cv2.CHAIN_APPROX_TC89_KCOS,
        )
        usable_contours: list[np.ndarray] = []
        for contour in contours:
            if abs(float(cv2.contourArea(contour))) < _MIN_CONTOUR_AREA:
                continue
            perimeter = float(cv2.arcLength(contour, True))
            epsilon = max(0.45, min(1.8, perimeter * 0.0015))
            approximated = cv2.approxPolyDP(contour, epsilon, True)
            if len(approximated) >= 3:
                usable_contours.append(approximated)
        if not usable_contours:
            continue

        block_name = _block_name(block_prefix, index, content)
        suffix = 1
        resolved_name = block_name
        while resolved_name in doc.blocks:
            suffix += 1
            resolved_name = f"{block_name}_{suffix}"
        block = doc.blocks.new(name=resolved_name)
        for contour in usable_contours:
            points = [
                (float(point[0][0]), float(mask_height - 1 - point[0][1]))
                for point in contour
            ]
            block.add_lwpolyline(
                points,
                close=True,
                dxfattribs={"layer": "0", "color": 0},
            )

        quad = _candidate_quad(candidate)
        transformed = [transform(float(x), float(y)) for x, y in quad]
        top_left, top_right, bottom_right, bottom_left = transformed
        target_width = (
            hypot(top_right[0] - top_left[0], top_right[1] - top_left[1])
            + hypot(bottom_right[0] - bottom_left[0], bottom_right[1] - bottom_left[1])
        ) * 0.5
        target_height = (
            hypot(top_left[0] - bottom_left[0], top_left[1] - bottom_left[1])
            + hypot(top_right[0] - bottom_right[0], top_right[1] - bottom_right[1])
        ) * 0.5
        if target_width <= 0.0 or target_height <= 0.0:
            continue
        rotation = degrees(
            atan2(bottom_right[1] - bottom_left[1], bottom_right[0] - bottom_left[0])
        )
        reference = layout.add_blockref(
            resolved_name,
            bottom_left,
            dxfattribs={
                "layer": layer_name,
                "color": 6,
                "xscale": target_width / max(float(mask_width), 1.0),
                "yscale": target_height / max(float(mask_height), 1.0),
                "rotation": float(rotation),
            },
        )
        reference.set_xdata(_XDATA_APP, _xdata_chunks(content))
        entities.append(reference)
        bounds.extend(transformed)

    return len(entities), entities, bounds
