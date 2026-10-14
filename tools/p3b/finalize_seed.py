"""Apply the user's completed-valid-re-review adjudication rule in a derived view."""

from collections import Counter

from audit_acceptance import audit_state
from common import atomic_json, read, read_rows, sha, write_rows
from pilot_audit import DOCS
from review_suspects import MANIFEST, LABEL_STATE, ORIGINALS, compare


def run():
    rows, new = read_rows(MANIFEST), read(LABEL_STATE)
    history = audit_state(new, rows, sha(MANIFEST), presentation_order=rows)
    if (
        not history.get("FINAL_STATE_INTERNALLY_CONSISTENT")
        or history["PRESENTATIONS_PERSISTED"] != 13
    ):
        raise ValueError("STOP: re-review state is incomplete/inconsistent")
    base = read_rows(DOCS / "formal-seed-correspondence-audit.jsonl")
    originals = read(ORIGINALS)
    if (
        sha(DOCS / "labels/formal-seed-v2-001.json")
        != originals["original_state_sha256"]
    ):
        raise ValueError("Original evidence changed")
    comparison = compare(rows, originals, new, base)
    for item in comparison["disagreements"]:
        item["historical_review_result"] = item.pop("review_result")
        item["current_resolution"] = "ADJUDICATED_RE_REVIEW_ACCEPTED"
    original_state = read(DOCS / "labels/formal-seed-v2-001.json")
    by_new = {r["sample_id"]: r for r in rows}
    effective = []
    for item in base:
        sid = item["sample_id"]
        reviewed = sid in by_new
        decision_state = new if reviewed else original_state
        nomination = decision_state["nomination_statuses"][sid]
        label = decision_state["labels"].get(sid)
        ready = nomination["status"] == "VALID_TARGET" and label is not None
        effective.append(
            {
                "sample_id": sid,
                "source_drawing_id": item["source_drawing_id"],
                "source_family_id": item["source_family_id"],
                "original_stage0": original_state["nomination_statuses"][sid],
                "original_stage1": original_state["labels"].get(sid),
                "re_review_stage0": new["nomination_statuses"].get(sid),
                "re_review_stage1": new["labels"].get(sid),
                "current_stage0": nomination["status"],
                "current_class": label["label"] if label else None,
                "current_decision_provenance": "user_authorized_complete_valid_independent_re_review"
                if reviewed
                else "accepted_original_READY_or_excluded_evidence",
                "correspondence_review_reason": item["reasons"],
                "current_review_status": "READY" if ready else "EXCLUDED",
                "training_authorized": False,
            }
        )
    ready = [r for r in effective if r["current_review_status"] == "READY"]
    classes = Counter(r["current_class"] for r in ready)
    result = {
        "TOTAL_REVIEWED": 13,
        "EXACT_AGREEMENT": comparison["EXACT_AGREEMENT"],
        "STAGE0_DISAGREEMENT": comparison["STAGE0_DISAGREEMENT"],
        "STAGE1_DISAGREEMENT": comparison["STAGE1_DISAGREEMENT"],
        "CONFIRMED_SINGLE": 0,
        "CONFIRMED_TRUE_PARALLEL": comparison["CONFIRMED_TRUE_PARALLEL"],
        "CONFIRMED_OTHER": comparison["CONFIRMED_OTHER"],
        "REVISED_TO_SINGLE": comparison["REVISED_TO_SINGLE"],
        "REVISED_TO_TRUE_PARALLEL": comparison["REVISED_TO_PARALLEL"],
        "REVISED_TO_OTHER": comparison["REVISED_TO_OTHER"],
        "REVISED_TO_AMBIGUOUS": comparison["REVISED_TO_AMBIGUOUS"],
        "REVISED_TO_X_OR_U": comparison["REVISED_TO_X_OR_U"],
        "disagreements": comparison["disagreements"],
        "FINAL_READY_SINGLE": classes["SINGLE_PHYSICAL_STROKE"],
        "FINAL_READY_TRUE_PARALLEL": classes["TRUE_PARALLEL_STRUCTURE"],
        "FINAL_READY_OTHER": classes["OTHER"],
        "FINAL_AMBIGUOUS": classes["AMBIGUOUS"],
        "FINAL_EXCLUDED": 100 - len(ready),
        "FINAL_TRAINING_READY_TOTAL": len(ready),
        "DRAWINGS": len({r["source_drawing_id"] for r in ready}),
        "SOURCE_FAMILIES": len({r["source_family_id"] for r in ready}),
        "DISPUTED_REMAINING": 0,
        "FORMAL_SEED_FINAL_STATUS": "PASS",
        "adjudication_authority": "Current user explicitly authorizes the complete and internally valid independent re-review to become the current adjudicated decision. Historical disagreement is retained, not unresolved.",
        "glyph_rule": "Character/digit/glyph/symbol ownership is OTHER even when internal strokes are parallel; never reinterpret as structural truth.",
        "original_state_sha256": sha(DOCS / "labels/formal-seed-v2-001.json"),
        "re_review_state_sha256": sha(LABEL_STATE),
        "original_manifest_sha256": sha(DOCS / "formal-seed-v2-001.jsonl"),
        "training_authorized": False,
        "model_trained": False,
    }
    if (
        classes["SINGLE_PHYSICAL_STROKE"] < 20
        or classes["TRUE_PARALLEL_STRUCTURE"] < 20
    ):
        result["FORMAL_SEED_FINAL_STATUS"] = "NEEDS_ADJUDICATION"
        raise ValueError(
            "Final structural support is insufficient; stop before validation"
        )
    write_rows(DOCS / "formal-seed-adjudicated-decisions.jsonl", effective)
    atomic_json(DOCS / "FORMAL-SEED-FINAL-STATUS.json", result)
    print(result)


if __name__ == "__main__":
    run()
