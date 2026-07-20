from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os
import re

import cv2
import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPainter


@dataclass(frozen=True)
class CadFontFace:
    family: str
    filename: str
    label: str
    cjk: bool
    category: str
    priority: int


# This is a runtime font catalog, not redistributed font binaries. The selected
# font filename is written into the DXF text style so CAD and the review preview
# can use the same installed face.
_CURATED_FONTS: tuple[CadFontFace, ...] = (
    CadFontFace("SimHei", "simhei.ttf", "黑体 / SimHei", True, "sans", 10),
    CadFontFace("DengXian", "Deng.ttf", "等线 / DengXian", True, "sans", 20),
    CadFontFace("DengXian", "Dengb.ttf", "等线粗体 / DengXian Bold", True, "sans-bold", 21),
    CadFontFace("FangSong", "simfang.ttf", "仿宋 / FangSong", True, "serif", 30),
    CadFontFace("KaiTi", "simkai.ttf", "楷体 / KaiTi", True, "hand", 40),
    CadFontFace("Arial", "arial.ttf", "Arial", False, "sans", 50),
    CadFontFace("Segoe UI", "segoeui.ttf", "Segoe UI", False, "sans", 60),
    CadFontFace("Calibri", "calibri.ttf", "Calibri", False, "sans", 70),
    CadFontFace("Times New Roman", "times.ttf", "Times New Roman", False, "serif", 80),
)


def contains_cjk(text: str) -> bool:
    return any(
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in text
    )


def _windows_font_directory() -> Path | None:
    windir = os.environ.get("WINDIR")
    if not windir:
        return None
    path = Path(windir) / "Fonts"
    return path if path.exists() else None


def _font_file_exists(filename: str) -> bool:
    font_dir = _windows_font_directory()
    if font_dir is None:
        return True
    return (font_dir / filename).exists()


@lru_cache(maxsize=1)
def available_font_faces() -> tuple[CadFontFace, ...]:
    families = {str(value).casefold() for value in QFontDatabase.families()}
    available = [
        face
        for face in _CURATED_FONTS
        if face.family.casefold() in families and _font_file_exists(face.filename)
    ]
    if available:
        return tuple(sorted(available, key=lambda item: item.priority))
    return (CadFontFace("Sans Serif", "txt", "系统无衬线字体", True, "sans", 999),)


def default_font_face(text: str) -> CadFontFace:
    faces = available_font_faces()
    wants_cjk = contains_cjk(text)
    for face in faces:
        if face.cjk == wants_cjk:
            return face
    return faces[0]


def find_font_face(family: str, filename: str, text: str = "") -> CadFontFace:
    family_value = str(family or "").strip()
    filename_value = Path(str(filename or "")).name
    family_key = family_value.casefold()
    filename_key = filename_value.casefold()
    for face in available_font_faces():
        if filename_key and face.filename.casefold() == filename_key:
            return face
        if family_key and face.family.casefold() == family_key:
            return face
    if family_value or filename_value:
        return CadFontFace(
            family=family_value or default_font_face(text).family,
            filename=filename_value or "txt",
            label=family_value or filename_value,
            cjk=contains_cjk(text),
            category="selected",
            priority=0,
        )
    return default_font_face(text)


def safe_style_name(face: CadFontFace) -> str:
    stem = Path(face.filename).stem if face.filename else face.family
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_").upper()
    return f"OCR_{cleaned or 'UNICODE'}"


def ensure_dxf_font_style(doc, face: CadFontFace) -> str:
    style_name = safe_style_name(face)
    if style_name not in doc.styles:
        doc.styles.add(style_name, font=face.filename or "txt")
    return style_name


def _font_for_face(face: CadFontFace, pixel_size: int) -> QFont:
    font = QFont(face.family)
    font.setPixelSize(max(8, int(pixel_size)))
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def font_metric_ratios(face: CadFontFace) -> tuple[float, float]:
    font = _font_for_face(face, 1000)
    metrics = QFontMetricsF(font)
    height = max(float(metrics.height()), 1.0)
    return float(metrics.ascent()) / height, float(metrics.descent()) / height


