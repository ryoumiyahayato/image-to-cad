"""Plot original pixels and actual saved finite geometry without reconstruction.

All private source coordinates come from the input reports. Probe zoom and the
displayed endpoint are evaluation locators derived from the frozen source
differences; neither is supplied to the responsibility classifier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import matplotlib
import numpy as np
from PIL import Image

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _image(ax, gray, bounds, *, grid=False):
    x0, y0, x1, y1 = bounds
    left, top = max(0, math.floor(x0)), max(0, math.floor(y0))
    right, bottom = min(gray.shape[1], math.ceil(x1)), min(gray.shape[0], math.ceil(y1))
    ax.imshow(gray[top:bottom, left:right], cmap="gray", vmin=0, vmax=255,
              interpolation="nearest", extent=(left - 0.5, right - 0.5, bottom - 0.5, top - 0.5))
    ax.set_xlim(x0 - 0.5, x1 - 0.5)
    ax.set_ylim(y1 - 0.5, y0 - 0.5)
    ax.set_aspect("equal")
    ax.tick_params(labelsize=8)
    if grid:
        ax.set_xticks(np.arange(math.ceil(x0) - 0.5, x1, 1), minor=True)
        ax.set_yticks(np.arange(math.ceil(y0) - 0.5, y1, 1), minor=True)
        ax.grid(which="minor", color="#8a8a8a", linewidth=0.35, alpha=0.55)
        ax.tick_params(which="minor", bottom=False, left=False)


def _geometry(ax, geometry, color, *, dashed=False, width=1.1, endpoints=True):
    if geometry.get("unsupported_reason") or any(geometry.get("bulges", [])):
        return
    points = np.asarray(geometry.get("points", []), float)
    if len(points) < 2:
        return
    if geometry.get("closed"):
        points = np.vstack((points, points[0]))
    ax.plot(points[:, 0], points[:, 1], color=color, linewidth=width,
            linestyle="--" if dashed else "-", alpha=0.95)
    if endpoints and not geometry.get("closed"):
        ax.scatter(points[[0, -1], 0], points[[0, -1], 1], s=25,
                   facecolors="white", edgecolors=color, linewidths=1, zorder=5)


def _residual(ax, endpoint):
    for group in endpoint.get("unassigned_source_groups", []):
        points = np.asarray(group["pixels"])
        color = "#d55e00" if group["observation"] == "OBSERVABLE_UNASSIGNED_CONTINUATION" else "#df9a00"
        ax.scatter(points[:, 0], points[:, 1], s=60, marker="s", facecolors="none",
                   edgecolors=color, linewidths=1.1, zorder=6)


def _observation_short(value):
    return {"CAP_OR_JUNCTION_COMPATIBLE": "cap / junction compatible",
            "SOURCE_BOUNDARY_COMPETITION": "boundary competition",
            "OBSERVABLE_UNASSIGNED_CONTINUATION": "observable unassigned ink",
            "SOURCE_UNRESOLVED_INSUFFICIENT_ISOLATED_WIDTH": "insufficient isolated width"}.get(value, value)


def _actual_figure(args, summary):
    gray = np.asarray(Image.open(args.actual_source).convert("L"))
    report = _read(args.actual_report)
    geometries = _read(args.actual_geometries)
    targets = set(report["target_object_ids"])
    rows = [row for row in geometries["geometries"] if row["object_id"] in targets]
    rows.sort(key=lambda row: min(point[0] for point in row["points"]))
    colors = dict(zip((row["object_id"] for row in rows), ("#009e73", "#cc79a7", "#0072b2", "#d55e00")))
    bounds = report["source_binding"]["roi_xyxy"]
    fig = plt.figure(figsize=(20, 13.0), layout="constrained")
    grid = fig.add_gridspec(2, 4, height_ratios=[1.25, 1])
    raw_ax, saved_ax = fig.add_subplot(grid[0, :2]), fig.add_subplot(grid[0, 2:])
    _image(raw_ax, gray, bounds)
    raw_ax.set_title("A source: original grayscale pixels", fontsize=14)
    _image(saved_ax, gray, bounds)
    for row in geometries["geometries"]:
        if row["object_id"] not in targets:
            _geometry(saved_ax, row, "#888888", width=0.7, endpoints=False)
    for row in rows:
        _geometry(saved_ax, row, colors[row["object_id"]], width=1.6)
    saved_ax.set_title("Actual saved A DXF: finite centerlines and endpoints", fontsize=14)
    result_rows = []
    for index, row in enumerate(rows):
        points = np.asarray(row["points"], float)
        span = np.ptp(points, axis=0)
        end = int(points[-1, 0] < points[0, 0]) if span[0] > span[1] else int(points[-1, 1] > points[0, 1])
        endpoint = next(e for e in report["endpoints"] if e["object_id"] == row["object_id"] and e["end"] == end)
        x, y = endpoint["point_px"]
        local = [math.floor(x) - 12, math.floor(y) - 12, math.floor(x) + 13, math.floor(y) + 13]
        ax = fig.add_subplot(grid[1, index])
        _image(ax, gray, local, grid=True)
        for other in rows:
            _geometry(ax, other, colors[other["object_id"]], width=1.2)
        _residual(ax, endpoint)
        ax.scatter([x], [y], s=75, facecolors="none", edgecolors="#000000", linewidths=1.3, zorder=7)
        observation = endpoint.get("observation", endpoint["status"])
        ax.set_title(f"{row['object_id'][-12:]} / end {end}\n{_observation_short(observation)}", fontsize=10)
        residual_count = sum(g["pixel_count"] for g in endpoint.get("unassigned_source_groups", []))
        notes = [f"Unassigned forward cells: {residual_count}"]
        if endpoint.get("context_width_unresolved_ids"):
            notes.append("Neighbor width unresolved: no tail ownership claim")
        if observation == "SOURCE_BOUNDARY_COMPETITION":
            excess = max(g["maximum_distance_outside_all_measured_envelopes_px"] for g in endpoint["unassigned_source_groups"])
            notes.append(f"Model excess {excess:.4f} px; no hard rejection")
        if endpoint["status"] == "SOURCE_UNRESOLVED_INSUFFICIENT_ISOLATED_WIDTH":
            notes.append("No cap decision from inadequate width samples")
        ax.set_xlabel("\n".join(notes), fontsize=9)
        result_rows.append({"object_id": row["object_id"], "end": end,
                            "observation": observation, "overall_endpoint_status": endpoint["status"],
                            "unassigned_forward_pixel_count": residual_count})
    unsupported_length = sum(r.get("uncovered_positive_length_px", 0) for r in report["geometry_support"])
    overlap_count = len(report["positive_length_overlaps"])
    unknown_bounds = sum(row.get("coverage_valid") is not True and bool(row.get("unsupported_reason"))
                         for row in geometries["geometries"])
    fig.suptitle(f"Issue 60 independent raw audit — actual saved A: {report['summary']['status']}\n"
                 f"Unsupported positive source length: {unsupported_length:g} px; positive duplicates: {overlap_count}; "
                 "raw observations do not prove exclusive ownership",
                 fontsize=15)
    fig.get_layout_engine().set(rect=(0, 0.055, 1, 0.95))
    fig.text(0.02, 0.015,
             "Grid lines mark pixel boundaries at half-integer coordinates. Colored circles are actual finite endpoints. "
             "Orange outlines mark measured residual source cells.\n"
             f"{unknown_bounds} uncertified context bounds remain a limitation. Residual windows with unmeasured "
             "neighbor width do not prove a missing target tail.", fontsize=10)
    path = args.out / "FROZEN_A_RAW_SAVED_EVIDENCE.png"
    fig.savefig(path, dpi=100)
    plt.close(fig)
    summary["actual_A"] = {
        "source_file_sha256": _sha(args.actual_source), "saved_dxf_sha256": geometries["dxf_sha256"],
        "saved_reader_sha256": geometries["independent_reader_sha256"],
        "raw_auditor_sha256": report["execution"]["module_sha256"],
        "actual_member_count": len(geometries["geometries"]), "target_count": len(targets),
        "actual_point_contact_count": len(report["pair_contacts"]),
        "positive_length_overlap_count": len(report["positive_length_overlaps"]),
        "positive_unsupported_source_length_px": unsupported_length,
        "white_hole_pixel_counts": [r["pixel_count"] for r in report["white_holes"]],
        "summary": report["summary"], "displayed_endpoints": result_rows,
        "figure": path.name,
    }


def _probe_figure(args, summary):
    run = _read(args.probe_output / "SUMMARY.json")
    freeze = _read(args.probe_output / "RUN_FREEZE.json")
    baseline_geometries = _read(args.probe_output / "baseline" / "ACTUAL_SAVED_GEOMETRIES.json")
    baseline_report = _read(args.probe_output / "baseline" / "RAW_BASELINE_GEOMETRY_COUNTERFACTUAL.json")
    baseline = np.asarray(Image.open(args.probe_sources / "baseline" / "source.png").convert("L"))
    sources, differences = {}, []
    for row in run["results"]:
        gray = np.asarray(Image.open(args.probe_sources / row["name"] / "source.png").convert("L"))
        sources[row["name"]] = gray
        ys, xs = np.nonzero(gray != baseline)
        if len(xs):
            differences.append(np.column_stack((xs, ys)))
    changed = np.vstack(differences)
    locator = np.mean(changed, axis=0)
    focus = min(baseline_report["endpoints"], key=lambda e: math.dist(e["point_px"], locator))
    focus_key = (focus["object_id"], focus["end"])
    low, high = changed.min(axis=0), changed.max(axis=0)
    bounds = [int(low[0] - 7), int(low[1] - 10), int(high[0] + 8), int(high[1] + 5)]
    rows = [row for row in baseline_geometries["geometries"] if row["object_id"] in baseline_geometries["target_object_ids"]]
    fig, axes = plt.subplots(2, 4, figsize=(19, 13), layout="constrained")
    summaries = []
    for ax, row in zip(axes.ravel(), run["results"]):
        name = row["name"]
        report = _read(args.probe_output / name / "RAW_BASELINE_GEOMETRY_COUNTERFACTUAL.json")
        endpoint = next(e for e in report["endpoints"] if (e["object_id"], e["end"]) == focus_key)
        actual = _read(args.probe_output / name / "ACTUAL_SAVED_GEOMETRIES.json")
        gray = sources[name]
        _image(ax, gray, bounds, grid=True)
        for geometry in rows:
            _geometry(ax, geometry, "#0072b2", dashed=row["produced_target_count"] == 0, width=1.1)
        _residual(ax, endpoint)
        point = endpoint["point_px"]
        if "window_radius_px" in endpoint:
            ax.add_patch(Circle(point, endpoint["window_radius_px"], fill=False, linewidth=0.7,
                                linestyle=":", edgecolor="#777777"))
        observation = endpoint.get("observation", endpoint["status"])
        label = _observation_short(observation)
        ax.set_title(name.replace("_", " ") + "\n" + label, fontsize=11)
        residual = sum(g["pixel_count"] for g in endpoint.get("unassigned_source_groups", []))
        excess = max([g["maximum_distance_outside_all_measured_envelopes_px"]
                      for g in endpoint.get("unassigned_source_groups", [])], default=0.0)
        actual_count = row["produced_target_count"]
        ink_count = len(endpoint.get("forward_4_connected_ink_pixels", []))
        ax.set_xlabel(f"Saved targets: {actual_count}; skeleton same: {row['skeleton_identical_to_baseline']}\n"
                      f"Forward ink: {ink_count}; unassigned: {residual}; excess: {excess:.3f} px\n"
                      + ("Solid = this variant's actual saved geometry" if actual_count
                         else "Dashed = baseline counterfactual; no variant targets"), fontsize=9)
        summaries.append({"name": name, "source_file_sha256": row["source_file_sha256"],
                          "saved_dxf_sha256": actual["dxf_sha256"],
                          "saved_target_count": actual_count,
                          "skeleton_identical_to_baseline": row["skeleton_identical_to_baseline"],
                          "actual_target_geometry_identical_to_baseline": row["actual_target_geometry_identical_to_baseline"],
                          "focus_observation": observation,
                          "forward_original_connected_pixels": ink_count,
                          "unassigned_pixel_count": residual,
                          "maximum_upper_envelope_excess_px": excess,
                          "maximum_forward_source_center_extent_px": endpoint.get("maximum_forward_source_center_extent_px"),
                          "actual_saved_summary": row["actual_saved_raw_summary"],
                          "actual_saved_scope": row["actual_saved_scope"],
                          "focus_scope": "RAW_VARIANT_VS_BASELINE_ACTUAL_SAVED_FINITE_GEOMETRY",
                          "variant_new_geometry_adoption_inferred_from_counterfactual": False})
    fig.suptitle("Eight predeclared sources: fresh A generation, actual DXF cold read, independent raw pixels\n"
                 "Finite baseline geometry tests cap / boundary / visible continuation; drawing order remains unknown",
                 fontsize=14)
    fig.get_layout_engine().set(rect=(0, 0.055, 1, 0.95))
    fig.text(0.02, 0.015,
             "Original source.png files are shown independently; no image pixels were changed. Grid lines are half-integer pixel boundaries.\n"
             "Orange outlines = unassigned raw cells under the frozen width family. Dotted circle = bounded endpoint observation window. "
             "Compatible caps do not certify unique ownership.", fontsize=10)
    path = args.out / "EIGHT_FRESH_SOURCE_PROBES.png"
    fig.savefig(path, dpi=100)
    plt.close(fig)
    summary["eight_probes"] = {
        "saved_reader_sha256": freeze["saved_reader_sha256"],
        "raw_auditor_sha256": freeze["raw_auditor_sha256"],
        "runner_sha256": freeze["runner_sha256"],
        "declared_variants_sha256": freeze["declared_variants_sha256"],
        "each_source_rebuilt_graph_owner_and_actual_saved_dxf": True,
        "display_locator_derived_from_original_source_differences_not_used_by_auditor": True,
        "focus_object_id": focus_key[0], "focus_end": focus_key[1],
        "results": summaries, "figure": path.name,
        "exact_declared_contact_diagnostics": [
            {"declaration": row["declaration"],
             "finite_host_distance_diagnostics": row["finite_host_distance_diagnostics"],
             "actual_endpoint_source": row["actual_endpoint_source"],
             "status": row["status"],
             "limitation": "A tiny binary64 near-contact in original black pixels does not "
                           "establish a visible white gap; coordinates were not snapped."}
            for row in baseline_report["attachment_declaration_checks"]
            if row["status"] != "EXACT_ENDPOINT_CONTACT_OBSERVED"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actual-source", type=Path, required=True)
    parser.add_argument("--actual-report", type=Path, required=True)
    parser.add_argument("--actual-geometries", type=Path, required=True)
    parser.add_argument("--probe-sources", type=Path, required=True)
    parser.add_argument("--probe-output", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for filename in ("FROZEN_A_RAW_SAVED_EVIDENCE.png", "EIGHT_FRESH_SOURCE_PROBES.png",
                     "INDEPENDENT_RAW_ACCEPTANCE_SUMMARY.json"):
        if (args.out / filename).exists():
            raise FileExistsError(args.out / filename)
    summary = {"schema": "issue60-independent-raw-evidence-summary-v1", "new_ocr_calls": 0,
               "new_model_calls": 0, "figure_script_sha256": _sha(__file__),
               "private_source_coordinates_not_for_public_repository": True}
    _actual_figure(args, summary)
    _probe_figure(args, summary)
    with (args.out / "INDEPENDENT_RAW_ACCEPTANCE_SUMMARY.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({"out": str(args.out), "figures": [summary["actual_A"]["figure"],
                                                         summary["eight_probes"]["figure"]]}))


if __name__ == "__main__":
    main()
