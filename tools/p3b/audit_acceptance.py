"""Read-only V2 state/history audit. Never changes human answers or opens sources."""

import argparse
import copy
import hashlib
from collections import Counter
from datetime import datetime

import jsonschema
import numpy as np
from PIL import Image

from common import LABELS, ROOT, atomic_json, digest, read, read_rows, sha
from label_ui import diverse_order
from quality import inspect
from queue_dedup import deduplicate

DOCS = ROOT / "docs/product-fix-p3b"
CACHE = ROOT.parent.parent / "image-to-cad-p3b-cache"
STATUSES = ("VALID_TARGET", "INVALID_NOMINATION", "UNCLEAR_TARGET")


def compact(label=None, nomination=None, skipped=None):
    return {
        "label": label.get("label") if label else None,
        "nomination": nomination.get("status") if nomination else None,
        "skipped": bool(skipped),
    }


def audit_state(state, rows, manifest_sha, presentation_order=None):
    """Replay every mutation/undo and compare final values and remaining undo stack."""
    errors, stack, replay = [], [], {}
    by_id = {r["sample_id"]: r for r in rows}
    ranks = {
        r["sample_id"]: i + 1
        for i, r in enumerate(
            presentation_order
            if presentation_order is not None
            else diverse_order(rows)
        )
    }
    seen, presented, direct_skips, classes_without_v = set(), set(), [], []
    zero_support_entries, nonvalid_history, corrections = [], {}, []
    cursor = None
    last_time = None
    schema = read(DOCS / "label-state-v2.schema.json")
    validator = jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )
    errors.extend("schema: " + e.message for e in validator.iter_errors(state))
    if errors:
        return {"SCHEMA_VALID": False, "INTERNAL_ERRORS": errors}
    if state["manifest_sha256"] != manifest_sha:
        errors.append("manifest binding mismatch")
    if state["revision"] != len(state["review_log"]):
        errors.append("revision does not match durable review log length")
    for i, event in enumerate(state["review_log"], 1):
        sid, action = event["sample_id"], event["action"]
        if sid not in by_id:
            errors.append(f"log {i}: unknown sample")
            continue
        now = datetime.fromisoformat(event["timestamp_utc"])
        if last_time and now < last_time:
            errors.append(f"log {i}: timestamps move backwards")
        last_time = now
        current = replay.setdefault(sid, compact())
        if action == "present":
            if event["queue_rank"] != ranks[sid]:
                errors.append(f"log {i}: wrong presentation rank")
            presented.add(sid)
            cursor = sid
            continue
        if sid not in presented:
            errors.append(f"log {i}: action before presentation")
        if action == "undo":
            if not stack:
                errors.append(f"log {i}: undo without event")
                continue
            prior = stack.pop()
            if (prior["sample_id"], prior["action"]) != (sid, event["reversed_action"]):
                errors.append(f"log {i}: undo mismatches last mutation")
            replay[sid] = copy.deepcopy(prior["previous"])
            cursor = sid
            continue
        stack.append(
            {
                "sample_id": sid,
                "action": "label" if action == "physical_class" else action,
                "previous": copy.deepcopy(current),
            }
        )
        if action == "nomination":
            if event["status"] in STATUSES[1:]:
                nonvalid_history[sid] = event["status"]
            elif sid in nonvalid_history and sid not in seen:
                corrections.append(
                    {
                        "sample_id": sid,
                        "earlier_status": nonvalid_history[sid],
                        "later_status": "VALID_TARGET",
                        "log_index": i,
                    }
                )
                seen.add(sid)
            current["nomination"] = event["status"]
            current["skipped"] = False
            if event["status"] != "VALID_TARGET":
                current["label"] = None
        elif action == "physical_class":
            if current["nomination"] != "VALID_TARGET":
                classes_without_v.append({"sample_id": sid, "log_index": i})
            metrics = by_id[sid]["quality"]["metrics"]
            geometry = by_id[sid]["candidate_geometry"]
            supported = (
                all(
                    metrics.get(p + "_SOURCE_SUPPORT_RATIO", 0) > 0
                    for p in ("A", "B")[: len(geometry)]
                )
                if geometry
                else metrics.get("TARGET_INK_PIXELS", 0) >= 4
            )
            if not supported:
                zero_support_entries.append({"sample_id": sid, "log_index": i})
            current["label"] = event["label"]
            current["skipped"] = False
        elif action == "skip":
            if current["nomination"] is None:
                direct_skips.append({"sample_id": sid, "log_index": i})
            current["skipped"] = True
    for field in ("labels", "nomination_statuses", "skipped"):
        if set(state[field]) - by_id.keys():
            errors.append(f"{field}: unknown sample IDs")
    for sid, row in by_id.items():
        label = state["labels"].get(sid)
        nomination = state["nomination_statuses"].get(sid)
        saved = compact(label, nomination, state["skipped"].get(sid))
        if saved != replay.get(sid, compact()):
            errors.append(f"{sid}: final values differ from history replay")
        for record in (label, nomination):
            if record and record["sample_sha256"] != digest(row):
                errors.append(f"{sid}: sample digest mismatch")
        if label and (not nomination or nomination["status"] != "VALID_TARGET"):
            errors.append(f"{sid}: saved class without V")
        if (
            label
            and nomination
            and label["timestamp_utc"] < nomination["timestamp_utc"]
        ):
            errors.append(f"{sid}: final class precedes final V")
        if nomination:
            decision_validator = jsonschema.Draft202012Validator(
                read(DOCS / "label-contract-v2.schema.json")
            )
            errors.extend(
                f"{sid}: completed decision schema: {error.message}"
                for error in decision_validator.iter_errors(
                    {
                        "sample_id": sid,
                        "nomination_status": nomination["status"],
                        "physical_class": label["label"] if label else None,
                        "training_authorized": False,
                    }
                )
            )
    remaining = [
        {
            "sample_id": e["sample_id"],
            "action": e["action"],
            "previous": compact(
                e["previous_label"], e["previous_nomination"], e["previous_skip"]
            ),
        }
        for e in state["events"]
    ]
    if remaining != stack:
        errors.append("remaining undo stack differs from history replay")
    for event in state["events"]:
        row = by_id.get(event["sample_id"])
        for field in ("previous_label", "previous_nomination"):
            if event[field] and row and event[field]["sample_sha256"] != digest(row):
                errors.append("undo snapshot has wrong sample digest")
    if cursor != state["cursor_sample_id"]:
        errors.append("cursor differs from history replay")
    if state["label_version"] != digest(
        {"labels": state["labels"], "nomination_statuses": state["nomination_statuses"]}
    ):
        errors.append("label version digest mismatch")
    missing = sorted(by_id.keys() - presented)
    if missing:
        errors.append("missing durable presentations")
    if classes_without_v:
        errors.append("Stage 1 entered without active prior V")
    if zero_support_entries:
        errors.append("zero source support entered Stage 1")
    counts = Counter(r["status"] for r in state["nomination_statuses"].values())
    return {
        "TOTAL_REVIEWED": len(state["nomination_statuses"]),
        **{s: counts[s] for s in STATUSES},
        "DIRECT_SKIP_WITHOUT_STAGE0": len({e["sample_id"] for e in direct_skips}),
        "STAGE1_CLASSES_PRESENT": {
            c: sum(r["label"] == c for r in state["labels"].values()) for c in LABELS
        },
        "STAGE1_CLASS_COUNT": len(state["labels"]),
        "V_WITH_STAGE1_SKIPPED": sum(
            sid in state["skipped"] and r["status"] == "VALID_TARGET"
            for sid, r in state["nomination_statuses"].items()
        ),
        "TRACEABLE_TARGET_RATE": counts["VALID_TARGET"] / len(rows) if rows else 0,
        "PRESENTATIONS_PERSISTED": len(presented),
        "PRESENTATION_LOG_ENTRIES": sum(
            e["action"] == "present" for e in state["review_log"]
        ),
        "MISSING_PRESENTATIONS": missing,
        "UNDO_LOG_ENTRIES": sum(e["action"] == "undo" for e in state["review_log"]),
        "SESSION_COUNT": len({e["session_id"] for e in state["review_log"]}),
        "X_U_LATER_CHANGED_TO_V": corrections,
        "INCONSISTENT_X_U_OVERWRITES": 0 if not errors else None,
        "STAGE1_WITHOUT_PRIOR_V": classes_without_v,
        "ZERO_SOURCE_SUPPORT_STAGE1": zero_support_entries,
        "SCHEMA_VALID": not any("completed decision schema" in e for e in errors),
        "FINAL_STATE_INTERNALLY_CONSISTENT": not errors,
        "INTERNAL_ERRORS": errors,
    }


