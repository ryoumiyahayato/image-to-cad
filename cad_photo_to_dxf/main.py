from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from app.core.offline_runtime import prepare_onnx_privacy
from app import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="图像转 CAD：原生 PDF 提取、扫描图几何与中英文文字")
    parser.add_argument("--version", action="version", version=f"Image to CAD {__version__}")
    parser.add_argument("--headless", action="store_true", help="不启动桌面窗口")
    parser.add_argument("--install-cad-fonts", action="store_true", help="为当前用户准备系统与 LibreCAD 中文字体")
    parser.add_argument("--input", type=Path, help="PDF、PNG、JPG、TIFF 或 BMP")
    parser.add_argument("--output", type=Path, default=Path("output.dxf"), help="DXF 输出路径")
    pages = parser.add_mutually_exclusive_group()
    pages.add_argument("--page", type=int, help="只转换指定页，从 1 开始")
    pages.add_argument("--all-pages", action="store_true", help="转换全部页（默认）")
    parser.add_argument("--dpi", type=float, default=300, help="扫描 DPI，默认 300；矢量 PDF 使用原页面尺寸")
    parser.add_argument("--scale", type=float, default=1, help="纸面到实际尺寸的倍数；图纸 1:100 输入 100，默认 1")
    parser.add_argument("--no-ocr", action="store_true", help="关闭扫描文字识别")
    parser.add_argument("--perspective", action="store_true", help="检测照片纸张边界并校正透视")
    parser.add_argument("--preserve-region", type=int, nargs=4, action="append", default=[],
                        metavar=("X0", "Y0", "X1", "Y1"), help="将指定扫描区域保留为独立透明图像")
    parser.add_argument("--overwrite", action="store_true", help="覆盖同名输出文件")
    parser.add_argument("--preview", type=Path, help="实际 DXF 的 PNG 预览路径，仅限单页")
    parser.add_argument("--report", type=Path, help="简明转换结果 JSON 路径")
    parser.add_argument("--verbose", action="store_true", help="显示处理进度")
    return parser


def run_headless(args) -> int:
    from app.core.conversion import convert_document
    if args.input is None:
        raise ValueError("--headless 需要 --input")

    def progress(stage, fraction):
        if args.verbose:
            print(f"[{fraction * 100:5.1f}%] {stage}", file=sys.stderr, flush=True)

    result = convert_document(
        args.input, args.output, page_number=args.page, all_pages=args.all_pages,
        dpi=args.dpi, drawing_scale=args.scale, enable_ocr=not args.no_ocr, perspective=args.perspective,
        preserve_regions=args.preserve_region, overwrite=args.overwrite,
        preview_path=args.preview, report_path=args.report, progress_callback=progress,
    )
    for page in result["outputs"]:
        print(f"DXF: {page['output']}")
        print(f"Route: {page['route']}; entities: {page.get('counts', {})}")
        if page.get("preview"):
            print(f"Preview: {page['preview']}")
    print(f"Report: {result['report']}")
    for warning in result["warnings"]:
        print(f"Warning: {warning}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    prepare_onnx_privacy()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.install_cad_fonts:
        if args.input:
            parser.error("--install-cad-fonts 请单独执行")
        try:
            if args.report and args.report.exists() and not args.overwrite:
                raise FileExistsError(f"文件已存在：{args.report}")
            from app.core.font_install import install_cad_fonts
            message = install_cad_fonts()
            print(message)
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps({"operation": "install_cad_fonts", "status": "prepared",
                                                  "message": message}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return 0
        except (ValueError, RuntimeError, OSError) as error:
            print(f"字体准备失败：{error}", file=sys.stderr)
            return 2
    if args.headless or args.input is not None:
        try:
            return run_headless(args)
        except (ValueError, FileNotFoundError, FileExistsError, RuntimeError, OSError) as error:
            print(f"转换失败：{error}", file=sys.stderr)
            return 2
    from PySide6.QtWidgets import QApplication
    from app.gui.window import MainWindow
    application = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
