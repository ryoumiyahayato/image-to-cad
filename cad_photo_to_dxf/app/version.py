from __future__ import annotations


PRODUCT_NAME = "Image to CAD"
__version__ = "0.3.0-dev"
PRODUCT_STATUS = "LOCAL_NO_GO"
PRODUCT_BASELINE_DATE = "2026-11-20"


def product_status_payload() -> dict[str, object]:
    """Describe the shipped entry, without promoting unmerged research to support."""
    return {
        "status": PRODUCT_STATUS,
        "design_baseline": PRODUCT_BASELINE_DATE,
        "goal": "complete_independently_editable_native_cad_objects",
        "running_pipeline": "preserved_main_baseline",
        "native_object_reconstruction_verified": False,
        "reference_geometry_counts_as_reconstruction": False,
    }
