from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
import sys

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
    weight: int = 400
    source_path: str = ""
    bundled: bool = False
    registry_name: str = ""


@dataclass(frozen=True)
class FontInstallReport:
    available: int
    installed: int
    already_installed: int
    failed: tuple[str, ...]
    restart_cad_recommended: bool

    @property
    def ready(self) -> bool:
        return self.available > 0 and not self.failed

    def summary(self) -> str:
        if self.available <= 0:
            return "安装包中未找到内置 CAD 字体。"
        if self.failed:
            return "字体安装不完整：" + "；".join(self.failed)
        if self.installed:
            return (
                f"已为当前 Windows 用户安装 {self.installed} 个内置 CAD 字体；"
                "已打开的 CAD 建议重新启动后再查看。"
            )
        return f"内置 CAD 字体已就绪：{self.already_installed} 个。"


_SYSTEM_FONTS: tuple[CadFontFace, ...] = (
    CadFontFace("SimHei", "simhei.ttf", "本机黑体 / SimHei", True, "sans", 200),
    CadFontFace("DengXian", "Deng.ttf", "本机等线 / DengXian", True, "sans", 210),
    CadFontFace("FangSong", "simfang.ttf", "本机仿宋 / FangSong", True, "serif", 220),
    CadFontFace("KaiTi", "simkai.ttf", "本机楷体 / KaiTi", True, "hand", 230),
    CadFontFace("Arial", "arial.ttf", "本机 Arial", False, "sans", 300),
    CadFontFace("Segoe UI", "segoeui.ttf", "本机 Segoe UI", False, "sans", 310),
    CadFontFace("Times New Roman", "times.ttf", "本机 Times New Roman", False, "serif", 320),
)


def contains_cjk(text: str) -> bool:
    return any(
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in text
    )


def _application_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(str(frozen_root))
    return Path(__file__).resolve().parents[1]


def bundled_font_directory() -> Path:
    return _application_root() / "resources" / "fonts"


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


def _load_bundle_manifest() -> tuple[dict[str, object], ...]:
    path = bundled_font_directory() / "manifest.json"
    if not path.exists():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ()
    fonts = payload.get("fonts", []) if isinstance(payload, dict) else []
    return tuple(item for item in fonts if isinstance(item, dict))


def _weight_from_value(value: object) -> int:
    try:
        weight = int(value)
    except (TypeError, ValueError):
        return 400
    return min(900, max(100, weight))


@lru_cache(maxsize=1)
def register_bundled_fonts_for_application() -> tuple[CadFontFace, ...]:
    """Register packaged OFL fonts in Qt and return their resolved family names."""

    directory = bundled_font_directory()
    faces: list[CadFontFace] = []
    for raw in _load_bundle_manifest():
        filename = Path(str(raw.get("filename", ""))).name
        path = directory / filename
        if not filename or not path.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            continue
        registered_families = tuple(QFontDatabase.applicationFontFamilies(font_id))
        configured_family = str(raw.get("family", "")).strip()
        family = (
            configured_family
            if configured_family in registered_families
            else (registered_families[0] if registered_families else configured_family)
        )
        if not family:
            continue
        label = str(raw.get("label", family)).strip() or family
        faces.append(
            CadFontFace(
                family=family,
                filename=filename,
                label=label,
                cjk=bool(raw.get("cjk", True)),
                category=str(raw.get("category", "sans")),
                priority=int(raw.get("priority", 100)),
                weight=_weight_from_value(raw.get("weight", 400)),
                source_path=str(path),
                bundled=True,
                registry_name=str(raw.get("registry_name", "")).strip(),
            )
        )
    return tuple(sorted(faces, key=lambda item: item.priority))


def _system_font_faces() -> tuple[CadFontFace, ...]:
    families = {str(value).casefold() for value in QFontDatabase.families()}
    return tuple(
        face
        for face in _SYSTEM_FONTS
        if face.family.casefold() in families and _font_file_exists(face.filename)
    )


@lru_cache(maxsize=1)
def available_font_faces() -> tuple[CadFontFace, ...]:
    bundled = register_bundled_fonts_for_application()
    faces: list[CadFontFace] = list(bundled)
    seen = {(face.family.casefold(), face.filename.casefold()) for face in faces}
    for face in _system_font_faces():
        key = (face.family.casefold(), face.filename.casefold())
        if key not in seen:
            faces.append(face)
            seen.add(key)
    if faces:
        return tuple(sorted(faces, key=lambda item: item.priority))
    return (
        CadFontFace(
            "Sans Serif",
            "txt",
            "系统无衬线字体（仅回退）",
            True,
            "sans",
            999,
        ),
    )


def default_font_face(text: str) -> CadFontFace:
    faces = available_font_faces()
    wants_cjk = contains_cjk(text)
    for face in faces:
        if face.bundled and (face.cjk or not wants_cjk):
            return face
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
        fallback = default_font_face(text)
        return CadFontFace(
            family=family_value or fallback.family,
            filename=filename_value or fallback.filename,
            label=family_value or filename_value,
            cjk=contains_cjk(text),
            category="selected",
            priority=0,
            weight=400,
        )
    return default_font_face(text)


