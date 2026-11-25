"""Post-save checker regressions; generated geometry is not an OCR/EXE claim."""

from copy import deepcopy
import hashlib
import json

import cv2
import ezdxf
import numpy as np
from PIL import Image
import pytest

from app.native_objects.circle_endpoint_contacts import restore_circle_endpoint_contacts
from app.native_objects.circular_markers import discover_circular_markers
from scripts.windows_native_smoke import _json_digest, digest, inspect_contact_path_vertices, native_identity


def saved_terminal_checker_fixture(tmp_path, reverse=False):
    gray = np.full((480, 640), 255, np.uint8)
    cv2.circle(gray, (80, 80), 20, 0, 3)
    cv2.line(gray, (75, 73), (75, 87), 0, 2)
    cv2.line(gray, (75, 73), (85, 73), 0, 2)
    cv2.line(gray, (75, 80), (82, 80), 0, 2)
    cv2.line(gray, (102, 80), (145, 80), 0, 3)
    source = tmp_path / "source.png"
    Image.fromarray(gray).save(source)
    observed = next(row for row in discover_circular_markers(gray, [0, 0, 640, 480])["rows"] if row["geometry_accepted"])
    circle = {"id": observed["id"], "kind": "CIRCLE", "geometry": observed["geometry"],
              "source_evidence": {**deepcopy(observed["source_evidence"]), "components_complete": False}}
    points = [[103.0, 80.0], [110.0, 80.0], [130.0, 80.0], [145.0, 80.0]]
    if reverse:
        points.reverse()
    planned = {"points": points, "bulges": [0.0] * len(points), "closed": False}
    original = {"id": "checker-path", "kind": "CONNECTION_PATH", "geometry": deepcopy(planned),
                "source_evidence": {"source_path_points": deepcopy(points), "source_pixels_modified": False}}
    restored = restore_circle_endpoint_contacts(gray, [0, 0, 640, 480], [circle, original])
    assert len(restored["replacements"]) == 1
    path_row = restored["replacements"][0]
    document = ezdxf.new("R2013")
    document.units = 4
    document.appids.new("I2CAD_NATIVE_V2")
    mm = 25.4 / 200
    center = circle["geometry"]["center"]
    entity = document.modelspace().add_circle((center[0] * mm, (480 - center[1]) * mm), circle["geometry"]["radius_px"] * mm)
    entity.set_xdata("I2CAD_NATIVE_V2", [(1000, json.dumps({"id": circle["id"], "kind": "CIRCLE"}))])
    entity = document.modelspace().add_lwpolyline([(x * mm, (480 - y) * mm) for x, y in path_row["geometry"]["points"]])
    entity.set_xdata("I2CAD_NATIVE_V2", [(1000, json.dumps({"id": path_row["id"], "kind": "CONNECTION_PATH", "circle_endpoint_contacts": True}))])
    saved = tmp_path / "checker-only.dxf"
    document.saveas(saved)
    # These transport fields exercise the checker. Only an ordinary pipeline
    # run can provide the actual complete saved-source audit used in release.
    cold = {"circle_endpoint_contact_checks": [{"id": path_row["id"], "type": "CIRCLE_ENDPOINT_CONTACT",
             "restored_endpoints": 1, "pass": True, "actual_saved_geometry_checked": True,
             "original_source_records_preserved": True, "external_entity_is_independent": True,
             "checker_test_only": True}]}
    return source, ezdxf.readfile(saved), {"objects": [circle, path_row], "source_sha256": digest(source)}, cold, planned


@pytest.mark.parametrize("reverse", [False, True])
def test_saved_terminal_checker_replays_exact_source_and_retains_every_original_vertex(tmp_path, reverse):
    source, document, objects, cold, planned = saved_terminal_checker_fixture(tmp_path, reverse)
    row = objects["objects"][1]
    entity = document.modelspace().query("LWPOLYLINE")[0]
    result = inspect_contact_path_vertices(document, objects, cold, entity, row, planned, source)
    assert result["endpoint_certificate_replayed"]
    assert result["original_vertices_continuously_preserved"] == 4
    assert result["added_terminal_segments"] == 1
    assert result["saved_vertex_tolerance_px"] == 1e-6
    assert result["terminal_checks"][0]["endpoint_number"] == int(reverse)


@pytest.mark.parametrize("damage", ["missing-certificate", "changed-original-vertex", "removed-original-vertex",
                                   "actual-endpoint-gap", "white-source-cell", "missing-pixel-witness",
                                   "wrong-port", "wrong-saved-circle", "missing-cold-check", "relaxed-policy"])
def test_saved_terminal_checker_rejects_unproved_or_changed_saved_path(tmp_path, damage):
    source, document, objects, cold, planned = saved_terminal_checker_fixture(tmp_path)
    circle, row = objects["objects"]
    certificate = row["source_evidence"]["circle_endpoint_contacts"]
    end = certificate["ends"][0]
    entity = document.modelspace().query("LWPOLYLINE")[0]
    mm = 25.4 / 200
    if damage == "missing-certificate":
        del row["source_evidence"]["circle_endpoint_contacts"]
    elif damage in ("changed-original-vertex", "removed-original-vertex"):
        if damage == "changed-original-vertex":
            row["geometry"]["points"][2][0] += 0.5
        else:
            row["geometry"]["points"].pop(2)
            row["geometry"]["bulges"].pop(2)
        certificate["restored_geometry_sha256"] = _json_digest(row["geometry"])
        entity.set_points([(x * mm, (480 - y) * mm) for x, y in row["geometry"]["points"]])
    elif damage == "actual-endpoint-gap":
        points = list(entity.get_points())
        points[0] = (points[0][0] + 0.0001 * mm, *points[0][1:])
        entity.set_points(points)
    elif damage == "white-source-cell":
        with Image.open(source) as image:
            gray = np.asarray(image.convert("L")).copy()
        gray[80, 101] = 255
        Image.fromarray(gray).save(source)
        objects["source_sha256"] = digest(source)
        x0, y0, x1, y1 = circle["source_evidence"]["crop_bbox_xyxy_px"]
        checksum = hashlib.sha256(np.ascontiguousarray(gray[y0:y1, x0:x1]).tobytes()).hexdigest()
        circle["source_evidence"]["crop_sha256"] = checksum
        end["circle_source_crop_sha256"] = checksum
    elif damage == "missing-pixel-witness":
        end["direct_segment_cells_xy"] = []
    elif damage == "wrong-port":
        end["observed_port_index"] = 1
    elif damage == "wrong-saved-circle":
        document.modelspace().query("CIRCLE")[0].translate(0.001, 0, 0)
    elif damage == "missing-cold-check":
        cold["circle_endpoint_contact_checks"] = []
    else:
        certificate["policy"]["absolute_extension_limit_px"] = 60.0
    saved = tmp_path / "mutated.dxf"
    document.saveas(saved)
    document = ezdxf.readfile(saved)
    entity = next(value for value in document.modelspace() if native_identity(value)["id"] == row["id"])
    with pytest.raises(AssertionError):
        inspect_contact_path_vertices(document, objects, cold, entity, row, planned, source)
