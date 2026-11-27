"""Install the bundled complete Chinese fonts for the current user."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


def _copy_font(source: Path, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() == source.read_bytes():
            return
        raise FileExistsError(f"已有同名字体内容不同，请先自行处理：{destination}")
    shutil.copyfile(source, destination)


def install_cad_fonts() -> str:
    from PySide6.QtCore import QStandardPaths

    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    resources = base / "resources" / "fonts"
    otf = resources / "NotoSansCJKsc-Regular.otf"
    lff = resources / "wqy-unicode.lff"
    for source in (otf, lff):
        if not source.is_file():
            raise FileNotFoundError(f"缺少完整字体资源：{source.name}；请使用完整软件包。")
    if sys.platform == "win32":
        import ctypes
        import winreg
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise RuntimeError("无法找到当前用户的字体目录")
        font_folder = Path(local) / "Microsoft" / "Windows" / "Fonts"
        destination = font_folder / otf.name
        _copy_font(otf, destination)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows NT\CurrentVersion\Fonts") as key:
            winreg.SetValueEx(key, "Noto Sans CJK SC Regular (OpenType)", 0,
                             winreg.REG_SZ, str(destination))
        ctypes.windll.gdi32.AddFontResourceW(str(destination))
        ctypes.windll.user32.SendNotifyMessageW(0xFFFF, 0x001D, 0, 0)
    elif sys.platform == "darwin":
        font_folder = Path.home() / "Library" / "Fonts"
        _copy_font(otf, font_folder / otf.name)
    else:
        font_folder = Path.home() / ".local" / "share" / "fonts" / "image-to-cad"
        _copy_font(otf, font_folder / otf.name)
        command = shutil.which("fc-cache")
        if command:
            subprocess.run([command, "-f", str(font_folder)], timeout=30, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if sys.platform in {"win32", "darwin"}:
        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        if not documents:
            raise RuntimeError("系统字体已准备；无法找到 LibreCAD 用户文档目录")
        cad_folder = Path(documents) / "librecad" / "fonts"
    else:
        cad_folder = Path.home() / ".librecad" / "fonts"
    _copy_font(lff, cad_folder / lff.name)
    for filename in ("OFL-1.1.txt", "WQY-LICENSE-Apache-2.0.txt"):
        license_file = resources / filename
        if license_file.is_file():
            shutil.copyfile(license_file, (cad_folder if "WQY" in filename else font_folder) / filename)
    return (f"已准备系统中文字体：{font_folder}\nLibreCAD 字体：{cad_folder}\n\n"
            "请完全退出并重新打开 CAD，再检查文字显示。分发图纸时请保留 DXF 旁的 fonts 和图片目录。")