def character_advance_units(face: CadFontFace, character: str) -> float:
    if character.isspace():
        return 0.35
    font = _font_for_face(face, 1000)
    metrics = QFontMetricsF(font)
    value = float(metrics.horizontalAdvance(character)) / 1000.0
    if not np.isfinite(value) or value <= 0.02:
        return 1.0 if contains_cjk(character) else 0.62
    return max(0.20, min(value, 1.80))


def _source_text_mask(image: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
    x, y, width, height = bbox
    image_height, image_width = image.shape[:2]
    left = max(0, int(x))
    top = max(0, int(y))
    right = min(image_width, int(x + width))
    bottom = min(image_height, int(y + height))
    if right <= left or bottom <= top:
        return np.zeros((1, 1), dtype=np.uint8)
    crop = image[top:bottom, left:right]
    if crop.ndim == 3:
        if crop.shape[2] == 4:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGRA2GRAY)
        else:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    else:
        gray = crop
    gray = np.ascontiguousarray(gray, dtype=np.uint8)
    _threshold, binary = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )
    h, w = binary.shape
    horizontal = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, w // 2), 1)),
    )
    vertical = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(5, h // 2))),
    )
    cleaned = cv2.subtract(binary, cv2.max(horizontal, vertical))
    return cleaned if cv2.countNonZero(cleaned) else binary


def render_font_mask(
    text: str,
    face: CadFontFace,
    size: tuple[int, int],
) -> np.ndarray:
    width, height = max(1, int(size[0])), max(1, int(size[1]))
    image = QImage(width, height, QImage.Format.Format_Grayscale8)
    image.fill(255)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QColor(0, 0, 0))
    font = _font_for_face(face, max(8, int(height * 0.82)))
    metrics = QFontMetricsF(font)
    available_width = max(1.0, float(width) * 0.96)
    natural_width = max(1.0, float(metrics.horizontalAdvance(text)))
    if natural_width > available_width:
        font.setPixelSize(max(8, int(font.pixelSize() * available_width / natural_width)))
    painter.setFont(font)
    painter.drawText(
        QRectF(0.0, 0.0, float(width), float(height)),
        int(Qt.AlignmentFlag.AlignCenter),
        text,
    )
    painter.end()
    ptr = image.bits()
    array = np.frombuffer(ptr, dtype=np.uint8, count=image.sizeInBytes()).reshape(
        image.height(), image.bytesPerLine()
    )[:, : image.width()]
    return np.where(array < 210, 255, 0).astype(np.uint8)


def _mask_similarity(source: np.ndarray, rendered: np.ndarray) -> float:
    source = np.where(source > 0, 255, 0).astype(np.uint8)
    rendered = np.where(rendered > 0, 255, 0).astype(np.uint8)
    if source.shape != rendered.shape:
        rendered = cv2.resize(
            rendered,
            (source.shape[1], source.shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )
    source_count = int(cv2.countNonZero(source))
    rendered_count = int(cv2.countNonZero(rendered))
    if source_count == 0 or rendered_count == 0:
        return 0.0
    source_distance = cv2.distanceTransform(255 - source, cv2.DIST_L2, 3)
    rendered_distance = cv2.distanceTransform(255 - rendered, cv2.DIST_L2, 3)
    forward = float(source_distance[rendered > 0].mean())
    backward = float(rendered_distance[source > 0].mean())
    diagonal = max(float(np.hypot(*source.shape)), 1.0)
    chamfer = (forward + backward) / (2.0 * diagonal)
    density_penalty = abs(source_count - rendered_count) / max(source_count, rendered_count)
    return max(0.0, 1.0 - chamfer * 4.0 - density_penalty * 0.25)


def match_font_face(
    image: np.ndarray,
    bbox: tuple[int, int, int, int],
    text: str,
) -> tuple[CadFontFace, float]:
    content = str(text or "").strip()
    if not content:
        return default_font_face(text), 0.0
    source = _source_text_mask(image, bbox)
    height, width = source.shape
    candidates = [
        face
        for face in available_font_faces()
        if face.cjk or not contains_cjk(content)
    ]
    if not candidates:
        candidates = list(available_font_faces())
    best_face = default_font_face(content)
    best_score = -1.0
    for face in candidates:
        rendered = render_font_mask(content, face, (width, height))
        score = _mask_similarity(source, rendered)
        if score > best_score:
            best_face = face
            best_score = score
    return best_face, max(0.0, float(best_score))