def safe_style_name(face: CadFontFace) -> str:
    stem = Path(face.filename).stem if face.filename else face.family
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_").upper()
    return f"OCR_{cleaned or 'UNICODE'}"


def ensure_dxf_font_style(doc, face: CadFontFace) -> str:
    """Create a DXF style with both raw filename and extended family metadata."""

    style_name = safe_style_name(face)
    if style_name not in doc.styles:
        style = doc.styles.add(style_name, font=face.filename or "txt")
    else:
        style = doc.styles.get(style_name)
        style.dxf.font = face.filename or "txt"
    style.dxf.width = 1.0
    style.dxf.oblique = 0.0
    try:
        style.set_extended_font_data(
            face.family,
            italic=False,
            bold=face.weight >= 600,
        )
    except (AttributeError, TypeError, ValueError):
        pass
    return style_name


def qfont_for_face(face: CadFontFace, pixel_size: int) -> QFont:
    font = QFont(face.family)
    font.setPixelSize(max(8, int(pixel_size)))
    try:
        font.setWeight(QFont.Weight(face.weight))
    except (TypeError, ValueError):
        pass
    strategy = QFont.StyleStrategy.PreferAntialias
    try:
        strategy |= QFont.StyleStrategy.NoFontMerging
    except AttributeError:
        pass
    font.setStyleStrategy(strategy)
    return font


def font_metric_ratios(face: CadFontFace) -> tuple[float, float]:
    metrics = QFontMetricsF(qfont_for_face(face, 1000))
    height = max(float(metrics.height()), 1.0)
    return float(metrics.ascent()) / height, float(metrics.descent()) / height


def character_advance_units(face: CadFontFace, character: str) -> float:
    if character.isspace():
        return 0.35
    metrics = QFontMetricsF(qfont_for_face(face, 1000))
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
        gray = cv2.cvtColor(
            crop,
            cv2.COLOR_BGRA2GRAY if crop.shape[2] == 4 else cv2.COLOR_BGR2GRAY,
        )
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
    font = qfont_for_face(face, max(8, int(height * 0.82)))
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
    faces = available_font_faces()
    bundled = [face for face in faces if face.bundled]
    candidates = bundled or [
        face for face in faces if face.cjk or not contains_cjk(content)
    ]
    if not candidates:
        candidates = list(faces)
    best_face = default_font_face(content)
    best_score = -1.0
    for face in candidates:
        rendered = render_font_mask(content, face, (width, height))
        score = _mask_similarity(source, rendered)
        if score > best_score:
            best_face = face
            best_score = score
    return best_face, max(0.0, float(best_score))


def _copy_font_if_needed(source: Path, target: Path) -> bool:
    if target.exists() and target.stat().st_size == source.stat().st_size:
        return False
    temporary = target.with_suffix(target.suffix + ".tmp")
    shutil.copy2(source, temporary)
    temporary.replace(target)
    return True


@lru_cache(maxsize=1)
def install_bundled_fonts_for_cad() -> FontInstallReport:
    """Install packaged fonts for the current Windows user without admin rights."""

    faces = register_bundled_fonts_for_application()
    if not faces:
        return FontInstallReport(0, 0, 0, (), False)
    if sys.platform != "win32":
        return FontInstallReport(len(faces), 0, len(faces), (), False)

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return FontInstallReport(
            len(faces),
            0,
            0,
            ("无法确定 LOCALAPPDATA，不能安装当前用户字体",),
            False,
        )

    destination = Path(local_app_data) / "Microsoft" / "Windows" / "Fonts"
    destination.mkdir(parents=True, exist_ok=True)
    installed = 0
    existing = 0
    failed: list[str] = []
    changed_paths: list[Path] = []

    try:
        import winreg

        registry_path = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            registry_path,
            0,
            winreg.KEY_SET_VALUE,
        )
    except (ImportError, OSError) as exc:
        return FontInstallReport(
            len(faces),
            0,
            0,
            (f"无法打开当前用户字体注册表：{exc}",),
            False,
        )

    try:
        for face in faces:
            source = Path(face.source_path)
            target = destination / face.filename
            try:
                changed = _copy_font_if_needed(source, target)
                value_name = face.registry_name or f"{face.family} (OpenType)"
                winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, str(target))
                if changed:
                    installed += 1
                    changed_paths.append(target)
                else:
                    existing += 1
            except OSError as exc:
                failed.append(f"{face.filename}: {exc}")
    finally:
        winreg.CloseKey(key)

    if changed_paths:
        try:
            import ctypes

            add_font = ctypes.windll.gdi32.AddFontResourceExW
            for path in changed_paths:
                add_font(str(path), 0, 0)
            result = ctypes.c_ulong()
            ctypes.windll.user32.SendMessageTimeoutW(
                0xFFFF,
                0x001D,
                0,
                0,
                0x0002,
                5000,
                ctypes.byref(result),
            )
        except (AttributeError, OSError):
            pass

    return FontInstallReport(
        len(faces),
        installed,
        existing,
        tuple(failed),
        bool(installed),
    )
