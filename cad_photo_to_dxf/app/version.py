from __future__ import annotations


PRODUCT_NAME = "Image to CAD"
__version__ = "0.3.0-dev"
PRODUCT_STATUS = "LOCAL_NO_GO"
PRODUCT_BASELINE_DATE = "2026-11-20"


def product_status_payload(mode: str = "native-objects") -> dict[str, object]:
    """Name the selected engine without turning integration into product approval."""
    if mode not in {"native-objects", "legacy"}:
        raise ValueError(f"Unknown processing engine: {mode}")
    return {
        "status": PRODUCT_STATUS,
        "design_baseline": PRODUCT_BASELINE_DATE,
        "goal": "complete_independently_editable_native_cad_objects",
        "running_pipeline": "native-objects" if mode == "native-objects" else "preserved_main_baseline",
        "native_object_entry_integrated": mode == "native-objects",
        "native_object_reconstruction_verified": False,
        "reference_geometry_counts_as_reconstruction": False,
    }
