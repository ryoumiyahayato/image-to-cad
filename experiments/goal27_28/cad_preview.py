"""Screen-only configuration of the existing ezdxf renderer.

Use the bundled LibreCAD font for its DXF alias. Never modify the document.
"""
from pathlib import Path

from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy
from ezdxf.addons.drawing.pyqt import PyQtBackend, CorrespondingDXFEntity
from ezdxf.fonts import fonts
from PySide6.QtGui import QColor, QPen, QTransform
from app.ocr.librecad_lff import (librecad_font_path, librecad_font_available,
    librecad_text_path, librecad_text_metrics)


def preview_context(doc):
    if not librecad_font_available():
        raise ValueError("LFF字体缺失：不能据替代字体预览接受修改")
    font_path = librecad_font_path()
    context = RenderContext(doc)
    face = fonts.FontFace(filename=font_path.name, family=font_path.stem)
    for style in doc.styles:
        if Path(style.dxf.font).stem.casefold() == font_path.stem.casefold():
            context.fonts[style.dxf.name.casefold()] = face
    return context


def screen_properties(entity, properties):
    # Cosmetic screen pen: the backend maps 0.25 mm * 2 / .3527 to ~1.42 px.
    # Preserve resolved color, visibility, geometry and relative heavier weights.
    properties.lineweight = max(.25, properties.lineweight)


class ReviewFrontend(Frontend):
    """Reuse the application's existing LFF paths; geometry stays in ezdxf."""
    def __init__(self, context, backend, scene, config):
        super().__init__(context, backend, config=config)
        self.scene = scene

    def draw_text_entity(self, entity, properties):
        if properties.font is None or properties.font.filename != librecad_font_path().name:
            raise ValueError("该字体未由本预览核验，须先实际CAD核验")
        if (entity.dxftype() != "TEXT" or entity.dxf.get("halign", 0)
                or entity.dxf.get("valign", 0) or entity.dxf.get("oblique", 0)
                or entity.dxf.get("text_generation_flag", 0)
                or "%%" in entity.dxf.text
                or tuple(entity.dxf.get("extrusion", (0, 0, 1))) != (0, 0, 1)):
            raise ValueError("该TEXT布局未由LFF预览支持，须先实际CAD核验")
        metrics = librecad_text_metrics(entity.dxf.text)
        if metrics.fallback_glyph_count:
            raise ValueError("LFF缺少字符，须先实际CAD核验")
        matrix = QTransform()
        matrix.translate(entity.dxf.insert.x, entity.dxf.insert.y)
        matrix.rotate(entity.dxf.get("rotation", 0))
        matrix.scale(entity.dxf.height / metrics.em_height * entity.dxf.get("width", 1), -entity.dxf.height / metrics.em_height)
        color = QColor(properties.color[:7])
        if len(properties.color) == 9:
            color.setAlpha(int(properties.color[7:9], 16))
        pen = QPen(color, properties.lineweight * 2 / .3527)
        pen.setCosmetic(True)
        item = self.scene.addPath(matrix.map(librecad_text_path(entity.dxf.text)), pen)
        item.setData(CorrespondingDXFEntity, entity)

    def draw_mtext_entity(self, entity, properties):
        raise ValueError("MTEXT尚未由本预览核验，须先实际CAD核验")


def draw_current_cad(doc, scene):
    context = preview_context(doc)
    config = Configuration(background_policy=BackgroundPolicy.BLACK, lineweight_scaling=2.)
    frontend = ReviewFrontend(context, PyQtBackend(scene), scene, config)
    frontend.push_property_override_function(screen_properties)
    frontend.draw_layout(doc.modelspace(), finalize=True)
    return context
