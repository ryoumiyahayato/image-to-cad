"""Independent source-only eligibility audit; never imports/runs the producer.

Run comparison against completed saved manifests first. Freeze its result and
this script hash externally, then diagnose previously budget-stopped sources.
No LINE geometry, pen rendering, optimization, or source mutation is performed.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import resource
import time

import numpy as np

PEN_CODES = (5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90,
             100, 106, 120, 140, 158, 200, 211)
AUDIT_VERSION = "independent-streaming-cardinal-source-eligibility-v1"
SCOPE = "NECESSARY_SOURCE_ELIGIBILITY_ONLY_NOT_A_RECOVERY_CANDIDATE"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n")


def truth_intervals(values):
    """Plain ordered scan, independent of producer's padded-difference helper."""
    answer, first = [], None
    for index, present in enumerate(values):
        if present and first is None:
            first = index
        elif not present and first is not None:
            answer.append((first, index))
            first = None
    if first is not None:
        answer.append((first, len(values)))
    return answer


def merge(intervals):
    answer = []
    for a, b in sorted(intervals):
        if a >= b:
            continue
        if answer and a <= answer[-1][1]:
            answer[-1] = (answer[-1][0], max(b, answer[-1][1]))
        else:
            answer.append((a, b))
    return answer


def subtract(left, right):
    out = []
    right = merge(right)
    for a, b in left:
        pieces = [(a, b)]
        for c, d in right:
            next_pieces = []
            for u, v in pieces:
                if d <= u or c >= v:
                    next_pieces.append((u, v))
                else:
                    if u < c:
                        next_pieces.append((u, c))
                    if d < v:
                        next_pieces.append((d, v))
            pieces = next_pieces
        out.extend(pieces)
    return merge(out)


def intersection(left, right):
    return merge((max(a, c), min(b, d)) for a, b in left for c, d in right
                 if max(a, c) < min(b, d))


def run_rows(runs):
    out = defaultdict(list)
    for y, a, b in runs:
        out[int(y)].append((int(a), int(b)))
    return out


def canonical_runs(rows):
    return [[int(y), int(a), int(b)] for y in sorted(rows)
            for a, b in merge(rows[y])]


def combine_runs(*groups):
    rows = defaultdict(list)
    for group in groups:
        for y, a, b in group:
            rows[y].append((a, b))
    return canonical_runs(rows)


def subtract_runs(left, right):
    right_rows = run_rows(right)
    return canonical_runs({y: subtract(v, right_rows.get(y, []))
                           for y, v in run_rows(left).items()})


def band_runs(axis, normal, station_intervals):
    lo, hi = normal
    if axis == "horizontal":
        return [[y, a, b] for y in range(lo, hi) for a, b in station_intervals]
    return [[y, lo, hi] for a, b in station_intervals for y in range(a, b)]


def parent_at_stations(parent_runs, axis, intervals):
    if axis == "horizontal":
        return [[y, u, v] for y, a, b in parent_runs
                for u, v in intersection([(a, b)], intervals)]
    return [[y, a, b] for y, a, b in parent_runs
            if any(u <= y < v for u, v in intervals)]


def points(runs):
    return {(y, x) for y, a, b in runs for x in range(a, b)}


def source_ledgers(row, parent_runs):
    """Construct compact run ledgers arithmetically; no per-band tile masks."""
    axis, normal = row["axis"], row["normal_interval"]
    exclusive = [i["source_station_range"] for i in row["exclusive_intervals"]]
    retired = [pair for i in row["exclusive_intervals"]
               for pair in i["retired_station_intervals"]]
    fitting = band_runs(axis, normal, [row["station_interval"]])
    exclusive_runs = band_runs(axis, normal, exclusive)
    retired_runs = band_runs(axis, normal, merge(retired))
    shared = parent_at_stations(parent_runs, axis, row["shared_station_intervals"])
    guarded = parent_at_stations(parent_runs, axis, row["guard_station_intervals"])
    guard = subtract_runs(guarded, shared)
    collar = subtract_runs(exclusive_runs, retired_runs)
    answer = {
        "native_fitting_band_runs_y_x0_x1": fitting,
        "native_exclusive_source_runs_y_x0_x1": exclusive_runs,
        "native_shared_core_source_runs_y_x0_x1": shared,
        "native_guard_source_runs_y_x0_x1": guard,
        "native_exclusive_collar_source_runs_y_x0_x1": collar,
        "native_mandatory_retained_source_runs_y_x0_x1": combine_runs(shared, guard, collar),
        "native_retired_source_runs_y_x0_x1": retired_runs,
    }
    interval_ledgers = []
    for item in row["exclusive_intervals"]:
        full = band_runs(axis, normal, [item["source_station_range"]])
        inner = band_runs(axis, normal, item["retired_station_intervals"])
        interval_ledgers.append({
            "native_source_runs_y_x0_x1": full,
            "native_retired_source_runs_y_x0_x1": inner,
            "native_retained_source_runs_y_x0_x1": subtract_runs(full, inner),
        })
    return answer, interval_ledgers


