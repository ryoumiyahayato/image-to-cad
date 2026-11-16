from __future__ import annotations

from dataclasses import replace
import json

import pytest

from app.core.processing import ProductionProcessingConfig, build_processing_cache_key
from main import build_parser, run_headless


def selection_manifest():
    return {
        "version": "explicit-native-source-region-selection-v1",
        "input": {"pixels_sha256": "a" * 64, "shape_yx": [12, 12], "dtype": "uint8", "dpi": 100.0},
        "original": {"pixels_sha256": "b" * 64, "shape_yx": [24, 24], "dtype": "uint8", "dpi": 200.0},
        "crop_work_px": [0, 0, 12, 12],
        "native_scale": 2,
        "prepared_window": {"origin_work_px": [2, 2], "shape_yx": [8, 8], "pixels_sha256": "c" * 64, "dtype": "uint8"},
        "selection": {
            "id": "synthetic-selection",
            "working_parent_runs_y_x0_x1": [[1, 1, 3], [2, 1, 3]],
            "native_member_runs_y_x0_x1": [[2, 2, 3]],
        },
    }


def cache_key(config):
    return build_processing_cache_key(input_content_sha256="d" * 64, page_index=0, config=config)


def test_source_region_off_adds_no_config_or_cache_fields():
    original = ProductionProcessingConfig(source_dpi=100, enable_ocr=False)
    explicit_off = replace(original, experimental_native_source_region_manifest=None)
    assert original == explicit_off
    assert cache_key(original) == cache_key(explicit_off)
    assert not any("source_region" in key for key in original.payload())


def test_source_region_cache_binds_content_and_ignores_json_layout():
    original = ProductionProcessingConfig(source_dpi=100, enable_ocr=False)
    manifest = selection_manifest()
    selected = replace(original, experimental_native_source_region_manifest=json.dumps(manifest))
    reformatted = replace(original, experimental_native_source_region_manifest=json.dumps(manifest, indent=4, sort_keys=True))
    assert selected == reformatted
    assert cache_key(selected) == cache_key(reformatted)
    assert cache_key(selected) != cache_key(original)
    extra = selected.payload().keys() - original.payload().keys()
    assert extra == {
        "experimental_native_source_region_manifest", "native_source_region_version",
        "native_source_region_selection_sha256",
    }
    assert {key: selected.payload()[key] for key in original.payload()} == original.payload()
    manifest["selection"]["native_member_runs_y_x0_x1"] = [[2, 3, 4]]
    other = replace(selected, experimental_native_source_region_manifest=json.dumps(manifest))
    assert cache_key(other) != cache_key(selected)
    # A caller changing a returned JSON payload cannot mutate the frozen config.
    payload = selected.payload()
    payload["experimental_native_source_region_manifest"]["selection"]["id"] = "changed"
    assert selected.payload()["experimental_native_source_region_manifest"]["selection"]["id"] == "synthetic-selection"


@pytest.mark.parametrize("options", [
    {"experimental_compound_strokes": True},
    {"experimental_pdf_native_text": "matched"},
    {"experimental_pdf_native_geometry": True},
])
def test_source_region_rejects_conflicting_routes(options):
    with pytest.raises(ValueError):
        ProductionProcessingConfig(
            experimental_native_source_region_manifest=json.dumps(selection_manifest()), **options,
        )


@pytest.mark.parametrize("args", [
    ["--input", "drawing.png"],
    ["--input", "drawing.png", "--source-dpi", "100"],
    ["--input", "drawing.pdf", "--source-dpi", "100"],
])
def test_source_region_cli_requires_registered_raster_before_io(args):
    parsed = build_parser().parse_args([
        "--headless", *args, "--experimental-native-source-region-manifest", "missing.json",
    ])
    with pytest.raises(ValueError, match="Source region selection requires"):
        run_headless(parsed)


def test_source_region_cli_parses_explicit_path_and_rejects_oversized_file(tmp_path):
    from app.geometry.source_region_selection import MAX_MANIFEST_BYTES

    path = tmp_path / "selection.json"
    path.write_bytes(b" " * (MAX_MANIFEST_BYTES + 1))
    parsed = build_parser().parse_args([
        "--headless", "--input", "missing.png", "--source-dpi", "100",
        "--original-scan", "missing.tiff",
        "--experimental-native-source-region-manifest", str(path),
    ])
    assert parsed.experimental_native_source_region_manifest == path
    with pytest.raises(ValueError, match="byte budget"):
        run_headless(parsed)


@pytest.mark.parametrize("records", [
    [{"native_source_region_partition": True}],
    [{"native_source_region_partition": True, "contour_index": True}],
    [{"native_source_region_partition": True, "contour_index": 1}],
    [{"native_source_region_partition": True, "contour_index": 0}, {"contour_index": 0}],
])
def test_shared_writer_rejects_bad_region_index_before_any_entities(records, tmp_path):
    import ezdxf
    from app.core.trace_types import TracePath
    from app.export.trace_entity_writer import write_page_entities

    doc = ezdxf.new("R2010")
    sentinel = doc.modelspace().add_line((1, 2), (3, 4))
    before = set(doc.entitydb)
    with pytest.raises(ValueError, match="contour index"):
        write_page_entities(
            doc, doc.modelspace(), trace_paths=(TracePath(((1, 1), (2, 1), (2, 2)), None, 0, 0),),
            straight_lines=(), texts=(), signatures=(), transform=lambda x, y: (x, -y),
            output_path=tmp_path / "unused.dxf", source_size=(12, 12), enclosure_records=records,
        )
    assert set(doc.entitydb) == before
    assert list(doc.modelspace()) == [sentinel]
    assert not (tmp_path / "unused.dxf").exists()


@pytest.mark.parametrize("record", [
    {"version": "explicit-native-source-region-v999", "kind": "circle", "contour_index": 0},
    {"kind": "explicit_native_source_region", "contour_index": 0},
    {"native_source_region_partition": False, "contour_index": 0},
])
def test_region_namespace_cannot_fall_through_to_generic_enclosure(record, tmp_path):
    import ezdxf
    from app.core.trace_types import TracePath
    from app.export.trace_entity_writer import write_page_entities

    doc = ezdxf.new("R2010")
    before = set(doc.entitydb)
    with pytest.raises(ValueError, match="explicit-selection contract"):
        write_page_entities(
            doc, doc.modelspace(), trace_paths=(TracePath(((1, 1), (2, 1), (2, 2)), None, 0, 0),),
            straight_lines=(), texts=(), signatures=(), transform=lambda x, y: (x, -y),
            output_path=tmp_path / "unused.dxf", source_size=(12, 12), enclosure_records=(record,),
        )
    assert set(doc.entitydb) == before
