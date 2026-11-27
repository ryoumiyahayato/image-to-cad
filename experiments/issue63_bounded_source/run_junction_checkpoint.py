"""Small, authored issue 63 A checkpoint: write, exit, independently cold-read.

This exercises the actual junction module, source graphs and DXF serializer.
It is not ordinary planner adoption, a real drawing result or a width model.
The cold reader uses its own Fraction incidence predicate and rebuilds source
observations from the saved PNG. It never consumes a construction PASS.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import inspect
import json
import math
import os
import subprocess
import sys
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import ezdxf
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "issue63-authored-junction-save-checkpoint-v1"
READER_SCHEMA = "independent-authored-junction-cold-reader-v1"
ROI, DPI = [1, 3, 96, 80], 300
sys.path.insert(0, str(ROOT / "cad_photo_to_dxf"))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                                     allow_nan=False) + "\n", encoding="utf-8")


def _raster(kind):
    segments = ([((16, 40), (80, 40)), ((40, 16), (40, 40)), ((64, 40), (64, 64))]
                if kind == "axial" else
                [((16, 32), (80, 48)), ((40, 12), (40, 38)), ((64, 44), (64, 68))])
    yy, xx = np.indices((80, 96))
    points = np.stack((xx, yy), axis=-1).astype(float)
    ink = np.zeros((80, 96), bool)
    # Independent authoring: pixel-center distance to the declared finite pen.
    # The source-domain production code instead enumerates closed pixel cells.
    for first, last in segments:
        first, last = np.array(first, float), np.array(last, float)
        delta = last - first
        fraction = np.clip((points - first) @ delta / float(delta @ delta), 0, 1)
        ink |= np.sum((points - first - fraction[..., None] * delta) ** 2, axis=-1) <= 4
    return np.where(ink, 0, 255).astype(np.uint8)


def authored_scene(kind="oblique", source=None):
    """Fresh graph plus complete source-bound authored finite candidates.

    The native candidate geometry is intentionally declared separately from the
    raster authoring and the production endpoint fitter. This local checkpoint
    does not claim ordinary free-cap or complete-component adoption.
    """
    from app.native_objects import attached_stroke_graph as planner
    from app.native_objects.contracts import stable_id
    from app.native_objects.text_contact_geometry import build_text_contact_source_graph

    source = _raster(kind) if source is None else source
    graph = build_text_contact_source_graph(source, [0, 0, 96, 80]).graph
    pairs, attachments, cores = {}, set(), {}
    junctions = [nid for nid, node in graph.nodes.items() if len(node["edges"]) == 3]
    if len(junctions) != 2:
        raise ValueError("AUTHORED_SOURCE_DOES_NOT_HAVE_TWO_COMPLETE_T_JUNCTIONS")
    for nid in junctions:
        passed = [item for item in planner._node_directions(graph, nid)["all_pair_candidates"] if item["pass"]]
        if len(passed) != 1:
            raise ValueError("AUTHORED_SOURCE_HAS_NO_UNIQUE_HOST_PAIR")
        a, b = map(tuple, passed[0]["pair"])
        pairs[(nid, a)], pairs[(nid, b)] = b, a
        attachments.update((nid, port) for port in graph.nodes[nid]["edges"] if port not in (a, b))
        cores[nid] = planner._core_proof(source, graph, nid)
    routes = planner._walk_decomposition(graph, {"edges": list(range(len(graph.edges))),
                                                 "nodes": sorted(graph.nodes)}, pairs, attachments)
    rows, host_index = [], None
    for index, route in enumerate(routes):
        raw = graph.xy(route["source_pixels"]).tolist()
        ends = deepcopy(route["terminals"])
        attached = [i for i, terminal in enumerate(ends)
                    if terminal["kind"] == "OBSERVED_COMPLETE_STROKE_ATTACHMENT"]
        if not attached:
            host_index = index
            native = ([[16.0, 40.0], [80.0, 40.0]] if kind == "axial" else
                      [[16.0, 32.0], [24.0, 34.25], [32.0, 36.0], [80.0, 48.0]])
        else:
            end = attached[0]
            left_guest = raw[0][0] < 50
            if kind == "axial":
                native = [[40.0, 40.0], [40.0, 16.0]] if left_guest else [[64.0, 40.0], [64.0, 64.0]]
            else:
                # Preserve a subpixel first segment with a true bend, original
                # host bends and an independently editable finite terminal tail.
                native = ([[40.0, 38.0], [40.25, 37.5], [40.0, 12.0]] if left_guest else
                          [[64.0, 44.0], [64.0, 67.0], [63.5, 68.0]])
            if end == 1:
                native.reverse()
        geometry = {"points": native, "bulges": [0.0] * len(native), "closed": False}
        rows.append({"stroke_id": stable_id("GRAPHSTROKE", geometry), "representation": geometry,
                     "source_graph_edge_ids": route["source_graph_edge_ids"],
                     "source_node_ids": route["source_node_ids"], "source_path_px": raw,
                     "endpoint_evidence": ends, "core_route_alternatives": route["core_route_alternatives"]})
    if len(rows) != 3 or host_index is None:
        raise ValueError("AUTHORED_SOURCE_DOES_NOT_HAVE_THREE_COMPLETE_BODIES")
    for row in rows:
        for terminal in row["endpoint_evidence"]:
            if terminal["kind"] == "OBSERVED_COMPLETE_STROKE_ATTACHMENT":
                terminal.update(host_path_index=host_index, host_path_id=rows[host_index]["stroke_id"],
                                host_source_graph_edge_ids=rows[host_index]["source_graph_edge_ids"])
    return source, graph, rows, cores


def attachments(rows):
    return [(index, end, terminal["host_path_index"]) for index, row in enumerate(rows)
            for end, terminal in enumerate(row["endpoint_evidence"]) if "host_path_index" in terminal]


def _write_dxf(path, rows, mapper):
    from app.native_objects.cad_io import save_native_dxf

    doc = ezdxf.new("R2013")
    doc.units = 4
    for row in rows:
        doc.layers.new(row["stroke_id"])
        doc.modelspace().add_lwpolyline([mapper(point) for point in row["representation"]["points"]],
                                       close=False, dxfattribs={"layer": row["stroke_id"]})
    return save_native_dxf(doc, path)


def _source_controls(directory):
    from app.native_objects import attached_stroke_graph as planner
    from app.native_objects import finite_source_junction as junction
    from app.native_objects.text_contact_geometry import build_text_contact_source_graph

    source, graph, rows, cores = authored_scene()
    guest_index, end, host_index = attachments(rows)[0]
    controls = {}
    mutations = {
        "unknown_explicit_host_id": lambda candidate, terminal: terminal.update(host_path_id="ABSENT_HOST"),
        "mismatched_name_and_index": lambda candidate, terminal: terminal.update(host_path_index=guest_index),
        "self_reference": lambda candidate, terminal: terminal.update(host_path_index=guest_index,
                                                                      host_path_id=candidate[guest_index]["stroke_id"]),
        "unsupported_source_near_point": lambda candidate, terminal: candidate[guest_index].update(source_graph_edge_ids=[]),
        "outside_finite_host": lambda candidate, terminal: candidate[host_index]["representation"].update(
            points=[[16.0, 32.0], [32.0, 36.0]]),
        "old_formal_host": lambda candidate, terminal: candidate[host_index].update(
            body_role="NECESSARY_PRIOR_FINITE_NEIGHBOR"),
        "old_finite_port_host": lambda candidate, terminal: candidate[host_index].update(
            body_role="NECESSARY_PRIOR_FINITE_PORT", role="NECESSARY_PRIOR_FINITE_PORT",
            prior_binding={"object_id": "AUTHORED_OLD_FORMAL_BODY"},
            full_saved_geometry=deepcopy(candidate[host_index]["representation"]),
            parent_object_id="AUTHORED_OLD_FORMAL_BODY"),
        "one_ulp_wrong_guest": lambda candidate, terminal: candidate[guest_index]["representation"]["points"][
            0 if end == 0 else -1].__setitem__(1, math.nextafter(38.0, math.inf)),
    }
    for name, mutate in mutations.items():
        candidate = deepcopy(rows)
        mutate(candidate, candidate[guest_index]["endpoint_evidence"][end])
        before = deepcopy(candidate)
        returned, receipt = junction.materialize_shared_vertices_v2(source, graph, candidate, cores)
        controls[name] = {"expected": "REFUSE", "pass": not receipt["pass"] and returned == before and candidate == before,
                          "constructor_receipt": receipt}
    for name in ("white_hole", "fourth_arm", "white_gap"):
        changed = source.copy()
        if name == "white_hole":
            changed[37, 40] = 255
        elif name == "fourth_arm":
            yy, xx = np.indices(changed.shape)
            changed[(abs(xx - 40) <= 2) & (yy >= 38) & (yy <= 58)] = 0
        else:
            changed[24:27, 36:45] = 255
        fresh = build_text_contact_source_graph(changed, [0, 0, 96, 80]).graph
        # Reuse the unchanged finite-candidate claim adversarially; the graph
        # is always rebuilt from changed source. No stale source PASS is used.
        returned, receipt = junction.materialize_shared_vertices_v2(changed, fresh, rows, cores)
        Image.fromarray(changed).save(directory / (name + ".png"))
        controls[name] = {"expected": "REFUSE", "pass": not receipt["pass"] and returned == rows,
                          "original_source_array_sha256": hashlib.sha256(changed.tobytes()).hexdigest(),
                          "fresh_original_graph": True, "constructor_receipt": receipt,
                          "near_contact_nodes": planner._plain([
                              {key: node[key] for key in ("id", "center", "edges", "core_topology",
                                                         "internal_source_endpoint_count")}
                              for node in fresh.nodes.values()
                              if np.linalg.norm(np.asarray(node["center"]) - [40, 38]) < 7])}
    _save(directory / "SOURCE_NEGATIVES.json", planner._plain(controls))
    return {name: item["pass"] for name, item in controls.items()}


def _writer(output):
    from app.native_objects import attached_stroke_graph as planner
    from app.native_objects import finite_component_saved_reader as reader
    from app.native_objects import finite_source_junction as junction

    cases = {}
    for kind in ("axial", "oblique"):
        directory = output / kind
        directory.mkdir()
        source, graph, rows, cores = authored_scene(kind)
        Image.fromarray(source).save(directory / "original_source.png")
        constructed, receipt = junction.materialize_shared_vertices_v2(source, graph, rows, cores)
        _save(directory / "CONSTRUCTION.json", planner._plain(receipt))
        _save(directory / "ORIGINAL_ROWS.json", planner._plain(rows))
        if not receipt["pass"]:
            raise ValueError(f"{kind}: {receipt['failure_reasons']}")
        before_mapper = junction.SharedCoordinateTransform(ROI, DPI)
        _write_dxf(directory / "BEFORE_IMPLICIT.dxf", rows, before_mapper)
        mapper = junction.SharedCoordinateTransform(ROI, DPI)
        serialization = _write_dxf(directory / "SHARED_VERTICES.dxf", constructed, mapper)
        _save(directory / "TRANSFORM.json", mapper.receipt())
        _save(directory / "ACTUAL_ROWS.json", planner._plain(constructed))
        # A wrong endpoint remains observable even when the change is one ULP.
        altered = ezdxf.readfile(directory / "SHARED_VERTICES.dxf")
        guest, end, _ = attachments(rows)[0]
        entity = list(altered.modelspace().query("LWPOLYLINE"))[guest]
        vertices = list(entity.get_points("xy"))
        index = 0 if end == 0 else -1
        vertices[index] = (math.nextafter(float(vertices[index][0]), math.inf), float(vertices[index][1]))
        entity.set_points(vertices, format="xy")
        altered.saveas(directory / "TAMPERED_ENDPOINT.dxf")
        cases[kind] = {"candidate_count": len(rows), "contact_count": len(attachments(rows)),
                       "original_vertex_counts": [len(row["representation"]["points"]) for row in rows],
                       "saved_vertex_counts": [len(row["representation"]["points"]) for row in constructed],
                       "actual_serialization": serialization, "source_domain_pass": receipt["pass"],
                       "source_sha256": _sha(directory / "original_source.png"),
                       "saved_dxf_sha256": _sha(directory / "SHARED_VERTICES.dxf")}
    controls = _source_controls(output)
    interfaces = {"planner_schema": planner.SCHEMA,
                  "planner_signature": str(inspect.signature(planner.plan_attached_stroke_graph)),
                  "reader_schema": reader.SCHEMA,
                  "reader_signature": str(inspect.signature(reader.saved_source_geometries)),
                  "junction_domain_schema": junction.DOMAIN_SCHEMA,
                  "junction_constructor_schema": junction.CONSTRUCTION_SCHEMA,
                  "checkpoint_reader_schema": READER_SCHEMA,
                  "bounded_component_module_present": importlib.util.find_spec(
                      "app.native_objects.bounded_source_component") is not None,
                  "full_source_stage_readiness": "NOT_CERTIFIED_BY_THIS_LOCAL_CHECKPOINT"}
    report = {"schema": SCHEMA, "phase": "writer", "pid": os.getpid(), "roi": ROI, "dpi": DPI,
              "cases": cases, "negative_source_controls": controls, "interfaces": interfaces,
              "pass": all(controls.values()), "scope": "AUTHORED_SOURCE_AND_NEW_CANDIDATES_ONLY",
              "real_source_stage": "NOT_RUN", "old_436_protection": "NOT_RUN"}
    _save(output / "WRITER.json", report)
    return report


def _q(value):
    return Fraction.from_float(float(value))


def _read_vertices(path):
    doc = ezdxf.readfile(path)
    if doc.units != 4 or any(entity.dxftype() != "LWPOLYLINE" for entity in doc.modelspace()):
        raise ValueError("UNEXPECTED_ACTUAL_SAVED_UNITS_OR_ENTITY_TYPE")
    result = []
    for entity in doc.modelspace():
        if entity.closed or any(point[4] for point in entity.get_points("xyseb")):
            raise ValueError("ACTUAL_SAVED_BODY_IS_NOT_OPEN_AND_STRAIGHT")
        result.append([tuple(_q(value) for value in point) for point in entity.get_points("xy")])
    return result


def _on_segment(point, start, end):
    # Independent rational incidence: no project kernel or tolerance import.
    cross = (point[0] - start[0]) * (end[1] - start[1]) - (point[1] - start[1]) * (end[0] - start[0])
    return cross == 0 and all(min(start[k], end[k]) <= point[k] <= max(start[k], end[k]) for k in (0, 1))


def _subsequence(original, changed):
    index = 0
    for point in changed:
        if index < len(original) and point == original[index]:
            index += 1
    return index == len(original)


def _saved_checks(path, before, references):
    actual = _read_vertices(path)
    contacts = []
    if len(actual) != len(before):
        return {"pass": False, "reason": "ACTUAL_ENTITY_COUNT_CHANGED"}
    for guest, end, host in references:
        point = actual[guest][0 if end == 0 else -1]
        contacts.append({"guest_index": guest, "host_index": host, "end_index": end,
                         "exact_finite_incidence": any(_on_segment(point, a, b)
                                                        for a, b in zip(actual[host], actual[host][1:])),
                         "explicit_shared_internal_vertex": point in actual[host][1:-1],
                         "actual_point_exact": [[str(v.numerator), str(v.denominator)] for v in point]})
    retained = [_subsequence(old, new) for old, new in zip(before, actual)]
    endpoints = [old[0] == new[0] and old[-1] == new[-1] for old, new in zip(before, actual)]
    return {"pass": all(retained) and all(endpoints)
            and all(item["exact_finite_incidence"] and item["explicit_shared_internal_vertex"] for item in contacts),
            "all_original_vertices_retained": retained, "all_original_endpoints_retained": endpoints,
            "contacts": contacts, "actual_dxf_sha256": _sha(path)}


def _source_inverse(point):
    scale = _q(25.4 / DPI)
    return point[0] / scale + ROI[0], ROI[3] - point[1] / scale


def _saved_domains(source, graph, source_rows, actual):
    from app.native_objects.finite_source_junction import prove_finite_junction_domain

    rows = deepcopy(source_rows)
    for row, vertices in zip(rows, actual):
        points = [_source_inverse(point) for point in vertices]
        row["representation"] = {"points": [[float(v) for v in point] for point in points],
                                 "bulges": [0.0] * len(points), "closed": False}
        row["representation_exact_points"] = [[{"numerator": str(v.numerator), "denominator": str(v.denominator)}
                                                for v in point] for point in points]
    return [prove_finite_junction_domain(source, graph, rows[guest]["endpoint_evidence"][end]["node_id"],
                                        rows[guest], rows[host], end)
            for guest, end, host in attachments(rows)]


def _render_saved(directory, source_path, actual):
    image = base64.b64encode(source_path.read_bytes()).decode("ascii")
    preview = Image.open(source_path).convert("RGB").resize((768, 640), Image.Resampling.NEAREST)
    draw = ImageDraw.Draw(preview)
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" width="768" height="640" viewBox="0 0 96 80">',
             '<title>Actual cold-read DXF over original authored raster</title>',
             f'<image width="96" height="80" href="data:image/png;base64,{image}"/>']
    for vertices, color in zip(actual, ("#d43b34", "#196bc4", "#09935a")):
        points = [_source_inverse(point) for point in vertices]
        coordinates = " ".join(f"{float(x):.15g},{float(y):.15g}" for x, y in points)
        display = [(float(x) * 8, float(y) * 8) for x, y in points]
        draw.line(display, fill=color, width=3)
        for x, y in display:
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), outline=color, width=2)
        lines.append(f'<polyline points="{coordinates}" fill="none" stroke="{color}" stroke-width="0.35"/>')
        lines += [f'<circle cx="{float(x):.15g}" cy="{float(y):.15g}" r="0.65" fill="none" '
                  f'stroke="{color}" stroke-width="0.2"/>' for x, y in points]
    (directory / "ACTUAL_SAVED_OVERLAY.svg").write_text("\n".join(lines + ["</svg>"]) + "\n", encoding="utf-8")
    preview.save(directory / "ACTUAL_SAVED_OVERLAY.png")


def _reader(output):
    cases = {}
    for kind in ("axial", "oblique"):
        directory = output / kind
        source_path = directory / "original_source.png"
        source = np.asarray(Image.open(source_path).convert("L"))
        # The source graph and all source ports are rebuilt in this reader process.
        _, graph, source_rows, _ = authored_scene(kind, source)
        references = attachments(source_rows)
        before = _read_vertices(directory / "BEFORE_IMPLICIT.dxf")
        actual = _read_vertices(directory / "SHARED_VERTICES.dxf")
        implicit = _saved_checks(directory / "BEFORE_IMPLICIT.dxf", before, references)
        saved = _saved_checks(directory / "SHARED_VERTICES.dxf", before, references)
        tampered = _saved_checks(directory / "TAMPERED_ENDPOINT.dxf", before, references)
        domains = _saved_domains(source, graph, source_rows, actual)
        _save(directory / "ACTUAL_SAVED_SOURCE_DOMAINS.json", domains)
        _render_saved(directory, source_path, actual)
        cases[kind] = {"pass": saved["pass"] and not tampered["pass"] and all(item["pass"] for item in domains),
                       "before_implicit": implicit, "saved": saved, "tampered": tampered,
                       "saved_source_domain_pass": [item["pass"] for item in domains],
                       "original_source_sha256": _sha(source_path),
                       "source_model_scope": "POINTWISE_DOMAIN_NOT_COMPLETE_INK_RESPONSIBILITY"}
    report = {"schema": READER_SCHEMA, "phase": "reader", "pid": os.getpid(), "cases": cases,
              "pass": all(item["pass"] for item in cases.values()),
              "construction_pass_consumed": False, "geometry_arithmetic": "INDEPENDENT_FRACTION_INCIDENCE"}
    _save(output / "COLD_READER.json", report)
    return report


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    phases = {}
    for phase in ("writer", "reader"):
        # subprocess.run returns only after the writer has exited. The next
        # phase starts a different interpreter; no in-memory DXF is reused.
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--phase", phase,
                                 "--output", str(output)], check=False, capture_output=True, text=True, encoding="utf-8")
        log = output.parent / (output.name + "-" + phase + ".log")
        log.write_text(result.stdout + result.stderr, encoding="utf-8")
        phases[phase] = {"returncode": result.returncode, "external_log": str(log), "log_sha256": _sha(log)}
        if result.returncode:
            _save(output / "FAILED_PHASE.json", {"schema": SCHEMA, "phases": phases})
            raise RuntimeError(f"{phase} failed; see {log}")
    writer = json.loads((output / "WRITER.json").read_text(encoding="utf-8"))
    reader = json.loads((output / "COLD_READER.json").read_text(encoding="utf-8"))
    methods = [Path(__file__), ROOT / "cad_photo_to_dxf/app/native_objects/finite_source_junction.py",
               ROOT / "cad_photo_to_dxf/app/native_objects/attached_stroke_graph.py",
               ROOT / "cad_photo_to_dxf/app/native_objects/attached_stroke_component.py",
               ROOT / "cad_photo_to_dxf/app/native_objects/attached_stroke_width_exact.py",
               ROOT / "cad_photo_to_dxf/app/native_objects/cad_io.py"]
    report = {"schema": SCHEMA, "status": "PASS_LOCAL_JUNCTION_CHECKPOINT", "pass": writer["pass"] and reader["pass"],
              "writer_pid": writer["pid"], "reader_pid": reader["pid"], "writer_exited_before_reader_started": True,
              "phases": phases, "method_files": {str(path.relative_to(ROOT)): _sha(path) for path in methods},
              "source_and_saved_contact_are_separate_gates": True,
              "real_source_stage": "NOT_RUN", "old_436_protection": "NOT_RUN", "complete_source_model": "NOT_RUN",
              "files": {str(path.relative_to(output)): {"bytes": path.stat().st_size, "sha256": _sha(path)}
                        for path in sorted(output.rglob("*")) if path.is_file()}}
    if not report["pass"] or writer["pid"] == reader["pid"]:
        report["pass"], report["status"] = False, "FAIL_LOCAL_JUNCTION_CHECKPOINT"
    _save(output / "MANIFEST.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--phase", choices=("writer", "reader"))
    args = parser.parse_args()
    report = (_writer(args.output) if args.phase == "writer" else _reader(args.output) if args.phase == "reader"
              else run(args.output))
    print(json.dumps({"schema": report["schema"], "pass": report["pass"], "output": str(args.output)}))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