def enumerate_source(parent, scale, dpi):
    """Contains-run queries, 1D interval arithmetic, no producer budget expansion."""
    parent_runs = [[y, a, b] for y, pixels in enumerate(parent)
                   for a, b in truth_intervals(pixels)]
    rows = []
    stats = {"section_keys": 0, "singleton_section_keys_not_proposed": 0,
             "candidate_key_columns": 0, "raw_bands": 0}
    for axis in ("horizontal", "vertical"):
        source = parent if axis == "horizontal" else parent.T
        station_count = source.shape[1]
        column_runs = [truth_intervals(source[:, x]) for x in range(station_count)]
        starts = [[a for a, _ in runs] for runs in column_runs]
        occurrences = defaultdict(list)
        for x, runs in enumerate(column_runs):
            for interval in runs:
                occurrences[interval].append(x)
        stats["section_keys"] += len(occurrences)
        for normal in sorted(occurrences):
            exact_positions = occurrences[normal]
            if len(exact_positions) < 2:
                stats["singleton_section_keys_not_proposed"] += 1
                continue
            stats["candidate_key_columns"] += station_count
            lo, hi = normal
            full = []
            for x, runs in enumerate(column_runs):
                index = bisect_right(starts[x], lo)-1
                full.append(index >= 0 and runs[index][1] >= hi)
            exact_set = set(exact_positions)
            width = float(hi-lo)
            code = min(PEN_CODES, key=lambda c: (abs(c*dpi*scale/2540.-width), c))
            pen_width = code*dpi*scale/2540.
            collar = max(2.*scale, width+math.sqrt(.5)*scale,
                         pen_width+math.sqrt(.5)*scale)
            guard_steps = math.ceil(collar+width/2.)
            for start, stop in truth_intervals(full):
                stats["raw_bands"] += 1
                # The following coordinates are source positions, not fit violations.
                exclusive = [(a+start, b+start) for a, b in truth_intervals(
                    [x in exact_set for x in range(start, stop)])]
                shared = subtract([(start, stop)], exclusive)
                guard = merge((max(0, a-guard_steps), min(station_count, b+guard_steps))
                              for a, b in shared)
                intervals = []
                for a, b in exclusive:
                    lower = a+width/2.+collar
                    upper = b-1-width/2.-collar
                    first = max(a, min(b, math.floor(lower)+1))
                    last = max(first, min(b, math.ceil(upper)))
                    inner = subtract([(first, last)], guard)
                    n = sum(v-u for u, v in inner)
                    effective = max(0., float(n-1))
                    length_mm = effective*25.4/(dpi*scale)
                    aspect = effective/width
                    if len(inner) != 1:
                        reason = "NO_CONTIGUOUS_EXCLUSIVE_INTERIOR"
                    elif n < 12:
                        reason = "FEWER_THAN_12_CONTINUOUS_NATIVE_SECTIONS"
                    elif length_mm < 2.:
                        reason = "EXCLUSIVE_INTERIOR_SHORTER_THAN_2MM"
                    elif aspect < 8.:
                        reason = "EXCLUSIVE_INTERIOR_ASPECT_BELOW_8"
                    else:
                        reason = "SOURCE_INTERVAL_ELIGIBLE"
                    intervals.append({
                        "source_station_range": [a, b],
                        "retired_station_intervals": [list(x) for x in inner],
                        "independent_native_cross_sections": n,
                        "effective_length_native_px": effective,
                        "effective_length_mm": length_mm,
                        "effective_length_width_ratio": aspect,
                        "reason": reason,
                    })
                edge_shift = abs(pen_width-width)/(2.*scale)
                if not shared:
                    reason = "NO_SHARED_SUPERSET_CORE"
                elif len(exclusive) < 2:
                    reason = "FEWER_THAN_TWO_EXCLUSIVE_INTERVALS"
                elif width < .5*scale or width > 4.*dpi*scale/100.:
                    reason = "SOURCE_WIDTH_OUTSIDE_R13_RANGE"
                elif edge_shift > .25:
                    reason = "STANDARD_PEN_WIDTH_SHIFT"
                elif any(i["reason"] != "SOURCE_INTERVAL_ELIGIBLE" for i in intervals):
                    reason = "INELIGIBLE_EXCLUSIVE_INTERVAL"
                else:
                    reason = "SOURCE_BAND_ELIGIBLE"
                rows.append({
                    "band_id": len(rows)+1, "axis": axis,
                    "normal_interval": list(normal), "station_interval": [start, stop],
                    "source_width_native_px": width, "source_span_native_px": stop-start,
                    "exclusive_intervals": intervals,
                    "shared_station_intervals": [list(x) for x in shared],
                    "guard_station_intervals": [list(x) for x in guard],
                    "lineweight_hundredth_mm": int(code), "native_pen_width_px": pen_width,
                    "maximum_pen_edge_shift_work_px": edge_shift,
                    "collar_native_px": collar, "guard_steps_native": int(guard_steps),
                    "source_precheck_reason": reason, "source_selected_before_fit": False,
                })
    eligible = [r for r in rows if r["source_precheck_reason"] == "SOURCE_BAND_ELIGIBLE"]
    eligible.sort(key=lambda r: (-r["source_span_native_px"], r["axis"],
                                r["normal_interval"], r["station_interval"]))
    consumed, retained = set(), set()
    for rank, row in enumerate(eligible, 1):
        ledgers, _ = source_ledgers(row, parent_runs)
        retiring = points(ledgers["native_retired_source_runs_y_x0_x1"])
        keep = points(ledgers["native_mandatory_retained_source_runs_y_x0_x1"])
        row["source_selection_rank"] = rank
        if retiring & (consumed | retained) or keep & consumed:
            row["source_precheck_reason"] = "SOURCE_FIXED_CANDIDATE_CONFLICT"
        else:
            row["source_selected_before_fit"] = True
            consumed |= retiring
            retained |= keep
    return rows, stats, parent_runs


