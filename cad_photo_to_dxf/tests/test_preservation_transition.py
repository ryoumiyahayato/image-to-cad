"""The reviewed compact transition must still detect real source loss."""

from copy import deepcopy
from dataclasses import asdict, replace
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import cv2

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
    module.verify_p10a_identity("processing-contract-page", structure)
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
    # The new contract does not excuse identity drift after counts still match.
    changed = replace(structure, straight_lines=(
        replace(structure.straight_lines[0], width=structure.straight_lines[0].width + 1),
        *structure.straight_lines[1:],
    ))
    with pytest.raises(AssertionError, match="P10-A observable structure changed"):
        module.verify_p10a_identity("processing-contract-page", changed)


def test_current_contract_rejects_an_unreviewed_algorithm(monkeypatch):
    config = replace(ProductionProcessingConfig(), algorithm_version="unreviewed")
    monkeypatch.setattr(module, "ProductionProcessingConfig", lambda: config)
    with pytest.raises(AssertionError, match="Unreviewed algorithm version"):
        module.load_current_baseline()


@pytest.mark.parametrize("name,message", [
    ("FINAL_STRUCTURE_SCHEMA_VERSION", "Unreviewed structure schema"),
    ("TRACE_CACHE_VERSION", "Unreviewed cache version"),
])
def test_current_contract_rejects_unreviewed_storage_versions(monkeypatch, name, message):
    monkeypatch.setattr(module, name, 999)
    with pytest.raises(AssertionError, match=message):
        module.load_current_baseline()


@pytest.fixture(scope="module")
def raster_sample():
    image = cv2.imread(str(ROOT / "cad_photo_to_dxf/samples/test.jpg"))
    result = ProductionProcessingService.process_page(image, ProductionProcessingConfig(enable_ocr=False))
    return image, result.final_structure


def test_reviewed_raster_transition_keeps_every_other_historical_identity_field(raster_sample):
    image, structure = raster_sample
    historical = json.loads((ROOT / "docs/refactor/preservation-baseline.json").read_text())
    baseline = module.load_current_baseline()
    module.verify_transition("sample-test", image, structure, baseline, historical)
    module.verify_p10a_identity("sample-test", structure)
    assert structure.structure_id == baseline["cases"]["sample-test"]["id"]

    # An extra point/length change is not the reviewed bbox -> source-run change.
    paths = list(structure.contours)
    index = next(i for i, path in enumerate(paths) if len(path.points) == 2)
    path = paths[index]
    paths[index] = replace(path, points=(path.points[0], (path.points[-1][0] + 1, path.points[-1][1])))
    with pytest.raises(AssertionError, match="unreviewed raster contour geometry"):
        module.verify_p10a_identity("sample-test", replace(structure, contours=tuple(paths)))

    # Counts can stay identical while a single original edge pixel disappears.
    binary = structure.contour_binary.copy()
    binary[0, 0] = 255
    with pytest.raises(AssertionError, match="unreviewed raster source mask"):
        module.verify_p10a_identity("sample-test", replace(structure, contour_binary=binary))

    # Nor can a changed source image borrow this specimen's dark-edge evidence.
    wrong_source = image.copy()
    wrong_source[0, 0] = 255
    with pytest.raises(AssertionError, match="restored edge lacks original black source"):
        module.verify_transition("sample-test", wrong_source, structure, baseline, historical)


@pytest.mark.parametrize("changes", [
    {"source_ids": ("UNREVIEWED_SOURCE",)},
    {"history": ("UNREVIEWED_HISTORY",)},
    {"confidence": 0.123},
    {"classification_confidence": 0.123},
    {"classification_reasons": ("UNREVIEWED_REASON",)},
])
def test_complete_line_ledger_rejects_lineage_drift_with_unchanged_geometry_identity(raster_sample, changes):
    image, structure = raster_sample
    changed_line = replace(structure.straight_lines[0], **changes)
    changed = replace(structure, straight_lines=(changed_line, *structure.straight_lines[1:]))
    # This limitation is explicit: the historical identity itself stays equal.
    assert changed.structure_id == structure.structure_id
    module.verify_p10a_identity("sample-test", changed)
    with pytest.raises(AssertionError, match="complete LINE source ledger changed"):
        module.verify_transition(
            "sample-test", image, changed, module.load_current_baseline(),
            json.loads((ROOT / "docs/refactor/preservation-baseline.json").read_text()),
        )


def test_raw_cache_cannot_use_loader_defaults_to_hide_missing_line_source_fields(raster_sample):
    _, structure = raster_sample
    records = [asdict(line) for line in structure.straight_lines]
    module.verify_complete_line_sources("sample-test", (), raw_records=records)
    records[0].pop("classification_confidence")
    with pytest.raises(AssertionError, match="incomplete LINE source record"):
        module.verify_complete_line_sources("sample-test", (), raw_records=records)


@pytest.mark.parametrize("mutation,message", [
    ("move", "raster HATCH differs from actual source cells"),
    ("crossed", "raster HATCH boundary is not a simple rectangle"),
    ("white", "raster HATCH display changed"),
    ("hidden", "raster HATCH display changed"),
    ("transparent", "raster HATCH display changed"),
])
def test_saved_raster_hatch_requires_exact_source_cells_not_just_same_entity_count(raster_sample, tmp_path, mutation, message):
    import ezdxf
    from app.export.trace_single_export import export_final_structure_dxf

    _, structure = raster_sample
    path = tmp_path / "reviewed-source-runs.dxf"
    export_final_structure_dxf(structure, path)
    document = ezdxf.readfile(path)
    module.verify_raster_export("sample-test", structure, document)
    hatches = list(document.modelspace().query("HATCH"))
    assert len(hatches) == 14
    # All mutations preserve entity count and source tags. A boundary's vertex
    # set also stays equal in the crossed case, but its filled area does not.
    hatch = hatches[0]
    if mutation == "move":
        for boundary in hatch.paths:
            boundary.vertices = [(x + 1, y, bulge) for x, y, bulge in boundary.vertices]
    elif mutation == "crossed":
        boundary = hatch.paths[0]
        points = boundary.vertices
        boundary.vertices = [points[i] for i in (0, 2, 1, 3)]
    elif mutation == "white":
        hatch.dxf.true_color = 0xFFFFFF
    elif mutation == "hidden":
        hatch.dxf.invisible = 1
    else:
        hatch.transparency = 1.0
    document.saveas(path)
    with pytest.raises(AssertionError, match=message):
        module.verify_raster_export("sample-test", structure, ezdxf.readfile(path))