def run():
    manifest = DOCS / "real-v2-acceptance.jsonl"
    state_path = DOCS / "labels/v2-ui-acceptance.json"
    rows, state = read_rows(manifest), read(state_path)
    result = audit_state(state, rows, sha(manifest))
    images, actual_zero = {}, []
    for row in rows:
        with Image.open(CACHE / "real-v2" / row["patch_dir"] / "gray.png") as image:
            gray = image.convert("L")
        if hashlib.sha256(gray.tobytes()).hexdigest() != row["patch_sha256"]:
            raise ValueError("Frozen crop hash mismatch")
        images[row["sample_id"]] = gray
        local = copy.deepcopy(row)
        x, y = row["source_bbox"][:2]
        local["source_bbox"] = [0, 0, 256, 256]
        for geometry in local["candidate_geometry"]:
            geometry[1] = [
                v - (x if i % 2 == 0 else y) for i, v in enumerate(geometry[1])
            ]
        if local.get("target_roi"):
            local["target_roi"][0] -= x
            local["target_roi"][1] -= y
        metrics = inspect(local, np.array(gray))["metrics"]
        if any(
            metrics.get(p + "_SOURCE_SUPPORT_RATIO", 1) == 0 for p in ("A", "B")
        ) or (
            not local["candidate_geometry"] and metrics.get("TARGET_INK_PIXELS", 0) < 4
        ):
            actual_zero.append(row["sample_id"])
    _, duplicates, duplicate_counts = deduplicate(
        rows, None, lambda r: images[r["sample_id"]]
    )
    result.update(
        state_sha256=sha(state_path),
        manifest_sha256=sha(manifest),
        split_manifest_sha256=sha(DOCS / "split-manifest.json"),
        label_version=state["label_version"],
        revision=state["revision"],
        ACTUAL_CROP_ZERO_SUPPORT_TARGETS=actual_zero,
        DUPLICATE_AUDIT={"counts": duplicate_counts, "details": duplicates},
        by_drawing=dict(Counter(r["source_drawing_id"] for r in rows)),
        by_target_type=dict(Counter(r["target_kind"] for r in rows)),
        training_authorized=False,
        validation_sources_accessed=0,
        blind_sources_accessed=0,
    )
    passed = (
        len(rows) == 30
        and result.get("TOTAL_REVIEWED") == 30
        and result.get("VALID_TARGET", 0) >= 29
        and result.get("FINAL_STATE_INTERNALLY_CONSISTENT", False)
        and not actual_zero
        and not duplicates
    )
    result["V2_UI_ACCEPTANCE"] = "PASS" if passed else "FAIL"
    atomic_json(DOCS / "v2-acceptance-audit.json", result)
    print(result)
    return result


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
