from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import atan, atan2, ceil, cos, hypot, pi, sin
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from PySide6.QtCore import QPointF
from PySide6.QtGui import QFont, QFontMetricsF, QPainterPath


LIBRECAD_FONT_FAMILY = "wqy-unicode"
LIBRECAD_FONT_FILENAME = "wqy-unicode.lff"
LIBRECAD_STYLE_NAME = "wqy-unicode"
_LFF_EM_HEIGHT = 9.0
_GLYPH_HEADER = re.compile(rb"^\[([0-9A-Fa-f]+)\]")


@dataclass(frozen=True)
class LffVertex:
    x: float
    y: float
    bulge: float = 0.0


@dataclass(frozen=True)
class LffGlyph:
    strokes: tuple[tuple[LffVertex, ...], ...]
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    advance: float


@dataclass(frozen=True)
class LibreCadFontInstallReport:
    available: bool
    installed: int
    already_installed: int
    destinations: tuple[str, ...]
    failed: tuple[str, ...]
    elevation_started: bool = False

    @property
    def ready(self) -> bool:
        return self.available and bool(self.installed or self.already_installed)

    def summary(self) -> str:
        if not self.available:
            return "安装包中缺少 LibreCAD 中文 LFF 字体。"
        if self.elevation_started:
            return "已请求管理员权限安装 LibreCAD 中文字体；完成后请完全退出并重新启动 LibreCAD。"
        if self.ready:
            count = self.installed + self.already_installed
            return f"LibreCAD 中文 LFF 字体已就绪：{count} 个字体目录。请重新启动 LibreCAD。"
        if self.failed:
            return "LibreCAD 中文字体尚未安装：" + "；".join(self.failed)
        return "未检测到 LibreCAD 字体目录。请先安装或启动 LibreCAD，再点击修复。"


def _application_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(str(frozen_root))
    return Path(__file__).resolve().parents[1]


def librecad_font_path() -> Path:
    return _application_root() / "resources" / "fonts" / LIBRECAD_FONT_FILENAME


def librecad_font_available() -> bool:
    path = librecad_font_path()
    return path.exists() and path.stat().st_size >= 10_000_000


class LffFont:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.letter_spacing = 1.0
        self.word_spacing = 5.0
        self._offsets: dict[int, int] = {}
        self._glyphs: dict[int, LffGlyph | None] = {}
        self._indexed = False

    def _build_index(self) -> None:
        if self._indexed:
            return
        self._indexed = True
        if not self.path.exists():
            return
        try:
            with self.path.open("rb") as handle:
                while True:
                    line = handle.readline()
                    if not line:
                        break
                    stripped = line.strip()
                    if stripped.startswith(b"# LetterSpacing:"):
                        try:
                            self.letter_spacing = float(stripped.split(b":", 1)[1])
                        except (ValueError, IndexError):
                            pass
                    elif stripped.startswith(b"# WordSpacing:"):
                        try:
                            self.word_spacing = float(stripped.split(b":", 1)[1])
                        except (ValueError, IndexError):
                            pass
                    match = _GLYPH_HEADER.match(stripped)
                    if match is not None:
                        self._offsets[int(match.group(1), 16)] = handle.tell()
        except OSError:
            self._offsets.clear()

    @staticmethod
    def _parse_stroke(line: str) -> tuple[LffVertex, ...]:
        vertices: list[LffVertex] = []
        for token in line.split(";"):
            value = token.strip()
            if not value:
                continue
            parts = [item.strip() for item in value.split(",")]
            if len(parts) < 2:
                continue
            try:
                x_value = float(parts[0])
                y_value = float(parts[1])
            except ValueError:
                continue
            bulge = 0.0
            if len(parts) >= 3 and parts[2].upper().startswith("A"):
                try:
                    bulge = float(parts[2][1:])
                except ValueError:
                    bulge = 0.0
            vertices.append(LffVertex(x_value, y_value, bulge))
        return tuple(vertices)

    def glyph(self, character: str) -> LffGlyph | None:
        if not character:
            return None
        codepoint = ord(character[0])
        if codepoint in self._glyphs:
            return self._glyphs[codepoint]
        self._build_index()
        offset = self._offsets.get(codepoint)
        if offset is None:
            self._glyphs[codepoint] = None
            return None

        strokes: list[tuple[LffVertex, ...]] = []
        try:
            with self.path.open("rb") as handle:
                handle.seek(offset)
                while True:
                    position = handle.tell()
                    line = handle.readline()
                    if not line:
                        break
                    stripped = line.strip()
                    if _GLYPH_HEADER.match(stripped) is not None:
                        handle.seek(position)
                        break
                    if not stripped or stripped.startswith(b"#"):
                        continue
                    stroke = self._parse_stroke(stripped.decode("utf-8", errors="ignore"))
                    if stroke:
                        strokes.append(stroke)
        except OSError:
            self._glyphs[codepoint] = None
            return None

        points = [vertex for stroke in strokes for vertex in stroke]
        if not points:
            self._glyphs[codepoint] = None
            return None
        min_x = min(point.x for point in points)
        min_y = min(point.y for point in points)
        max_x = max(point.x for point in points)
        max_y = max(point.y for point in points)
        advance = max(max_x, 0.0) - min(min_x, 0.0) + self.letter_spacing
        glyph = LffGlyph(tuple(strokes), min_x, min_y, max_x, max_y, max(advance, 1.0))
        self._glyphs[codepoint] = glyph
        return glyph


