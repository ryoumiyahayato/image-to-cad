from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def load_image(path: str | Path) -> np.ndarray:
    """Load an image from a path, including paths containing non-ASCII text."""
    file_path = Path(path)
    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported image type: {file_path.suffix}")
    if not file_path.exists():
        raise FileNotFoundError(file_path)

    data = np.fromfile(str(file_path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Unable to decode image: {file_path}")
    return image


def save_image(path: str | Path, image: np.ndarray) -> None:
    """Save an image to a path, including paths containing non-ASCII text."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    extension = file_path.suffix.lower() or ".png"
    ok, encoded = cv2.imencode(extension, image)
    if not ok:
        raise ValueError(f"Unable to encode image as {extension}")
    encoded.tofile(str(file_path))
