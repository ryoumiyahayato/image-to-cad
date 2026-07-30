from __future__ import annotations

from collections import defaultdict

import cv2
import numpy as np

from app.processing_contract import (
    ProductionProcessingConfig,
    ProductionProcessingService,
)


CORE_PERFORMANCE_STAGES = {
    "background_normalization",
    "binarization",
    "ocr",
    "structural_line_detection",
    "roi_generation",
    "connectivity",
    "ownership",
    "contour_tracing",
    "final_structure_generation",
}


def _sample_page() -> np.ndarray:
    image = np.full((240, 320, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (24, 24), (296, 216), (0, 0, 0), 2)
    cv2.line(image, (24, 120), (296, 120), (0, 0, 0), 2)
    cv2.line(image, (160, 24), (160, 216), (0, 0, 0), 2)
    cv2.putText(
        image,
        "A1",
        (44, 88),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 0, 0),
        1,
        cv2.LINE_AA,
    )
    return image


def test_performance_callback_is_complete_and_content_neutral() -> None:
    image = _sample_page()
    config = ProductionProcessingConfig(enable_ocr=False, source_dpi=150.0)
    without_observation = ProductionProcessingService.process_page(
        image,
        config,
    )
    durations: dict[str, float] = defaultdict(float)

    def collect(stage: str, seconds: float) -> None:
        durations[stage] += seconds

    with_observation = ProductionProcessingService.process_page(
        image,
        config,
        performance_callback=collect,
    )

    assert with_observation.final_structure is not None
    assert without_observation.final_structure is not None
    assert (
        with_observation.final_structure.structure_id
        == without_observation.final_structure.structure_id
    )
    assert CORE_PERFORMANCE_STAGES <= durations.keys()
    assert all(value >= 0.0 for value in durations.values())
    assert durations["ocr"] == 0.0


def test_performance_callback_accepts_repeated_stage_samples() -> None:
    image = _sample_page()
    config = ProductionProcessingConfig(enable_ocr=False)
    samples: dict[str, list[float]] = defaultdict(list)

    ProductionProcessingService.process_page(
        image,
        config,
        performance_callback=lambda stage, seconds: samples[stage].append(
            seconds
        ),
    )

    assert len(samples["final_structure_generation"]) == 2
    assert samples["contour_tracing"]
