"""Small pixel-derived capability/refusal checkpoint; no adoption or DXF export.

Ten independently authored raster controls use fixed geometry and fixed normal
sections. Both field versions receive the same observations and all black,
white and own-section constraints. A graph refusal witness is reported
separately; absence of that witness is not complete-source acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import shutil
import subprocess
import sys
import time
import traceback
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path

SCHEMA = "issue63-model-capability-checkpoint-b-v2-independent-knots"
SOURCE_SIZE = (96, 80)
WINDOW = (8, 24, 80, 56)
POINTS = ((20, 40), (60, 40))
SECTION_CENTERS = ((28, 40), (40, 40), (52, 40))
BODY_ID = "AUTHORED_FINITE_STROKE"
DEFAULT_REPO = Path(__file__).resolve().parents[2]


def plain(value):
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if hasattr(value, "tolist"):
        return plain(value.tolist())
    if isinstance(value, F):
        return {"numerator": str(value.numerator), "denominator": str(value.denominator)}
    return value


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(plain(value), stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def sources(repo):
    paths = [Path(__file__).resolve()]
    directory = repo / "cad_photo_to_dxf/app/native_objects"
    paths += [directory / name for name in ("bounded_stroke_field.py", "bounded_stroke_field_v2.py",
        "attached_stroke_width_exact.py", "attached_stroke_component.py", "text_contact_geometry.py", "connections.py",
        "finite_circle_source.py", "finite_source_ports.py")]
    paths += [repo / "docs/native/ISSUE63_CONTINUOUS_FIELD_V2_CONTRACT_20261127.md"]
    return {path.relative_to(repo).as_posix(): sha(path) for path in paths}


def file_manifest(directory):
    return [{"path": path.relative_to(directory).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)}
        for path in sorted(directory.rglob("*")) if path.is_file()]


def declarations():
    return [
        {"name": "clean_constant", "profile": "constant", "mutation": "none", "role": "CLEAN_CAPABILITY_CONTROL"},
        {"name": "clean_symmetric_variable", "profile": "symmetric", "mutation": "none", "role": "CLEAN_CAPABILITY_CONTROL"},
        {"name": "clean_monotone_variable", "profile": "monotone", "mutation": "none", "role": "CLEAN_CAPABILITY_CONTROL"},
        {"name": "one_pixel_cap_extension", "profile": "constant", "mutation": "one_cap_pixel", "role": "OPEN_OBSERVABLE_BOUNDARY_DIAGNOSTIC"},
        {"name": "independent_short_tail", "profile": "constant", "mutation": "short_tail", "role": "REQUIRED_SOURCE_TRUNCATION_REFUSAL"},
        {"name": "independent_long_tail", "profile": "constant", "mutation": "long_tail", "role": "REQUIRED_SOURCE_TRUNCATION_REFUSAL"},
        {"name": "finite_wedge", "profile": "constant", "mutation": "wedge", "role": "OPEN_BOUNDED_SHAPE_DIAGNOSTIC"},
        {"name": "finite_block", "profile": "constant", "mutation": "block", "role": "OPEN_BOUNDED_SHAPE_DIAGNOSTIC"},
        {"name": "real_white_gap", "profile": "constant", "mutation": "white_gap", "role": "REQUIRED_WHITE_SOURCE_REFUSAL"},
        {"name": "real_white_hole", "profile": "constant", "mutation": "white_hole", "role": "REQUIRED_WHITE_SOURCE_REFUSAL"},
    ]


def authored_source(declaration):
    """Center-sample a separately declared disc stamp process, not field code."""
    import numpy as np

    width, height = SOURCE_SIZE
    yy, xx = np.mgrid[0:height, 0:width]
    ink = np.zeros((height, width), dtype=bool)
    stamps = []
    for step in range(161):
        x = 20.0 + step / 4.0
        t = step / 160.0
        if declaration["profile"] == "constant":
            radius_squared = 4.0
        elif declaration["profile"] == "symmetric":
            radius_squared = 4.0 + 12.0 * (1.0 - abs(2.0 * t - 1.0))
        else:
            radius_squared = 4.0 + 12.0 * t
        ink |= (xx - x) ** 2 + (yy - 40.0) ** 2 <= radius_squared
        stamps.append({"center": [x, 40.0], "radius_squared": radius_squared})
    mutation = declaration["mutation"]
    if mutation == "one_cap_pixel":
        ink[40, 63] = True
    elif mutation in ("short_tail", "long_tail"):
        ink[40, 61:66 if mutation == "short_tail" else 72] = True
    elif mutation == "wedge":
        for x, y in [(61, 42), (62, 42), (63, 42), (61, 43), (62, 43), (61, 44)]:
            ink[y, x] = True
    elif mutation == "block":
        ink[42:45, 61:64] = True
    elif mutation == "white_gap":
        ink[:, 44:46] = False
    elif mutation == "white_hole":
        ink[40, 44] = False
    return np.where(ink, 0, 255).astype(np.uint8), {
        "rasterizer": "CENTER_POINT_SAMPLED_UNION_OF_PREDECLARED_QUARTER_PIXEL_DISC_STAMPS",
        "uses_project_geometry_or_field_kernel": False, "stamps": stamps,
        "declaration": declaration, "source_shape": [height, width]}


def measure_source(gray):
    from app.native_objects import attached_stroke_width_exact as exact

    sections = []
    for q in SECTION_CENTERS:
        row = exact.measure_section(gray, q, POINTS[0], POINTS[1], half_span=12)
        row["native_segment_index"] = 0
        sections.append(row)
    width = exact.intersect_sections(sections)
    width["sections"] = sections
    return width


def observations(gray, widths, window):
    black, white, own = [], [], []
    left, top, right, bottom = window
    for y in range(top, bottom):
        for x in range(left, right):
            (black if int(gray[y, x]) < 128 else white).append([x, y])
    first_white, measured_white = [], []
    for oid, width in widths.items():
        for index, section in enumerate(width["sections"]):
            measured_white.extend(cell for cell, value in zip(section.get("section_source_cells", []),
                section.get("original_values", [])) if value >= 128)
            if not section.get("constraint_eligible"):
                continue
            own.extend({"body_id": oid, "source_cell": cell, "section_index": index}
                       for cell in section["independent_black_cells"])
            first_white.extend(section["first_white_cells"])
    return {"black_cells": black, "window_white_cells": white,
        "all_first_white_cells_including_outside_window": first_white,
        "all_actually_measured_section_white_including_ineligible": measured_white,
        "white_cells": [list(cell) for cell in dict.fromkeys(map(tuple, white + first_white + measured_white))],
        "owned_black_constraints": own,
        "fixed_window_xyxy": window, "window_cell_count": (right - left) * (bottom - top),
        "source_independence": "FRESH_FIXED_NORMAL_SECTIONS_ON_AUTHORED_SINGLE_AXIS_SOURCE",
        "producer_pass_supplied_as_source_evidence": False}


def recheck_vector(kernel, fields, black, white, own, result):
    """Check all supplied observations again against the one returned vector."""
    if result.get("pass") is not True:
        return {"status": "NOT_APPLICABLE_NO_FEASIBLE_VECTOR", "pass": None}
    if "parameter_vector" in result:
        replay = kernel.evaluate_vector(black, white, fields, result["parameter_vector"],
                                        owned_black_constraints=own)
        keys = ("parameter_layout", "selected_squared_half_widths", "black_witnesses", "white_witnesses")
        same = all(replay.get(key) == result.get(key) for key in keys)
        return {"status": "ALL_SUPPLIED_AND_RETAINED_SECTION_OBSERVATIONS_EXACTLY_RECHECKED",
            "pass": replay.get("pass") is True and same, "checks": replay.get("checks"),
            "same_complete_vector_and_witness_receipts": same,
            "canonical_owned_black_constraint_count": replay.get("canonical_owned_black_constraint_count"),
            "canonical_white_cell_count": replay.get("canonical_white_cell_count"),
            "shared_exact_kernel": True, "independent_physical_source_certificate": False}
    from app.native_objects import attached_stroke_width_exact as exact

    values = [exact.decode_rational(row) for row in result["alpha_vector"]]
    prepared = [kernel.prepare_field(row["bounded_width_field"]) for row in fields]
    by_id = {row["stroke_id"]: index for index, row in enumerate(fields)}
    checks = {"one_alpha_per_body": len(values) == len(fields),
        "strict_parameter_bounds": all(0 <= value < 1 for value in values),
        "all_black": all(any(kernel.cell_cost(field, cell).value(alpha) <= 0
            for field, alpha in zip(prepared, values)) for cell in black),
        "every_owned_section_black": all(kernel.cell_cost(prepared[by_id[row["body_id"]]], row["source_cell"])
            .value(values[by_id[row["body_id"]]]) <= 0 for row in own)}
    checks["one_common_white_witness_per_cell"] = all(any(all(
        kernel.point_cost(field, (F(cell[0]) + dx, F(cell[1]) + dy)).value(alpha) > 0
        for field, alpha in zip(prepared, values)) for dx in (F(-1, 2), F(0), F(1, 2))
        for dy in (F(-1, 2), F(0), F(1, 2))) for cell in white)
    return {"status": "ALL_SUPPLIED_OBSERVATIONS_RECHECKED_UNDER_ONE_VECTOR", "checks": checks,
        "pass": all(checks.values()), "shared_exact_kernel": True,
        "independent_physical_source_certificate": False}


def evaluate_model(kernel, bodies, observed, max_states):
    fields = [{"stroke_id": row["stroke_id"], "bounded_width_field":
        kernel.build_width_field(row["points"], row["width"])} for row in bodies]
    if not all(row["bounded_width_field"].get("pass") is True for row in fields):
        return {"fields": fields, "solver": {"pass": False, "status": "NOT_RUN_FIELD_INPUT_NOT_ESTABLISHED"},
            "vector_recheck": {"pass": None, "status": "NOT_RUN"}}
    result = kernel.solve_bounded_union(observed["black_cells"], observed["white_cells"], fields,
        owned_black_constraints=observed["owned_black_constraints"], max_states=max_states)
    return {"fields": fields, "solver": result,
        "vector_recheck": recheck_vector(kernel, fields, observed["black_cells"], observed["white_cells"],
            observed["owned_black_constraints"], result)}


def source_refusal_witness(gray):
    """Independent small-source refusal facts, never positive source acceptance.

    A fresh original skeleton route supplies a contiguous outward chord of at
    least 4 px inside the existing 1.5 px axial corridor and beyond the existing
    3 px cap extent. All original edge samples remain in the saved graph. This
    narrow witness is only for these declared straight-body controls.
    """
    from app.native_objects import attached_stroke_component as component
    from app.native_objects.text_contact_geometry import build_text_contact_source_graph

    context = build_text_contact_source_graph(gray, (0, 0, gray.shape[1], gray.shape[0]))
    graph = context.graph
    edges = [{"edge_id": index, "nodes": edge["nodes"], "source_points": graph.xy(edge["pixels"]).tolist()}
        for index, edge in enumerate(graph.edges)]
    witnesses = []
    for end, adjacent in ((0, 1), (1, 0)):
        origin = tuple(F(value) for value in POINTS[end])
        outward = tuple(F(POINTS[end][k] - POINTS[adjacent][k]) for k in (0, 1))
        norm2 = sum(value * value for value in outward)
        for edge in edges:
            chunks, current = [], []
            for point in edge["source_points"]:
                delta = tuple(F(point[k]) - origin[k] for k in (0, 1))
                forward = sum(a * b for a, b in zip(delta, outward))
                normal = delta[0] * outward[1] - delta[1] * outward[0]
                if forward > 0 and normal * normal <= F(9, 4) * norm2:
                    current.append(point)
                elif current:
                    chunks.append(current)
                    current = []
            if current:
                chunks.append(current)
            for points in chunks:
                chord2 = sum((F(points[-1][k]) - F(points[0][k])) ** 2 for k in (0, 1))
                farthest = max(sum((F(point[k]) - origin[k]) * outward[k] for k in (0, 1)) for point in points)
                if chord2 >= 16 and farthest * farthest > 9 * norm2:
                    witnesses.append({"native_end": end, "source_edge_id": edge["edge_id"],
                        "ordered_original_skeleton_points": points, "chord_squared_exact": plain(chord2),
                        "maximum_forward_projection_squared_px": plain(farthest * farthest / norm2),
                        "all_witness_pixels_original_black": all(int(gray[int(y), int(x)]) < 128 for x, y in points),
                        "reason": "OBSERVABLE_CONTIGUOUS_SOURCE_ROUTE_BEYOND_DECLARED_FINITE_END"})
    finite = component.exact_centerline_source_support(gray, POINTS)
    refusal = bool(witnesses) or finite["pass"] is not True
    return {"schema": "checkpoint-b-source-refusal-witness-v1",
        "refuse_declared_whole_object": refusal,
        "status": "SOURCE_COUNTEREXAMPLE_TO_COMPLETE_OBJECT" if refusal else "NO_REFUSAL_WITNESS_FOUND_NOT_SOURCE_ACCEPTANCE",
        "finite_centerline_original_source": finite, "continuation_witnesses": witnesses,
        "all_graph_edges": edges, "source_crop_hash": context.source_crop_hash,
        "source_graph_rebuilt": True, "source_completeness_positive_certificate": False,
        "scope": "NARROW_STRAIGHT_CONTROL_REFUSAL_NOT_REPLACEMENT_FOR_PRODUCTION_READER"}


def synthetic_case(args, declaration, first, second):
    import numpy as np
    from PIL import Image

    directory = args.output / declaration["name"]
    directory.mkdir()
    started = time.perf_counter()
    source, generator = authored_source(declaration)
    array_sha = hashlib.sha256(source.tobytes()).hexdigest()
    Image.fromarray(source).save(directory / "source.png")
    write(directory / "INPUT.json", {"declaration": declaration, "generator": generator,
        "source_array_sha256": array_sha, "source_png_sha256": sha(directory / "source.png"),
        "points": POINTS, "section_centers": SECTION_CENTERS, "window": WINDOW,
        "case_name_is_not_an_adoption_rule": True})
    with Image.open(directory / "source.png") as image:
        gray = np.asarray(image.convert("L"))
    width = measure_source(gray)
    observed = observations(gray, {BODY_ID: width}, WINDOW)
    write(directory / "MEASURED_WIDTH.json", width)
    write(directory / "OBSERVATIONS.json", observed)
    body = {"stroke_id": BODY_ID, "points": POINTS, "width": width}
    results = {}
    for label, kernel in (("v1", first), ("v2", second)):
        results[label] = evaluate_model(kernel, [body], observed, args.max_states)
        write(directory / (label.upper() + "_MODEL.json"), results[label])
    source_result = source_refusal_witness(gray)
    write(directory / "SOURCE_REFUSAL.json", source_result)
    second_pass = results["v2"]["solver"].get("pass") is True
    role = declaration["role"]
    requirement = (second_pass if role == "CLEAN_CAPABILITY_CONTROL" else
        source_result["refuse_declared_whole_object"] if role == "REQUIRED_SOURCE_TRUNCATION_REFUSAL" else
        not second_pass and source_result["refuse_declared_whole_object"] if role == "REQUIRED_WHITE_SOURCE_REFUSAL" else None)
    summary = {"name": declaration["name"], "role": role, "source_array_sha256": array_sha,
        "v1_field_feasible": results["v1"]["solver"].get("pass") is True,
        "v1_status": results["v1"]["solver"].get("status"),
        "v2_field_feasible": second_pass, "v2_status": results["v2"]["solver"].get("status"),
        "source_refusal_status": source_result["status"], "continuation_witness_count": len(source_result["continuation_witnesses"]),
        "declared_whole_object_refused": source_result["refuse_declared_whole_object"],
        "capability_or_refusal_requirement_satisfied": requirement,
        "v1_vector_recheck": results["v1"]["vector_recheck"].get("pass"),
        "v2_vector_recheck": results["v2"]["vector_recheck"].get("pass"),
        "all_measured_sections_retained": len(width["sections"]) == len(SECTION_CENTERS),
        "source_array_unchanged": hashlib.sha256(gray.tobytes()).hexdigest() == array_sha,
        "wall_seconds": time.perf_counter() - started,
        "source_completeness_positive_certificate": False, "adoption": "NOT_RUN"}
    write(directory / "RESULT.json", summary)
    write(directory / "FILE_MANIFEST.json", file_manifest(directory))
    return summary


def conditional_case(args, first, second):
    from PIL import Image

    directory = args.output / "frozen_real_two_cell_conditional"
    directory.mkdir()
    plan = json.loads(args.real_plan.read_text())
    reference = json.loads(args.conditional_reference.read_text())
    if sha(args.real_plan) != reference["plan_sha256"]:
        raise ValueError("CONDITIONAL_REFERENCE_PLAN_IDENTITY_MISMATCH")
    proof = next(row["finite_component_responsibility"] for row in plan["components"]
                 if row.get("finite_component_responsibility"))
    bodies = [{"stroke_id": row["stroke_id"], "points": row["representation"]["points"], "width": row["width"]}
              for row in proof["bodies"]]
    cells = [row["cell"] for row in reference["rows"][0]["cells"]]
    if any([row["cell"] for row in body["cells"]] != cells for body in reference["rows"]):
        raise ValueError("CONDITIONAL_REFERENCE_CELL_SET_INCONSISTENT")
    with Image.open(args.real_source) as image:
        gray = image.convert("L")
        values = [gray.getpixel(tuple(cell)) for cell in cells]
    if values != [0] * len(cells):
        raise ValueError("CONDITIONAL_SOURCE_CELLS_ARE_NOT_ORIGINAL_BLACK")
    own = [{"body_id": body["stroke_id"], "source_cell": cell, "section_index": index}
        for body in bodies for index, section in enumerate(body["width"]["sections"])
        if section.get("constraint_eligible") for cell in section["independent_black_cells"]]
    first_whites = [cell for body in bodies for section in body["width"]["sections"]
        if section.get("constraint_eligible") for cell in section["first_white_cells"]]
    measured_whites = [cell for body in bodies for section in body["width"]["sections"]
        for cell, value in zip(section.get("section_source_cells", []), section.get("original_values", [])) if value >= 128]
    whites = [list(cell) for cell in dict.fromkeys(map(tuple, first_whites + measured_whites))]
    paths = {"plan": args.real_plan, "source": args.real_source, "reference": args.conditional_reference}
    before = {key: sha(path) for key, path in paths.items()}
    write(directory / "INPUT.json", {"files": {key: {"path": str(path), "sha256": before[key]} for key, path in paths.items()},
        "cells": cells, "source_gray_values": values, "original_bodies": bodies,
        "old_geometries_and_sections_unchanged": True, "new_source_measurements": False,
        "source_graph_stage": "NOT_RUN", "new_unproved_junction_controls": [],
        "all_original_measured_white_cells_including_ineligible_retained": True,
        "first_run_first_white_observations_expanded_with_already_measured_white": True,
        "two_black_only_scope_not_repeated": "NEW_CONTRACT_MANDATORILY_RETAINS_ALL_OWN_SECTION_OBSERVATIONS"})
    results = {}
    for scope, observed in (
        ("two_black_plus_all_original_section_constraints", {"black_cells": cells, "white_cells": whites,
            "owned_black_constraints": own}),
    ):
        write(directory / (scope + "_observations.json"), observed)
        results[scope] = {}
        for label, kernel in (("v1", first), ("v2", second)):
            result = evaluate_model(kernel, bodies, observed, args.max_states)
            write(directory / (scope + "_" + label + ".json"), result)
            results[scope][label] = {"pass": result["solver"].get("pass"), "status": result["solver"].get("status"),
                "vector_recheck_pass": result["vector_recheck"].get("pass"),
                "exact_family_infeasibility_proved": result["solver"].get("exact_family_infeasibility_proved"),
                "resource_truncated": result["solver"].get("resource_truncated")}
    report = {"scope": "FROZEN_GEOMETRY_AND_HISTORICAL_OBSERVATION_CAPABILITY_ONLY", "results": results,
        "inputs_unchanged": before == {key: sha(path) for key, path in paths.items()},
        "old_outer_bound_preserved": {"sha256": before["reference"], "applies_to_original_v1_family": True},
        "new_issue63_stage": "NOT_RUN", "new_saved_dxf": "NOT_RUN", "new_adoption_count": "NOT_ESTABLISHED"}
    write(directory / "RESULT.json", report)
    write(directory / "FILE_MANIFEST.json", file_manifest(directory))
    return report


def circle_joint_case(args, model):
    """Actual-circle predicates, finite ownership and query authorization controls.

    The pixel authoring and supplied synthetic scope are explicit. This is not
    an independently source-certified production circle or adoption receipt.
    """
    import numpy as np
    from app.native_objects import attached_stroke_width_exact as exact
    from app.native_objects import finite_circle_source as circle
    from app.native_objects.finite_source_ports import _runs
    from PIL import Image

    directory = args.output / "circle_joint_scope_and_boundary"
    directory.mkdir()
    yy, xx = np.mgrid[0:80, 0:96]
    radial_squared = (xx - 40) ** 2 + (yy - 30) ** 2
    ring = (radial_squared >= 8 ** 2) & (radial_squared <= 12 ** 2)
    axial = np.maximum(np.maximum(20 - xx, xx - 60), 0)
    straight = axial ** 2 + (yy - 64) ** 2 <= 4
    source = np.where(ring | straight, 0, 255).astype(np.uint8)
    source_sha = hashlib.sha256(source.tobytes()).hexdigest()
    Image.fromarray(source).save(directory / "source.png")
    with Image.open(directory / "source.png") as image:
        gray = np.asarray(image.convert("L"))
    scope = (8, 8, 80, 78)
    points = ((20, 64), (60, 64))
    sections = []
    for q in ((28, 64), (40, 64), (52, 64)):
        section = exact.measure_section(gray, q, points[0], points[1], half_span=12)
        section["native_segment_index"] = 0
        sections.append(section)
    straight_width = exact.intersect_sections(sections)
    straight_width["sections"] = sections
    geometry = {"object_id": "SYNTHETIC_CIRCLE_NATIVE_CHILD", "parent_object_id": "SYNTHETIC_MARKER",
        "stroke_id": "SYNTHETIC_CIRCLE_NATIVE_CHILD", "curve_type": "CIRCLE", "kind": "CIRCLE",
        "circle_center_exact": [exact.encode_rational(F(40)), exact.encode_rational(F(30))],
        "circle_radius_exact": exact.encode_rational(F(10)), "body_role": "NECESSARY_PRIOR_CIRCLE_ARC"}
    ring_cells = {(int(x), int(y)) for y, x in zip(*np.nonzero(ring))}
    radial_width = circle._radial_sections(gray, geometry, scope, ring_cells,
        [{"object_id": "SYNTHETIC_STRAIGHT", "points": points}], ())
    observed = observations(gray, {"SYNTHETIC_STRAIGHT": straight_width,
                                  geometry["stroke_id"]: radial_width}, scope)
    query = {(x, y) for y in range(scope[1], scope[3]) for x in range(scope[0], scope[2])}
    query.update(tuple(cell) for cell in observed["white_cells"])
    query.update(tuple(row["source_cell"]) for row in observed["owned_black_constraints"])
    circle_body = {**geometry, "width": radial_width,
        "finite_arc_domain": {"authorized_query_cells_y_x0_x1": _runs(query)},
        "authorized_original_ring_cells_y_x0_x1": _runs(ring_cells & query)}
    bodies = [{"stroke_id": "SYNTHETIC_STRAIGHT", "bounded_width_field":
               model.build_width_field(points, straight_width)}, circle_body]
    write(directory / "INPUT.json", {"authoring": "INTEGER_CENTER_SAMPLES_OF_ANNULUS_AND_SEPARATE_FINITE_CAPSULE",
        "circle_center": [40, 30], "circle_radius": 10, "circle_nominal_pen_radius": 2,
        "straight_points": points, "straight_nominal_pen_radius": 2, "scope": scope,
        "source_array_sha256": source_sha, "bodies": bodies,
        "synthetic_scope_declared_by_author": True, "production_source_approval": False,
        "producer_pass_supplied_as_source_evidence": False})
    write(directory / "OBSERVATIONS.json", observed)
    result = model.solve_bounded_union(observed["black_cells"], observed["white_cells"], bodies,
        owned_black_constraints=observed["owned_black_constraints"], max_states=args.max_states)
    replay = recheck_vector(model, bodies, observed["black_cells"], observed["white_cells"],
                           observed["owned_black_constraints"], result)
    write(directory / "JOINT_MODEL.json", {"solver": result, "vector_recheck": replay})
    # The marker/source alias must resolve to the actual native-circle body.
    aliases = deepcopy(observed["owned_black_constraints"])
    for row in aliases:
        if row["body_id"] == geometry["stroke_id"]:
            row["body_id"] = geometry["parent_object_id"]
    alias_result = (model.evaluate_vector(observed["black_cells"], observed["white_cells"], bodies,
        result["parameter_vector"], owned_black_constraints=aliases) if result.get("pass") else
        {"status": "NOT_APPLICABLE_NO_FEASIBLE_VECTOR", "pass": None})
    write(directory / "ALIAS_VECTOR_REPLAY.json", alias_result)
    missing_query = deepcopy(bodies)
    omitted_white = tuple(observed["white_cells"][0])
    missing_query[-1]["finite_arc_domain"]["authorized_query_cells_y_x0_x1"] = _runs(query - {omitted_white})
    query_result = model.solve_bounded_union(observed["black_cells"], observed["white_cells"], missing_query,
        owned_black_constraints=observed["owned_black_constraints"], max_states=args.max_states)
    write(directory / "UNAUTHORIZED_QUERY_REFUSAL.json", {"omitted_source_white_cell": omitted_white,
        "solver": query_result})
    missing_ownership = deepcopy(bodies)
    omitted_ring = min(ring_cells)
    missing_ownership[-1]["authorized_original_ring_cells_y_x0_x1"] = _runs((ring_cells & query) - {omitted_ring})
    owner_result = model.solve_bounded_union(observed["black_cells"], observed["white_cells"], missing_ownership,
        owned_black_constraints=observed["owned_black_constraints"], max_states=args.max_states)
    write(directory / "MISSING_RING_OWNERSHIP_REFUSAL.json", {"omitted_ring_black_cell": omitted_ring,
        "solver": owner_result})
    quarter, tiny = F(1, 4), F(1, 1 << 80)
    boundary = {"closed_black_tangent_is_included": circle.circle_cell_intersects(geometry, (51, 30), quarter),
        "strictly_smaller_radius_excludes_black_tangent": not circle.circle_cell_intersects(geometry, (51, 30), quarter - tiny),
        "white_tangent_is_not_strictly_outside": not circle.circle_point_strictly_outside(geometry, (F(101, 2), 30), quarter),
        "rationally_outside_white_is_strict": circle.circle_point_strictly_outside(geometry, (F(101, 2) + tiny, 30), quarter)}
    write(directory / "EXACT_NATIVE_CIRCLE_BOUNDARY.json", {"checks": boundary,
        "pass": all(boundary.values()), "native_circle_not_chords": True,
        "predicate_control_radius_not_claimed_as_a_calibrated_source_width": True})
    upper_result = model.evaluate_vector(observed["black_cells"], observed["white_cells"], bodies,
        [exact.encode_rational(F(1))] * (bodies[0]["bounded_width_field"]["parameter_count"] + 1),
        owned_black_constraints=observed["owned_black_constraints"])
    write(directory / "OPEN_PARAMETER_UPPER_REFUSAL.json", upper_result)
    report = {"joint_field_feasible": result.get("pass"), "joint_status": result.get("status"),
        "successful_vector_exactly_rechecked": replay.get("pass"),
        "native_child_source_alias_replay": alias_result.get("pass"),
        "unauthorized_query_refused": query_result.get("pass") is False and
            "CIRCLE_QUERY_DOMAIN_INCOMPLETE" in query_result.get("reason", ""),
        "missing_original_ring_ownership_refused": owner_result.get("pass") is False,
        "strict_upper_parameter_refused": upper_result.get("pass") is False and
            upper_result.get("status") == "INVALID_OR_NONSTRICT_PARAMETER_VECTOR",
        "native_circle_exact_boundary_pass": all(boundary.values()),
        "source_unchanged": source_sha == hashlib.sha256(gray.tobytes()).hexdigest(),
        "production_source_completeness_positive_certificate": False, "adoption": "NOT_RUN"}
    report["required_refusal_and_exactness_checks_pass"] = all(report[key] for key in (
        "unauthorized_query_refused", "missing_original_ring_ownership_refused", "strict_upper_parameter_refused",
        "native_circle_exact_boundary_pass", "source_unchanged")) and (
        not result.get("pass") or replay.get("pass") is True and alias_result.get("pass") is True)
    write(directory / "RESULT.json", report)
    write(directory / "FILE_MANIFEST.json", file_manifest(directory))
    return report


def api_resource_case(args, model):
    directory = args.output / "endpoint_and_resource_contract"
    directory.mkdir()
    original = json.loads((args.output / "clean_constant/V2_MODEL.json").read_text())["fields"][0]["bounded_width_field"]
    checks = []
    for end, point in ((0, (16, 40)), (-1, (64, 40))):
        changed = model.extend_endpoint_field(original, end, point)
        checks.append({"end": end, "new_field": changed,
            "original_pieces_byte_value_preserved": changed["pieces"][:-1] == original["pieces"],
            "fixed_knots_and_observations_preserved": all(changed[key] == original[key]
                for key in ("knots", "section_observations", "parameter_count")),
            "diagnostic_not_native": changed["diagnostic_extension"]["status"] == "DIAGNOSTIC_NOT_NATIVE"})
    monotone = args.output / "clean_monotone_variable"
    fields = json.loads((monotone / "V2_MODEL.json").read_text())["fields"]
    obs = json.loads((monotone / "OBSERVATIONS.json").read_text())
    limited = model.solve_bounded_union(obs["black_cells"], obs["white_cells"], fields,
        owned_black_constraints=obs["owned_black_constraints"], max_states=1)
    write(directory / "ONE_ORACLE_BUDGET.json", limited)
    resource = limited.get("numerical_resource_bound", {})
    limited_ok = (limited.get("pass") is True or limited.get("status", "").startswith("PENDING")) and (
        not resource or resource.get("oracle_evaluations", 0) <= 1) and not limited.get("exact_family_infeasibility_proved")
    report = {"endpoint_extensions": checks,
        "endpoint_parameter_identity_preserved": all(row["original_pieces_byte_value_preserved"] and
            row["fixed_knots_and_observations_preserved"] and row["diagnostic_not_native"] for row in checks),
        "one_oracle_budget_never_claims_infeasibility": limited_ok,
        "resource_result": limited.get("status"), "source_authorization_not_established_by_api_control": True}
    write(directory / "RESULT.json", report)
    write(directory / "FILE_MANIFEST.json", file_manifest(directory))
    return report


def run(args):
    import cv2
    from app.native_objects import bounded_stroke_field as first
    from app.native_objects import bounded_stroke_field_v2 as second

    cv2.setNumThreads(1)
    before = sources(args.repo)
    declared = declarations()
    shutil.copyfile(__file__, args.output / "EXECUTED_ENTRYPOINT.py")
    for relative in before:
        destination = args.output / "EXECUTED_SOURCES" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.repo / relative, destination)
    write(args.output / "FROZEN_INPUT_DEFINITIONS.json", {"schema": SCHEMA, "declarations": declared,
        "source_size": SOURCE_SIZE, "window": WINDOW, "points": POINTS, "section_centers": SECTION_CENTERS,
        "fixed_section_half_span": 12, "case_names_do_not_determine_model_verdicts": True,
        "old_v1_and_new_v2_same_inputs": True, "development_controls_not_holdouts": True})
    write(args.output / "EXECUTION_STARTED.json", {"source_files_sha256": before,
        "arguments": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.repo, text=True).strip(),
        "python_executable": sys.executable, "new_ocr_calls": 0, "new_model_inferences": 0,
        "new_ordinary_stage": "NOT_RUN"})
    summaries = []
    for index, declaration in enumerate(declared):
        print(json.dumps({"case": declaration["name"], "stage": "FIXED_SOURCE_SECTIONS_AND_JOINT_MODEL"}), flush=True)
        try:
            result = synthetic_case(args, declaration, first, second)
        except Exception as exc:  # noqa: BLE001 - Retain every failed control and continue the frozen set.
            result = {"name": declaration["name"], "status": "CHECKPOINT_CASE_EXECUTION_ERROR",
                "type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
            write(args.output / declaration["name"] / "ERROR.json", result)
        summaries.append(result)
        write(args.output / f"PROGRESS_{index + 1:02d}.json", {"results": summaries})
        print(json.dumps(result, ensure_ascii=False), flush=True)
    conditional = conditional_case(args, first, second) if args.real_plan else {"status": "NOT_REQUESTED"}
    print(json.dumps({"case": "circle_joint_scope_and_boundary", "stage": "EXACT_NATIVE_CIRCLE_CONTROLS"}), flush=True)
    circles = circle_joint_case(args, second)
    print(json.dumps(circles), flush=True)
    api = api_resource_case(args, second)
    after = sources(args.repo)
    required = [row for row in summaries if row.get("capability_or_refusal_requirement_satisfied") is not None]
    report = {"schema": SCHEMA, "results": summaries, "conditional_real_capability": conditional,
        "circle_joint_scope_and_boundary": circles, "endpoint_and_resource_contract": api,
        "field_family_identities": {"v1": first.SCHEMA, "v2_module_current_family": second.SCHEMA},
        "source_files_sha256_before": before, "source_files_sha256_after": after, "sources_unchanged": before == after,
        "all_cases_executed": all(row.get("status") != "CHECKPOINT_CASE_EXECUTION_ERROR" for row in summaries),
        "all_required_capability_and_refusal_properties_satisfied": all(row["capability_or_refusal_requirement_satisfied"] for row in required)
            and circles["required_refusal_and_exactness_checks_pass"] and api["endpoint_parameter_identity_preserved"]
            and api["one_oracle_budget_never_claims_infeasibility"],
        "all_successful_vectors_rechecked": all(row.get("v1_vector_recheck") is not False and row.get("v2_vector_recheck") is not False for row in summaries),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "new_source_stage": "NOT_RUN", "ordinary_output": "NOT_RUN", "new_saved_dxf": "NOT_RUN", "adoption": "NOT_RUN",
        "field_feasibility_is_not_source_completeness": True,
        "refusal_witness_absence_is_not_source_acceptance": True}
    report["checkpoint_observations_complete"] = report["all_cases_executed"] and before == after
    write(args.output / "SUMMARY.json", report)
    return 0 if report["checkpoint_observations_complete"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-states", type=int, default=8192)
    parser.add_argument("--real-plan", type=Path)
    parser.add_argument("--real-source", type=Path)
    parser.add_argument("--conditional-reference", type=Path)
    args = parser.parse_args()
    args.repo, args.output = args.repo.resolve(), args.output.resolve()
    if args.output.exists():
        parser.error("Output directory must be new; failed receipts are retained.")
    if any((args.real_plan, args.real_source, args.conditional_reference)) and not all((args.real_plan, args.real_source, args.conditional_reference)):
        parser.error("Conditional real check requires all three real material arguments.")
    if args.max_states < 1:
        parser.error("max-states must be positive.")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.repo / "cad_photo_to_dxf"))
    os.environ.update(PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    args.output.mkdir(parents=True)
    try:
        return run(args)
    except Exception as exc:
        write(args.output / "EXECUTION_ERROR.json", {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()})
        raise
    finally:
        write(args.output / "FILE_MANIFEST.json", file_manifest(args.output))


if __name__ == "__main__":
    sys.exit(main())