def load_verified_inputs(input_root, meta):
    path = input_root/meta["input"]
    if digest(path) != meta["input_sha256"]:
        raise ValueError("Input archive SHA mismatch")
    with np.load(path, allow_pickle=False) as archive:
        arrays = {key: archive[key].copy() for key in archive.files}
    for name, desc in meta["arrays"].items():
        array = arrays[name]
        if (hashlib.sha256(array.tobytes()).hexdigest() != desc["sha256"]
                or list(array.shape) != desc["shape"] or str(array.dtype) != desc["dtype"]):
            raise ValueError("Input array binding mismatch: "+name)
    if any(meta["production_guards"].values()):
        raise ValueError("This diagnostic does not override protected/current/claimed guards")
    scale = int(meta["native_scale"])
    component = arrays["component"]
    native = arrays["native_gray"]
    parent = np.repeat(np.repeat(component, scale, axis=0), scale, axis=1) & (native == 0)
    return parent, arrays, {
        "input_sha256": digest(path), "arrays": meta["arrays"],
        "native_parent_pixels_sha256": hashlib.sha256(parent.tobytes()).hexdigest(),
        "native_parent_pixels": int(parent.sum()), "native_shape": list(parent.shape),
    }


def project_saved(saved):
    """Only source decisions are read; no geometric pen outcomes used."""
    omitted = {
        "native_fitting_band_runs_y_x0_x1", "native_exclusive_source_runs_y_x0_x1",
        "native_shared_core_source_runs_y_x0_x1", "native_guard_source_runs_y_x0_x1",
        "native_exclusive_collar_source_runs_y_x0_x1",
        "native_mandatory_retained_source_runs_y_x0_x1", "native_retired_source_runs_y_x0_x1",
    }
    out = {k: v for k, v in saved.items() if k not in omitted}
    out["exclusive_intervals"] = [
        {k: v for k, v in item.items() if not k.endswith("_runs_y_x0_x1")}
        for item in saved["exclusive_intervals"]]
    return out


