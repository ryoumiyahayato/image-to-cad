"""Finite prior scope, full identity and actual source-read falsifiers."""
from copy import deepcopy
import hashlib
import json

import cv2
import ezdxf
import numpy as np

from app.native_objects import finite_source_ports as ports
from app.native_objects.text_contact_geometry import build_text_contact_source_graph
from app.native_objects.finite_component_saved_reader import APPID, saved_source_geometries


def _fixture(*, remote_defect=False):
    source = np.full((180, 540), 255, np.uint8)
    cv2.line(source, (20, 100), (500, 100), 0, 3)
    cv2.line(source, (100, 50), (100, 100), 0, 3)
    graph = build_text_contact_source_graph(source, [0, 0, 540, 180]).graph
    geometry = [[20., 100.], [500., 100.]]
    if remote_defect:
        geometry = [[20., 100.], [450., 100.], [470., 100.], [475., 106.], [480., 100.], [500., 100.]]
    prior = {"id": "prior", "kind": "CONNECTION_PATH", "layer": "STRUCTURE",
        "geometry": {"points": geometry, "bulges": [0.] * len(geometry), "closed": False},
        "source_evidence": {"source_path_points": [[x, 100] for x in range(18, 503)],
            "source_pixels_modified": False, "original_source_crop_xyxy_px": [0, 0, 540, 180],
            "original_source_crop_array_sha256": hashlib.sha256(source.tobytes()).hexdigest()}}
    target = {"stroke_id": "target", "representation": {"points": [[100., 50.], [100., 100.]],
                                                         "bulges": [0., 0.], "closed": False}}
    domain = ports.build_influence_domain(source, graph, [target], [87, 37, 114, 114])
    row = ports.prior_source_geometry_row(prior)
    return source, graph, prior, target, domain, row


def test_finite_prior_success_recomputes_identity_and_both_exit_sides():
    source, graph, prior, target, domain, saved = _fixture()
    result = ports.certify_finite_prior_port(source, graph, saved, prior, domain, roi=[0, 0, 540, 180], dpi=25.4)
    assert result["pass"], result["failures"]
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["body_role"] == "NECESSARY_PRIOR_FINITE_PORT"
    assert not result["whole_prior_object_reauthorized"]
    assert row["representation"]["points"][-1][0] < 400
    exits = [e for e in row["endpoint_evidence"] if e["kind"] == "FINITE_PRIOR_SCOPE_EXIT"]
    assert len(exits) == 1 and len(exits[0]["both_sides_source_points_px"]) >= 9
    assert ports.validate_finite_port_certificate(source, graph, row, prior_object=prior,
        expected_influence_domain=domain)["pass"]
    width = ports.measure_finite_port_sections(source, graph, row, [row, target])
    assert width["pass"], width
    assert width["every_finite_subrange_port_enumerated"]


def test_remote_prior_white_failure_is_kept_and_not_renewed_as_whole_path_pass():
    source, graph, prior, _, domain, saved = _fixture(remote_defect=True)
    result = ports.certify_finite_prior_port(source, graph, saved, prior, domain, roi=[0, 0, 540, 180], dpi=25.4)
    assert result["pass"], result["failures"]
    assert not result["original_whole_prior_support"]["pass"]
    assert result["excluded_remote_findings"]
    assert all(cell[0] > 400 for item in result["excluded_remote_findings"] for cell in item["white_cells"])


def test_changed_whole_geometry_or_source_never_inherits_finite_port():
    source, graph, prior, _, domain, saved = _fixture()
    changed = deepcopy(saved)
    changed["points_exact"][-1][0] = [501, 1]
    result = ports.certify_finite_prior_port(source, graph, changed, prior, domain, roi=[0, 0, 540, 180], dpi=25.4)
    assert not result["pass"] and "COMPLETE_PRIOR_SOURCE_STAGE_GEOMETRY_CHANGED" in result["failures"]
    altered = source.copy()
    altered[100, 450] = 255
    result = ports.certify_finite_prior_port(altered, graph, saved, prior, domain, roi=[0, 0, 540, 180], dpi=25.4)
    assert not result["pass"] and "PRIOR_SOURCE_CROP_HASH_MISMATCH" in result["failures"]


def test_tampered_subrange_and_shrunken_domain_are_rejected_by_recomputation():
    source, graph, prior, _, domain, saved = _fixture()
    result = ports.certify_finite_prior_port(source, graph, saved, prior, domain, roi=[0, 0, 540, 180], dpi=25.4)
    assert result["pass"], result["failures"]
    changed = deepcopy(result["rows"][0])
    changed["source_edge_subranges"][0]["start_index"] += 1
    assert not ports.validate_finite_port_certificate(source, graph, changed)["pass"]
    changed = deepcopy(result["rows"][0])
    changed["influence_domain"]["model_window"][2] -= 1
    assert not ports.validate_finite_port_certificate(source, graph, changed)["pass"]


def test_actual_cold_saved_prior_binds_complete_mm_and_finite_source_geometry(tmp_path):
    source, graph, prior, _, domain, _ = _fixture()
    scale = 25.4 / 200
    doc = ezdxf.new("R2013")
    doc.units = 4
    doc.appids.new(APPID)
    points = [(x * scale, (180 - y) * scale) for x, y in prior["geometry"]["points"]]
    entity = doc.modelspace().add_lwpolyline(points)
    entity.set_xdata(APPID, [(1000, json.dumps({"id": prior["id"]}))])
    path = tmp_path / "actual-prior.dxf"
    doc.saveas(path)
    row = saved_source_geometries(path, [0, 0, 540, 180], 200, source_model="v2")["geometries"][0]
    result = ports.certify_finite_prior_port(source, graph, row, prior, domain, roi=[0, 0, 540, 180], dpi=200)
    assert result["pass"], result["failures"]
    forged = deepcopy(row)
    forged["points_exact"][0][0][0] += 1
    result = ports.certify_finite_prior_port(source, graph, forged, prior, domain, roi=[0, 0, 540, 180], dpi=200)
    assert not result["pass"]
    assert "SAVED_PRIOR_SOURCE_COORDINATES_DO_NOT_MATCH_ACTUAL_MM_TRANSFORM" in result["failures"]


def test_plain_line_start_end_schema_keeps_original_whole_binding_hash():
    source, graph, prior, _, domain, _ = _fixture()
    prior["kind"] = "LINE"
    prior["geometry"] = {"start": prior["geometry"]["points"][0], "end": prior["geometry"]["points"][-1]}
    before = deepcopy(prior)
    result = ports.certify_finite_prior_port(source, graph, ports.prior_source_geometry_row(prior), prior,
                                            domain, roi=[0, 0, 540, 180], dpi=25.4)
    assert result["pass"], result["failures"]
    assert prior == before
    assert result["rows"][0]["prior_binding"] == before
    assert result["rows"][0]["prior_binding_sha256"] == ports._digest(before)
