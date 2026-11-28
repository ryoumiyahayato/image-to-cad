"""Render the saved DXF with its companion fonts and images."""
from __future__ import annotations
from pathlib import Path
import threading

_RENDER_LOCK = threading.Lock()


def resolve_drawing_fonts(document, folder):
    """Resolve portable DXF styles identically for preview and text measurement."""
    from ezdxf.fonts import fonts

    folders = {folder}
    for style in document.styles:
        filename = style.dxf.get("font", "")
        if filename:
            candidate = folder / filename
            if candidate.is_file():
                folders.add(candidate.parent)
                style.dxf.font = candidate.name
    for path in folders:
        fonts.font_manager.scan_folder(path)


def render_dxf(dxf_path, png_path, *, max_dimension=1600) -> Path:
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext, config, layout
    from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend
    from ezdxf.math import BoundingBox2d

    source, output = Path(dxf_path).resolve(), Path(png_path).resolve()
    with _RENDER_LOCK:
        document = ezdxf.readfile(source)
        resolve_drawing_fonts(document, source.parent)
        # Resolve paths in this in-memory view; the DXF stays portable.
        for definition in document.objects.query("IMAGEDEF"):
            filename = Path(definition.dxf.filename)
            if not filename.is_absolute():
                definition.dxf.filename = str(source.parent / filename)
        backend = PyMuPdfBackend()
        configuration = config.Configuration(
            background_policy=config.BackgroundPolicy.WHITE,
            color_policy=config.ColorPolicy.COLOR,
        )
        hidden = {layer.dxf.name.casefold() for layer in document.layers
                  if layer.is_off() or layer.is_frozen()}
        hidden.add("review_source")

        class ImageFrameFrontend(Frontend):
            def override_properties(self, entity, properties):
                if properties.layer.casefold() in hidden:
                    properties.is_visible = False

            def draw_image_entity(self, entity, properties):
                variables = entity.doc.rootdict.get("ACAD_IMAGE_VARS")
                if variables is None or variables.dxf.frame != 0:
                    return super().draw_image_entity(entity, properties)
                # ezdxf 1.4.5 draws an IMAGE boundary even with IMAGEFRAME=0.
                # Honour that saved setting while rendering the image pixels.
                draw_lines = self.pipeline.draw_solid_lines
                self.pipeline.draw_solid_lines = lambda *args, **kwargs: None
                try:
                    return super().draw_image_entity(entity, properties)
                finally:
                    self.pipeline.draw_solid_lines = draw_lines

        ImageFrameFrontend(RenderContext(document), backend, configuration).draw_layout(
            document.modelspace(), finalize=True,
        )
        # A source-only drawing has no visible extents. Give it a blank paper
        # viewport so the renderer never derives a NaN scale from an empty box.
        bounds = backend.player().bbox()
        if not bounds.has_data:
            bounds = BoundingBox2d([(0, 0), (210, 297)])
        pixels = backend.get_pixmap_bytes(
            layout.Page(0, 0, margins=layout.Margins.all(3), max_width=254, max_height=254),
            dpi=max(48, int(max_dimension / 10)), render_box=bounds,
        )
        if not pixels:
            raise RuntimeError("DXF preview rendering produced an empty image")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(pixels)
    return output