def aggregate(rows):
    return {
        "complete_enumerated_bands": len(rows),
        "source_precheck_reasons": dict(sorted(Counter(
            r["source_precheck_reason"] for r in rows).items())),
        "exclusive_interval_reasons_all_bands": dict(sorted(Counter(
            i["reason"] for r in rows for i in r["exclusive_intervals"]).items())),
        "exclusive_interval_reasons_two_interval_shared_bands": dict(sorted(Counter(
            i["reason"] for r in rows
            if r["shared_station_intervals"] and len(r["exclusive_intervals"]) >= 2
            for i in r["exclusive_intervals"]).items())),
        "two_interval_shared_bands": sum(bool(r["shared_station_intervals"])
                                       and len(r["exclusive_intervals"]) >= 2 for r in rows),
        "necessary_eligible_bands": sum(r["source_precheck_reason"] == "SOURCE_BAND_ELIGIBLE"
                                       for r in rows),
        "source_selected_bands": sum(r["source_selected_before_fit"] for r in rows),
        "best_exclusive_interval_native_sections": max(
            (i["independent_native_cross_sections"] for r in rows
             for i in r["exclusive_intervals"]), default=0),
        "best_exclusive_interval_mm": max(
            (i["effective_length_mm"] for r in rows for i in r["exclusive_intervals"]),
            default=0.),
    }


