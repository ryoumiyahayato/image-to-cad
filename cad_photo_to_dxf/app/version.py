from __future__ import annotations


PRODUCT_NAME = "Image to CAD"
__version__ = "0.4.0-dev"
PRODUCT_STATUS = "DEVELOPMENT"
PRODUCT_BASELINE_DATE = "2026-11-28"


def product_status_payload() -> dict[str, object]:
    """Describe supported routes without certifying untested drawings."""
    return {
        "status": PRODUCT_STATUS,
        "design_baseline": PRODUCT_BASELINE_DATE,
        "running_pipeline": "auto",
        "routes": ["vector_pdf", "scan", "scan_pdf"],
        "text": "editable_chinese_english_lines",
        "unmodelled_ink": "transparent_image_for_review",
        "coordinate_units": "paper_mm",
        "engineering_scale": "requires_known_dimension",
    }
