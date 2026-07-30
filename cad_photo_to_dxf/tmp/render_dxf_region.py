from __future__ import annotations

import argparse
from pathlib import Path

import ezdxf
from ezdxf.addons.drawing import Frontend, RenderContext, layout, svg
from ezdxf.math import BoundingBox2d, Vec2
from PySide6.QtCore import QByteArray, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--box", nargs=4, type=float, metavar=("XMIN", "YMIN", "XMAX", "YMAX"))
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1000)
    args = parser.parse_args()

    doc = ezdxf.readfile(args.input)
    backend = svg.SVGBackend()
    Frontend(RenderContext(doc), backend).draw_layout(doc.modelspace())

    render_box = None
    if args.box is not None:
        xmin, ymin, xmax, ymax = args.box
        render_box = BoundingBox2d([Vec2(xmin, ymin), Vec2(xmax, ymax)])

    page = layout.Page(args.width, args.height, units=layout.Units.px)
    settings = layout.Settings(
        fit_page=True,
        crop_at_margins=True,
        min_stroke_width=0.35,
        fixed_stroke_width=0.0,
        output_layers=False,
    )
    svg_bytes = backend.get_string(page, settings=settings, render_box=render_box).encode("utf-8")

    image = QImage(args.width, args.height, QImage.Format.Format_ARGB32)
    image.fill(QColor("black"))
    painter = QPainter(image)
    QSvgRenderer(QByteArray(svg_bytes)).render(
        painter,
        QRectF(0, 0, args.width, args.height),
    )
    painter.end()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(args.output)):
        raise RuntimeError(f"failed to save {args.output}")


if __name__ == "__main__":
    main()