def run_case(meta, prior, args, reference):
    started = time.perf_counter()
    parent, arrays, bindings = load_verified_inputs(Path(args.inputs), meta)
    prior_path = Path(args.results)/prior["result_path"]
    if digest(prior_path) != prior["result_sha256"]:
        raise ValueError("Saved producer result SHA mismatch")
    old = json.loads(prior_path.read_text())
    old_source = old.get("native_source_runs_y_x0_x1")
    rows, stats, parent_runs = enumerate_source(parent, int(meta["native_scale"]), float(meta["dpi"]))
    difference = []
    if old_source is not None and old_source != parent_runs:
        difference.append({"kind": "native_parent_runs"})
    result = {
        "schema": AUDIT_VERSION, "scope": SCOPE,
        "page": meta["page"], "name": meta["name"],
        "producer_result_sha256": prior["result_sha256"],
        "producer_original_reason": prior["reason"],
        "source_bindings": bindings, "enumeration_statistics": stats,
        **aggregate(rows),
        "producer_run_count": 0, "numeric_geometry_fit_calls": 0,
        "source_threshold_changes": False, "producer_budget_changes": False,
        "source_mutations": 0,
    }
    if reference:
        manifest = old["source_proposal_manifest"]
        if old["source_proposed_bands"] != manifest["bands"]:
            difference.append({"kind": "saved_manifest_alias_mismatch"})
        if len(rows) != len(manifest["bands"]):
            difference.append({"kind": "band_count", "actual": len(rows),
                               "saved": len(manifest["bands"])})
        if stats != manifest["budget"]:
            difference.append({"kind": "enumeration_statistics", "actual": stats,
                               "saved": manifest["budget"]})
        source_fields = 0
        for row, saved in zip(rows, manifest["bands"]):
            projected = project_saved(saved)
            if row != projected:
                keys = sorted(k for k in set(row) | set(projected)
                              if row.get(k) != projected.get(k))
                difference.append({"kind": "source_descriptor", "band_id": row["band_id"],
                                   "fields": keys})
            ledger, interval_ledgers = source_ledgers(row, parent_runs)
            for key, actual in ledger.items():
                source_fields += 1
                if actual != saved[key]:
                    difference.append({"kind": "source_runs", "band_id": row["band_id"],
                                       "field": key})
            for i, (actual, expected) in enumerate(zip(interval_ledgers, saved["exclusive_intervals"])):
                for key, value in actual.items():
                    source_fields += 1
                    if value != expected[key]:
                        difference.append({"kind": "exclusive_source_runs",
                                           "band_id": row["band_id"], "interval_index": i,
                                           "field": key})
        result.update(reference_equivalence_passed=not difference,
                      source_run_fields_compared=source_fields,
                      source_manifest_sha256=old["proposal_manifest_sha256"])
    else:
        result["source_band_descriptors"] = rows
        result["necessary_eligible_source_domains"] = [
            {"descriptor": row, "ledgers": source_ledgers(row, parent_runs)[0]}
            for row in rows if row["source_precheck_reason"] == "SOURCE_BAND_ELIGIBLE"]
        result["diagnostic_conclusion"] = (
            "EXCLUDED_BY_FROZEN_SOURCE_NECESSARY_CONDITIONS"
            if not result["necessary_eligible_bands"]
            else "NECESSARY_SOURCE_CONDITIONS_ONLY_FIT_AND_ADOPTION_UNDECIDED")
    result["differences"] = difference
    result["source_input_arrays_unchanged"] = all(
        hashlib.sha256(arrays[name].tobytes()).hexdigest() == desc["sha256"]
        for name, desc in meta["arrays"].items())
    result["elapsed_seconds"] = time.perf_counter()-started
    result["process_peak_rss_kib"] = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    result["rss_scope"] = "PROCESS_HIGH_WATER_MARK_INCLUDING_PREVIOUS_CASES"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("compare", "budget"), required=True)
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--results", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--freeze")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    input_manifest = Path(args.inputs)/"manifest.json"
    results_summary = Path(args.results)/"summary.json"
    source_meta = json.loads(input_manifest.read_text())
    summary = json.loads(results_summary.read_text())
    script_hash = digest(__file__)
    binding = {
        "audit_script_sha256": script_hash, "input_manifest_sha256": digest(input_manifest),
        "producer_summary_sha256": digest(results_summary),
    }
    mapping = {(r["page"], r["name"]): r for r in source_meta["rows"]}
    if args.phase == "compare":
        chosen = [r for r in summary["rows"] if r["reason"] == "NO_CARDINAL_SHARED_CORE_TRACK_PASSED"]
        if len(chosen) != 44:
            raise ValueError("Expected exactly 44 saved complete source manifests")
    else:
        if not args.freeze:
            raise ValueError("Comparison freeze is required before budget diagnosis")
        frozen = json.loads(Path(args.freeze).read_text())
        if any(frozen[k] != v for k, v in binding.items()):
            raise ValueError("Frozen binding differs")
        compare_path = output/"reference_comparison.json"
        if digest(compare_path) != frozen["reference_comparison_sha256"]:
            raise ValueError("Comparison artifact changed after freeze")
        comparison = json.loads(compare_path.read_text())
        if comparison["cases"] != 44 or not comparison["all_reference_equivalent"]:
            raise ValueError("All 44 source comparisons must pass")
        chosen = [r for r in summary["rows"] if r["reason"] == "SOURCE_BAND_BUDGET"]
        if len(chosen) != 5:
            raise ValueError("Expected exactly five retained producer budget abstentions")
        with (output/"budget_run_started.json").open("x") as handle:
            json.dump({"started_utc": datetime.now(timezone.utc).isoformat(), **binding}, handle)
    start = time.perf_counter()
    reports = []
    for old in chosen:
        meta = mapping[(old["page"], old["name"])]
        report = run_case(meta, old, args, args.phase == "compare")
        name = f'{args.phase}_{old["page"]}_{old["name"]}.json'
        dump(output/name, report)
        reports.append({
            "page": old["page"], "name": old["name"], "file": name, "sha256": digest(output/name),
            **{k: report[k] for k in (
                "complete_enumerated_bands", "source_precheck_reasons",
                "exclusive_interval_reasons_two_interval_shared_bands",
                "two_interval_shared_bands", "necessary_eligible_bands",
                "source_selected_bands", "elapsed_seconds", "process_peak_rss_kib")},
            "reference_equivalence_passed": report.get("reference_equivalence_passed"),
            "differences": report["differences"],
            "diagnostic_conclusion": report.get("diagnostic_conclusion"),
        })
        print(json.dumps(reports[-1], ensure_ascii=False), flush=True)
    final = {
        "schema": AUDIT_VERSION, "scope": SCOPE, "phase": args.phase, **binding,
        "cases": len(reports), "rows": reports,
        "elapsed_seconds": time.perf_counter()-start,
        "process_peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        "producer_run_count": 0, "numeric_geometry_fit_calls": 0,
        "producer_budget_changes": False, "source_threshold_changes": False,
        "source_mutations": 0,
        "all_reference_equivalent": all(r["reference_equivalence_passed"] for r in reports)
                                   if args.phase == "compare" else None,
        "necessary_eligible_bands": sum(r["necessary_eligible_bands"] for r in reports),
        "all_observed_bindings_unchanged": (
            digest(__file__) == script_hash and digest(input_manifest) == binding["input_manifest_sha256"]
            and digest(results_summary) == binding["producer_summary_sha256"]),
    }
    dump(output/("reference_comparison.json" if args.phase == "compare" else "budget_diagnosis.json"), final)
    if not final["all_observed_bindings_unchanged"]:
        raise SystemExit(3)
    if args.phase == "compare" and not final["all_reference_equivalent"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

