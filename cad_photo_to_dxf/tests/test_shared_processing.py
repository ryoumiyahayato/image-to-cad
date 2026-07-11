from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from app import __version__
from app.dxf_exporter import export_dxf
from app.geometry_cleaner import GeometryCleanParams
from app.line_detect import LineDetectionParams
from app.preprocess import PreprocessParams
from app.processing_service import ProcessingConfig, process_corrected_image
from app.quality import assess_image_quality
from app.reporting import build_processing_report


class SharedProcessingTests(unittest.TestCase):
    def test_shared_service_produces_unique_editable_lines_and_report(self) -> None:
        image = np.full((360, 520, 3), 255, np.uint8)
        cv2.rectangle(image, (40, 40), (480, 320), (0, 0, 0), 4)
        cv2.line(image, (80, 140), (440, 140), (0, 0, 0), 8)
        cv2.line(image, (260, 80), (260, 280), (0, 0, 0), 4)

        config = ProcessingConfig(
            preprocess=PreprocessParams(),
            detection=LineDetectionParams(
                min_line_length=30,
                use_lsd=True,
                scale_with_resolution=False,
            ),
            cleaning=GeometryCleanParams(
                min_line_length=8,
                scale_with_resolution=False,
            ),
            preserve_hatch=True,
        )
        processed = process_corrected_image(image, config)

        self.assertTrue(processed.raw_lines)
        self.assertTrue(processed.lines)
        canonical = {
            (
                round(line.x1, 5),
                round(line.y1, 5),
                round(line.x2, 5),
                round(line.y2, 5),
            )
            for line in processed.lines
        }
        self.assertEqual(len(canonical), len(processed.lines))
        self.assertTrue(all(line.length > 0 for line in processed.lines))

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "shared.dxf"
            export = export_dxf(
                processed.lines,
                output,
                processed.binary.shape[0],
                coordinate_mode="pixel_units",
            )
            report = build_processing_report(
                application_version=__version__,
                started_at_utc=datetime.now(timezone.utc).isoformat(),
                duration_seconds=0.1,
                input_path="synthetic.png",
                input_shape=image.shape,
                perspective={
                    "applied": True,
                    "automatic": False,
                    "confidence": 1.0,
                    "corners": [[0, 0], [519, 0], [519, 359], [0, 359]],
                    "target_aspect_ratio": None,
                    "corrected_shape": list(image.shape),
                },
                quality=assess_image_quality(image),
                parameters={
                    "preprocess": asdict(config.preprocess),
                    "line_detection_requested": asdict(config.detection),
                    "line_detection_effective": asdict(
                        processed.effective_detection_params
                    ),
                    "line_detection_resolution_factor": (
                        processed.detection_resolution_factor
                    ),
                    "geometry_cleaning": asdict(config.cleaning),
                },
                preprocess_stages=processed.preprocess_stages,
                debug_directory=None,
                raw_lines=processed.raw_lines,
                final_lines=processed.lines,
                geometry_report=processed.geometry_report,
                classification_report=processed.classification_report,
                auxiliary=processed.auxiliary,
                export_result=export,
                calibration_source="uncalibrated",
            )

        self.assertEqual(report["export"]["coordinate_mode"], "pixel_units")
        self.assertIsNone(report["export"]["mm_per_pixel"])
        self.assertEqual(
            report["lineage"]["final_entity_count"],
            len(processed.lines),
        )
        self.assertIn("line_detection_effective", report["parameters"])


if __name__ == "__main__":
    unittest.main()