@lru_cache(maxsize=1)
def _font() -> LffFont:
    return LffFont(librecad_font_path())


def _arc_points(start: LffVertex, end: LffVertex) -> tuple[tuple[float, float], ...]:
    bulge = float(end.bulge)
    if abs(bulge) < 1e-9:
        return ((end.x, end.y),)
    dx = end.x - start.x
    dy = end.y - start.y
    chord = hypot(dx, dy)
    if chord < 1e-9:
        return ((end.x, end.y),)
    theta = 4.0 * atan(bulge)
    midpoint_x = (start.x + end.x) * 0.5
    midpoint_y = (start.y + end.y) * 0.5
    perpendicular_x = -dy / chord
    perpendicular_y = dx / chord
    center_distance = chord * (1.0 - bulge * bulge) / (4.0 * bulge)
    center_x = midpoint_x + perpendicular_x * center_distance
    center_y = midpoint_y + perpendicular_y * center_distance
    radius = hypot(start.x - center_x, start.y - center_y)
    start_angle = atan2(start.y - center_y, start.x - center_x)
    segment_count = max(4, int(ceil(abs(theta) / (pi / 18.0))))
    points: list[tuple[float, float]] = []
    for index in range(1, segment_count + 1):
        angle = start_angle + theta * index / segment_count
        points.append((center_x + radius * cos(angle), center_y + radius * sin(angle)))
    return tuple(points)


def _append_glyph_path(path: QPainterPath, glyph: LffGlyph, offset_x: float) -> None:
    for stroke in glyph.strokes:
        if not stroke:
            continue
        first = stroke[0]
        path.moveTo(QPointF(offset_x + first.x, -first.y))
        previous = first
        for current in stroke[1:]:
            for x_value, y_value in _arc_points(previous, current):
                path.lineTo(QPointF(offset_x + x_value, -y_value))
            previous = current


def _fallback_glyph_path(path: QPainterPath, offset_x: float) -> None:
    width = 7.0
    height = 9.0
    path.moveTo(offset_x + width * 0.5, -height)
    path.lineTo(offset_x + width, -height * 0.5)
    path.lineTo(offset_x + width * 0.5, 0.0)
    path.lineTo(offset_x, -height * 0.5)
    path.closeSubpath()


def librecad_text_path(text: str) -> QPainterPath:
    """Return the exact LibreCAD LFF stroke path used by the exported TEXT style."""

    content = str(text or "")
    path = QPainterPath()
    cursor = 0.0
    font = _font()
    for character in content:
        if character.isspace():
            cursor += max(font.word_spacing, 3.0)
            continue
        glyph = font.glyph(character)
        if glyph is None:
            _fallback_glyph_path(path, cursor)
            cursor += 8.0
            continue
        _append_glyph_path(path, glyph, cursor - min(glyph.min_x, 0.0))
        cursor += glyph.advance
    return path


def librecad_character_advance_units(character: str) -> float:
    if character.isspace():
        return 0.5
    glyph = _font().glyph(character)
    if glyph is None:
        return 1.0 if ord(character) >= 0x2E80 else 0.65
    value = glyph.advance / _LFF_EM_HEIGHT
    return max(0.20, min(value, 2.0))


def librecad_metric_ratios() -> tuple[float, float]:
    return 0.94, 0.06


def ensure_librecad_dxf_style(doc) -> str:
    """Create the lowercase LFF style name LibreCAD resolves without substitution."""

    if LIBRECAD_STYLE_NAME not in doc.styles:
        style = doc.styles.add(LIBRECAD_STYLE_NAME, font=LIBRECAD_FONT_FILENAME)
    else:
        style = doc.styles.get(LIBRECAD_STYLE_NAME)
        style.dxf.font = LIBRECAD_FONT_FILENAME
    style.dxf.width = 1.0
    style.dxf.oblique = 0.0
    return LIBRECAD_STYLE_NAME


