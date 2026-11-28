"""Full-page geometry residuals for the CLI and desktop review."""
from pathlib import Path
from tempfile import NamedTemporaryFile


MISSING_COLOR = (212, 72, 37)
EXTRA_COLOR = (21, 86, 194)


def scan_residual_path(output):
    output = Path(output)
    return output.parent / (output.stem + "_assets") / "geometry-residual.png"


def describe_geometry_residuals(geometry):
    def describe(count, total):
        ratio = f" ({count / total:.2%})" if total else ""
        return f"{count:,} px{ratio}"

    missing = describe(geometry["missing_pixels"], geometry["source_pixels"])
    extra = describe(geometry["extra_pixels"], geometry["drawn_pixels"])
    return missing, extra


def save_geometry_residuals(output, image, missing, extra):
    """Store the difference at source resolution against a faded source image."""
    import cv2
    import numpy as np
    from PIL import Image

    # Reserve two palette entries for exact residual pixels.
    gray_indices = np.minimum(np.arange(256), 253).astype(np.uint8)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    pixels = cv2.LUT(gray, gray_indices)
    pixels[missing != 0] = 254
    pixels[extra != 0] = 255
    overlay = Image.fromarray(pixels)
    palette = [channel for value in np.linspace(170, 255, 254, dtype=int)
               for channel in (value, value, value)]
    overlay.putpalette([*palette, *MISSING_COLOR, *EXTRA_COLOR])
    path = scan_residual_path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as buffer:
        temporary = Path(buffer.name)
    try:
        overlay.save(temporary, format="PNG")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
