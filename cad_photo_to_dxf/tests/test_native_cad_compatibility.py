"""Regression evidence for the raw CAD audit; synthetic geometry only."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import ezdxf


SCRIPT = Path(__file__).resolve().parents[2] / "maintenance/native_cad_compatibility.py"
SPEC = importlib.util.spec_from_file_location("native_cad_compatibility", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_raw_zero_zscale_cannot_be_hidden_by_planar_geometry(tmp_path):
    doc = ezdxf.new("R2013", units=4)
    block = doc.blocks.new("SYNTHETIC_ROOM")
    block.add_lwpolyline([(0, 0), (4, 0), (4, 3), (0, 3)], close=True)
    doc.modelspace().add_blockref("SYNTHETIC_ROOM", (10, 20), dxfattribs={"zscale": 2})
    path = tmp_path / "scale.dxf"
    doc.saveas(path)
    lines = path.read_text().splitlines()
    for index in range(0, len(lines), 2):
        if lines[index].strip() == "43" and lines[index + 1] == "2.0":
            lines[index + 1] = "0.0"
    path.write_text("\n".join(lines) + "\n")
    original = path.read_bytes()
    result = audit.snapshot(path)
    insert = result["inserts"][0]
    assert insert["raw_scale_tags"]["43"] == "0.0"
    assert insert["singular_scale"] is True
    assert insert["raw_scale_determinant"] == 0
    assert insert["direct_member_z_all_zero"] is True
    assert "independent_consumer" in result["not_established"]
    assert path.read_bytes() == original


def test_xdata_loss_invalidates_audit_without_claiming_uneditable(tmp_path):
    doc = ezdxf.new("R2013", units=4)
    doc.appids.add("TEST_SOURCE")
    line = doc.modelspace().add_line((0, 0), (4, 3))
    line.set_xdata("TEST_SOURCE", [(1000, "synthetic")])
    before = tmp_path / "before.dxf"
    after = tmp_path / "after.dxf"
    doc.saveas(before)
    line.discard_xdata("TEST_SOURCE")
    doc.saveas(after)
    result = audit.compare(audit.snapshot(before), audit.snapshot(after))
    assert result["xdata_before_after"] == [1, 0]
    assert result["prior_audit_reusable"] is False
    assert result["xdata_loss_is_traceability_issue_not_editability_verdict"] is True
    assert result["status"] == "OBSERVATIONS_ONLY_NOT_CAD_ACCEPTANCE"


def test_review_off_frozen_and_plot_are_distinct(tmp_path):
    doc = ezdxf.new("R2013", units=4)
    review = doc.layers.new("REVIEW", dxfattribs={"color": 30, "plot": 0})
    review.freeze()
    review.lock()
    review.on()
    path = tmp_path / "layers.dxf"
    doc.saveas(path)
    result = audit.snapshot(path)
    layer = next(layer for layer in result["layers"] if layer["name"] == "REVIEW")
    assert layer["off"] is False
    assert layer["frozen"] is True
    assert layer["locked"] is True
    assert layer["plot"] == 0
    assert "printed_review_visibility" in result["not_established"]