def _running_librecad_executables() -> tuple[Path, ...]:
    if sys.platform != "win32":
        return ()
    command = (
        "Get-CimInstance Win32_Process -Filter \"name='librecad.exe'\" | "
        "ForEach-Object { $_.ExecutablePath }"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    return tuple(
        Path(line.strip())
        for line in completed.stdout.splitlines()
        if line.strip().casefold().endswith("librecad.exe")
    )


def _registry_librecad_roots() -> tuple[Path, ...]:
    if sys.platform != "win32":
        return ()
    try:
        import winreg
    except ImportError:
        return ()
    roots: list[Path] = []
    hives = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    subkeys = (
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
        r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    )
    for hive in hives:
        for subkey in subkeys:
            try:
                key = winreg.OpenKey(hive, subkey)
            except OSError:
                continue
            try:
                for index in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        child_name = winreg.EnumKey(key, index)
                        child = winreg.OpenKey(key, child_name)
                        display_name = str(winreg.QueryValueEx(child, "DisplayName")[0])
                        if "librecad" not in display_name.casefold():
                            winreg.CloseKey(child)
                            continue
                        try:
                            location = str(winreg.QueryValueEx(child, "InstallLocation")[0]).strip()
                        except OSError:
                            location = ""
                        if location:
                            roots.append(Path(location))
                        winreg.CloseKey(child)
                    except OSError:
                        continue
            finally:
                winreg.CloseKey(key)
    return tuple(roots)


def find_librecad_font_directories() -> tuple[Path, ...]:
    roots: list[Path] = []
    for executable in _running_librecad_executables():
        roots.append(executable.parent)
    executable = shutil.which("librecad.exe")
    if executable:
        roots.append(Path(executable).parent)
    roots.extend(_registry_librecad_roots())
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        value = os.environ.get(variable)
        if not value:
            continue
        base = Path(value)
        roots.extend(base.glob("LibreCAD*"))
        roots.extend((base / "Programs").glob("LibreCAD*"))

    candidates: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        for candidate in (
            root / "resources" / "fonts",
            root / "fonts",
            root.parent / "resources" / "fonts",
        ):
            key = str(candidate.resolve(strict=False)).casefold()
            if key in seen:
                continue
            seen.add(key)
            if candidate.exists() and candidate.is_dir():
                candidates.append(candidate)
    return tuple(candidates)


def _copy_if_needed(source: Path, target: Path) -> bool:
    if target.exists() and target.stat().st_size == source.stat().st_size:
        return False
    temporary = target.with_suffix(target.suffix + ".tmp")
    shutil.copy2(source, temporary)
    temporary.replace(target)
    return True


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _request_elevated_copy(source: Path, destinations: tuple[Path, ...]) -> bool:
    if sys.platform != "win32" or not destinations:
        return False
    commands = []
    for directory in destinations:
        target = directory / LIBRECAD_FONT_FILENAME
        commands.append(
            f"New-Item -ItemType Directory -Force -Path {_powershell_quote(str(directory))} | Out-Null; "
            f"Copy-Item -LiteralPath {_powershell_quote(str(source))} "
            f"-Destination {_powershell_quote(str(target))} -Force"
        )
    command = "; ".join(commands)
    try:
        import ctypes

        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "powershell.exe",
            f"-NoProfile -ExecutionPolicy Bypass -Command {_powershell_quote(command)}",
            None,
            1,
        )
        return int(result) > 32
    except (AttributeError, OSError, ValueError):
        return False


def install_librecad_font(*, request_elevation: bool = False) -> LibreCadFontInstallReport:
    source = librecad_font_path()
    if not librecad_font_available():
        return LibreCadFontInstallReport(False, 0, 0, (), (str(source),))
    if sys.platform != "win32":
        return LibreCadFontInstallReport(True, 0, 0, (), ("仅 Windows 自动安装 LibreCAD 字体",))

    directories = find_librecad_font_directories()
    installed = 0
    existing = 0
    failed: list[str] = []
    permission_denied: list[Path] = []
    for directory in directories:
        target = directory / LIBRECAD_FONT_FILENAME
        try:
            changed = _copy_if_needed(source, target)
            if changed:
                installed += 1
            else:
                existing += 1
        except PermissionError:
            permission_denied.append(directory)
        except OSError as exc:
            failed.append(f"{directory}: {exc}")

    elevation_started = False
    if request_elevation and permission_denied:
        elevation_started = _request_elevated_copy(source, tuple(permission_denied))
        if not elevation_started:
            failed.extend(f"{directory}: 需要管理员权限" for directory in permission_denied)
    elif permission_denied:
        failed.extend(f"{directory}: 需要管理员权限" for directory in permission_denied)

    return LibreCadFontInstallReport(
        True,
        installed,
        existing,
        tuple(str(path) for path in directories),
        tuple(failed),
        elevation_started,
    )


def fallback_text_path(text: str, pixel_size: int = 100) -> QPainterPath:
    """Fallback only for development environments where the large LFF is absent."""

    font = QFont("Noto Sans CJK SC")
    font.setPixelSize(max(8, int(pixel_size)))
    metrics = QFontMetricsF(font)
    path = QPainterPath()
    path.addText(QPointF(0.0, float(metrics.ascent())), font, text)
    return path


def preview_text_path(text: str) -> QPainterPath:
    if librecad_font_available():
        return librecad_text_path(text)
    return fallback_text_path(text)
