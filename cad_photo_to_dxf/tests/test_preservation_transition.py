"""The reviewed compact transition must still detect real source loss."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.processing import ProductionProcessingConfig, ProductionProcessingService
from tests.test_processing_contract import _page


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("compact_preservation", ROOT / "maintenance/preservation_check.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_current_transition_keeps_historical_records_and_source_obligations():
    historical = json.loads((ROOT / "docs/refactor/preservation-baseline.json").read_text())
    baseline = module.load_current_baseline()
    assert historical["processing-contract-page"]["members"]["straight_lines"] == 21
    assert historical["reconciliation-gap-junction"]["members"]["straight_lines"] == 12
    image = _page()
    result = ProductionProcessingService.process_page(image, ProductionProcessingConfig(enable_ocr=False))
    structure = result.final_structure
    module.verify_transition("processing-contract-page", image, structure, baseline, historical)
    assert len(structure.straight_lines) == 14
    # Removing an independent retained boundary cannot be accepted as this transition.
    incomplete = SimpleNamespace(straight_lines=structure.straight_lines[1:])
    with pytest.raises(AssertionError, match="unaccounted"):
        module.verify_transition("processing-contract-page", image, incomplete, baseline, historical)
    # Nor may an old observation be declared redundant against a different physical side.
    wrong = deepcopy(baseline)
    wrong["transition"]["processing-contract-page"][0]["keeper"] = [
        structure.straight_lines[0].x1, structure.straight_lines[0].y1,
        structure.straight_lines[0].x2, structure.straight_lines[0].y2,
    ]
    with pytest.raises(AssertionError):
        module.verify_transition("processing-contract-page", image, structure, wrong, historical)
