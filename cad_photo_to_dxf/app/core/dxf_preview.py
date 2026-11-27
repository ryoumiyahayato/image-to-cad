"""Render the saved DXF with its companion fonts and images."""
from __future__ import annotations
from pathlib import Path
import threading

_RENDER_LOCK = threading.Lock()


def render_dxf(dxf_path, png_path, *, max_dimension=1600) -> Path:
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext, config, layout
    from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend
    from ezdxf.fonts import fonts

    source, output = Path(dxf_path).resolve(), Path(png_path).resolve()
    with _RENDER_LOCK:
        document = ezdxf.readfile(source)
        font_folders = {source.parent}
        for style in document.styles:
            filename = style.dxf.get("font", "")
            if filename:
                candidate = Path(filename)
                if not candidate.is_absolute():
                    candidate = source.parent / candidate
                if candidate.is_file():
                    font_folders.add(candidate.parent)
                    # ezdxf resolves registered fonts by basename, not by a
                    # relative DXF resource path. Change only this preview.
                    style.dxf.font = candidate.name
        for folder in font_folders:
            fonts.font_manager.scan_folder(folder)
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
        class ImageFrameFrontend(Frontend):
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
            document.modelspace(), finalize=True
        )
        pixels = backend.get_pixmap_bytes(
            layout.Page(0, 0, margins=layout.Margins.all(3), max_width=254, max_height=254),
            dpi=max(48, int(max_dimension / 10)),
        )
        if not pixels:
            raise RuntimeError("DXF preview rendering produced an empty image")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(pixels)
    return output
