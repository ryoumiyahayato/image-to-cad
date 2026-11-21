"""Bind a local whole-wall edit to existing source ownership and old saved DXF.

No recognition, fitting, candidate generation or ownership decision is run.
All straight visible geometry is inspected, including nested INSERT members.
Previously reviewed original-pixel witnesses are checked against the input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import ezdxf
from PIL import Image


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(entity):
    if entity.has_xdata("I2CAD_NATIVE_V2"):
        return json.loads(entity.get_xdata("I2CAD_NATIVE_V2")[0].value)["id"]
    return None


def straight_segments(entity):
    if entity.dxftype() == "INSERT":
        for member in entity.virtual_entities():
            yield from straight_segments(member)
    elif entity.dxftype() == "LINE":
        yield list(entity.dxf.start)[:2], list(entity.dxf.end)[:2]
    elif entity.dxftype() == "LWPOLYLINE":
        points = list(entity.get_points("xyb"))
        for i in range(len(points) if entity.closed else len(points) - 1):
            first, second = points[i], points[(i + 1) % len(points)]
            if abs(first[2]) < 1e-12:
                yield list(first[:2]), list(second[:2])


def nearby_parallel_overlap(first, second):
    a, b = first
    c, d = second
    u = [b[i] - a[i] for i in range(2)]
    v = [d[i] - c[i] for i in range(2)]
    lu, lv = math.hypot(*u), math.hypot(*v)
    if min(lu, lv) < 1e-10:
        return None
    cosine = abs(sum(u[i] * v[i] for i in range(2)) / lu / lv)
    angle = math.degrees(math.acos(min(1.0, cosine)))
    if angle > 1.0:
        return None
    unit = [x / lu for x in u]
    projection = sorted(sum((p[i] - a[i]) * unit[i] for i in range(2)) for p in (c, d))
    overlap = [max(0.0, projection[0]), min(lu, projection[1])]
    separation = [abs((p[0] - a[0]) * unit[1] - (p[1] - a[1]) * unit[0]) for p in (c, d)]
    if overlap[1] - overlap[0] <= 1e-7 or min(separation) > 4.0:
        return None
    return {"angle_degrees": angle, "projection_overlap_px": overlap,
            "endpoint_normal_distances_px": separation}


def coordinate_distance(first, second):
    forward = max(abs(first[j][i] - second[j][i]) for j in range(2) for i in range(2))
    reverse = max(abs(first[j][i] - second[1-j][i]) for j in range(2) for i in range(2))
    return min(forward, reverse)


def audit(args):
    checkpoint = Path(args.checkpoint)
    local = Path(args.local_output)
    manifest = read(checkpoint / "result.objects.json")
    walls = read(checkpoint / "evidence/walls/wall_segments.json")
    edited = read(local / "local_edit_check.json")
    target_id = edited["target_id"]
    records = {record["id"]: record for record in manifest["objects"]}
    target = records[target_id]
    target_segments = [[m["geometry"]["start"], m["geometry"]["end"]] for m in target["geometry"]["members"]]
    prior = read(args.prior_scan)
    assert prior["target_owned_members_read_from_canonical_geometry"] == target["geometry"]["members"]
    assert digest(args.source_image) == manifest["source_sha256"]
    assert digest(checkpoint / "result.dxf") == manifest["dxf_sha256"]
    roi, scale = manifest["roi_xyxy_px"], 25.4 / manifest["dpi"]
    source = Image.open(args.source_image).convert("L")
    partitions = [row for row in walls["source_interval_partition"]
                  if any(claim["wall_id"] == target_id for claim in row["wall_claims"])]
    partition_map = {row["source_line_id"]: row for row in partitions}
    before = ezdxf.readfile(args.before)
    before_ids = {identity(e) for e in before.modelspace() if e.dxf.layer != "REVIEW"}
    assert target_id not in before_ids
    results = {}
    for variant in ("restored", "moved", "deleted"):
        path = local / ("wall_local_" + variant + ".dxf")
        assert digest(path) == edited["outputs"][variant]["sha256"]
        doc = ezdxf.readfile(path)
        entities = {identity(e): e for e in doc.modelspace()}
        source_rows = []
        for parent, row in partition_map.items():
            assert row["all_source_parameter_intervals_accounted"]
            assert not row["geometric_pixel_cutoff_used"]
            assert abs(row["length_conservation_error_px"]) < 1e-7
            remainders = [o for o in records.values()
                          if o["source_evidence"].get("parent_line_id") == parent]
            found = []
            for obj in remainders:
                interval = obj["source_evidence"].get("outside_selected_wall_source_responsibility")
                if interval is None:
                    continue
                assert obj["id"] in entities
                assert entities[obj["id"]].dxftype() == "LINE"
                for claimed in row["claimed_union_intervals_px"]:
                    assert min(interval[1], claimed[1]) - max(interval[0], claimed[0]) <= 1e-7
                found.append({"id": obj["id"], "preserved_interval_px": interval})
            assert parent not in entities, "OLD_FULL_SOURCE_LINE_STILL_VISIBLE"
            source_rows.append({"source_line_id": parent, "present_in_v84": parent in before_ids,
                                "old_full_line_visible_now": False,
                                "claimed_intervals_px": row["claimed_union_intervals_px"],
                                "independent_remainders_preserved": found})
        nearby = []
        for oid, entity in entities.items():
            if oid == target_id:
                continue
            for first_mm in straight_segments(entity):
                first = [[point[0] / scale + roi[0], roi[3] - point[1] / scale] for point in first_mm]
                for index, second in enumerate(target_segments):
                    proximity = nearby_parallel_overlap(first, second)
                    if proximity is None:
                        continue
                    obj = records[oid]
                    parent = obj["source_evidence"].get("parent_line_id")
                    assert parent in partition_map, "UNEXPLAINED_NEARBY_SOURCE_CANDIDATE"
                    interval = obj["source_evidence"]["outside_selected_wall_source_responsibility"]
                    matching = [row for row in prior["candidates"]
                                if row["target_wall_member_index"] == index
                                and coordinate_distance(first, row["member_source_endpoints"]) < 1e-6]
                    assert len(matching) == 1, "PRIOR_SOURCE_REVIEW_DOES_NOT_MATCH_ACTUAL_SAVED_GEOMETRY"
                    witness = matching[0]
                    assert witness["white_separator_samples"] > 0
                    pixels = witness["all_common_source_witnesses"]
                    for pixel in pixels:
                        assert source.getpixel(tuple(pixel["source_pixel"])) == pixel["literal_gray"]
                    nearby.append({"id": oid, "target_member": index, "geometry_source_px": first,
                                   "remaining_source_interval_px": interval, "proximity": proximity,
                                   "original_ink_witnesses_verified": len(pixels),
                                   "previous_source_review_samples": witness["sample_count"],
                                   "previous_white_separator_vetoes": witness["white_separator_samples"],
                                   "decision": "PRESERVE_INDEPENDENT_SOURCE_PREFIX_NOT_TARGET_RESIDUE"})
        results[variant] = {"sha256": digest(path), "source_partitions": source_rows,
                            "nearby_straight_candidates": nearby,
                            "target_owned_source_overlap_in_standalone_remainders_px": 0.0}
    output = {"schema": "local-wall-source-residue-binding-v1", "status": "PASS_BOUND_SOURCE_INTERVALS_AND_LOCAL_RESIDUE",
              "target_id": target_id, "v84_target_insert_count": 0,
              "v84_sha256": digest(args.before), "source_image_sha256": digest(args.source_image),
              "checkpoint_dxf_sha256": manifest["dxf_sha256"],
              "prior_source_review_sha256": digest(args.prior_scan),
              "script_sha256": digest(__file__), "variants": results,
              "new_OCR_calls": 0, "new_geometry_or_source_ownership_inference": False,
              "scope": "Actual saved local LINE/straight polyline/block geometry and existing source interval responsibility; does not resolve global neighboring-wall ownership."}
    Path(args.out).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": output["status"], "variant_count": len(results),
                      "nearby_candidates_per_variant": {k: len(v["nearby_straight_candidates"]) for k, v in results.items()}}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("checkpoint", "local-output", "before", "prior-scan", "source-image", "out"):
        parser.add_argument("--" + key, required=True)
    audit(parser.parse_args())
