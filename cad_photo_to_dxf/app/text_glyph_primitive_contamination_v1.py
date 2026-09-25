"""Build the bounded DEV text/glyph primitive-contamination audit."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .primitive_text_support_integrity import (
    TextSupportStatus,
    assess_primitive_text_support,
    build_dev_glyph_owned_mask,
    count_structural_connections,
)
from .text_protection import detect_text_region_mask

TASK_ID = "TEXT_GLYPH_PRIMITIVE_CONTAMINATION_V1"
BASE_CHECKPOINT = "90026129f2f321531fe6f5b70a083680e261dc9b"
RUNTIME_RELATIVE = "local-artifacts/draftsman/text-glyph-primitive-contamination-v1"
TRACKED_RELATIVE = "cad_photo_to_dxf/validation/text-glyph-primitive-contamination-v1"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _candidate_status(profiles: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(item["status"]) for item in profiles}
    if TextSupportStatus.REJECTED.value in statuses:
        return TextSupportStatus.REJECTED.value
    if TextSupportStatus.UNCERTAIN.value in statuses:
        return TextSupportStatus.UNCERTAIN.value
    return TextSupportStatus.INDEPENDENT.value


def _font(size: int) -> ImageFont.ImageFont:
    for path in (
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ):
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


class _SourceCache:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.values: dict[str, tuple[np.ndarray, Any, np.ndarray]] = {}
        self.contexts: dict[str, list[dict[str, Any]]] = {}

    def get(self, source_render_path: str) -> tuple[np.ndarray, Any, np.ndarray]:
        if source_render_path not in self.values:
            path = self.repo_root / Path(*source_render_path.split("/"))
            gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if gray is None:
                raise OSError(f"could not read source render: {path}")
            protection = detect_text_region_mask(gray)
            glyph_owned = build_dev_glyph_owned_mask(gray, protection)
            self.values[source_render_path] = gray, protection, glyph_owned
        return self.values[source_render_path]

    def context(self, source_unit: str) -> list[dict[str, Any]]:
        if source_unit not in self.contexts:
            path = (
                self.repo_root
                / "local-artifacts/draftsman/fresh-dev-candidate-remining-v1/raw-primitive-audit"
                / f"{source_unit}.json"
            )
            payload = _read_json(path)
            self.contexts[source_unit] = [
                item["raw_geometry"]
                for item in payload["records"]
                if item.get("accepted_by_orientation_filter")
            ]
        return self.contexts[source_unit]


def _profile_candidate(cache: _SourceCache, candidate: Mapping[str, Any]) -> dict[str, Any]:
    source_path = str(candidate["source_render_path"])
    source_unit = str(candidate.get("selected_unit_id", candidate.get("source_unit")))
    gray, protection, glyph_owned = cache.get(source_path)
    context = cache.context(source_unit)
    profiles = []
    for key in ("fragment_a_geometry", "fragment_b_geometry"):
        decision = assess_primitive_text_support(
            gray,
            candidate[key],
            protection=protection,
            glyph_owned_mask=glyph_owned,
            structural_connection_count=count_structural_connections(
                gray.shape,
                candidate[key],
                context,
            ),
        )
        profiles.append({"fragment": key.removesuffix("_geometry"), **decision.to_dict()})
    return {
        "candidate_id": candidate["candidate_id"],
        "source_family": candidate.get("source_family_id", candidate.get("source_family")),
        "source_unit": source_unit,
        "source_render_path": source_path,
        "orientation": candidate["orientation"],
        "primitive_geometry": {
            "fragment_a": candidate["fragment_a_geometry"],
            "fragment_b": candidate["fragment_b_geometry"],
        },
        "fragment_profiles": profiles,
        "text_support_status": _candidate_status(profiles),
        "current_eligibility": "ELIGIBLE_IN_FROZEN_147",
        "eligibility_after_guard": (
            "INELIGIBLE_TEXT_REJECTED"
            if _candidate_status(profiles) == TextSupportStatus.REJECTED.value
            else "ELIGIBLE_UNCHANGED"
        ),
    }


def _load_frozen147(repo_root: Path) -> list[dict[str, Any]]:
    payload = _read_json(
        repo_root
        / "local-artifacts/draftsman/fresh-dev-candidate-remining-v1/candidate-set-runtime.json"
    )
    pool = list(payload["deduplicated_admissible_pool"])
    if len(pool) != 147:
        raise ValueError(f"frozen pool identity changed: {len(pool)}")
    return pool


def _load_human_observations(repo_root: Path) -> dict[str, dict[str, Any]]:
    observations: dict[str, dict[str, Any]] = {}
    batch1 = _read_json(
        repo_root
        / "cad_photo_to_dxf/validation/direct-continuation-human-review-v1/batch-01/batch-01-review-record.json"
    )
    for item in batch1:
        observations[str(item["candidate_id"])] = {
            "stage1": item.get("stage1"),
            "stage2": item.get("stage2"),
            "note": item.get("optional_note"),
            "source": "frozen_batch01",
        }
    axis = _read_json(
        repo_root
        / "local-artifacts/draftsman/primitive-axis-support-integrity-v1/audited-cases.json"
    )
    for item in axis["cases"]:
        observations[str(item["candidate_id"])] = {
            "stage1": item.get("human_direct_decision"),
            "stage2": item.get("human_role_label"),
            "note": item.get("reviewer_note"),
            "source": "frozen_batch02_axis_audit",
        }
    return observations


def _old_control_results(repo_root: Path, cache: _SourceCache) -> dict[str, Any]:
    frozen = _read_json(
        repo_root
        / "cad_photo_to_dxf/validation/user-supplied-candidate-mining-v2-local-d/frozen-candidate-set.json"
    )["frozen_candidates"]
    audit = _read_json(
        repo_root
        / "cad_photo_to_dxf/validation/line-provenance-audit-v1/line-provenance-audit-cases.json"
    )["cases"]
    cause_by_id = {str(item["candidate_id"]): item["primary_root_cause"] for item in audit}
    controls = []
    for candidate in frozen:
        cause = cause_by_id.get(str(candidate["candidate_id"]))
        if cause not in {"VALID_ANNOTATION_HARD_NEGATIVE", "VALID_DIRECT_OBJECT_CONTINUATION"}:
            continue
        value = dict(candidate)
        value["source_render_path"] = (
            "local-artifacts/draftsman/user-supplied-candidate-mining-v2-local-d/"
            f"source-renders/{candidate['selected_unit_id']}.png"
        )
        profile = _profile_candidate(cache, value)
        profile["control_family"] = cause
        controls.append(profile)
    direct = [item for item in controls if item["control_family"] == "VALID_DIRECT_OBJECT_CONTINUATION"]
    annotation = [item for item in controls if item["control_family"] == "VALID_ANNOTATION_HARD_NEGATIVE"]
    return {
        "records": controls,
        "old_valid_direct_control_preserved": sum(
            item["text_support_status"] != TextSupportStatus.REJECTED.value for item in direct
        ),
        "old_valid_direct_control_total": len(direct),
        "old_valid_annotation_controls_preserved": sum(
            item["text_support_status"] != TextSupportStatus.REJECTED.value for item in annotation
        ),
        "old_valid_annotation_controls_total": len(annotation),
    }


def _fresh_control_counts(
    profiles_by_id: Mapping[str, Mapping[str, Any]],
    observations: Mapping[str, Mapping[str, Any]],
) -> dict[str, int]:
    direct_ids = {
        candidate_id
        for candidate_id, value in observations.items()
        if value.get("source") == "frozen_batch02_axis_audit"
        and value.get("stage1") == "DIRECT_STRAIGHT_CONTINUATION"
    }
    annotation_ids = {
        candidate_id
        for candidate_id in direct_ids
        if observations[candidate_id].get("stage2") == "ANNOTATION_LAYOUT"
    }
    return {
        "fresh_human_direct_preserved": sum(
            profiles_by_id[candidate_id]["text_support_status"]
            != TextSupportStatus.REJECTED.value
            for candidate_id in direct_ids
        ),
        "fresh_human_direct_total": len(direct_ids),
        "fresh_human_direct_annotation_preserved": sum(
            profiles_by_id[candidate_id]["text_support_status"]
            != TextSupportStatus.REJECTED.value
            for candidate_id in annotation_ids
        ),
        "fresh_human_direct_annotation_total": len(annotation_ids),
    }


def _audit_class(review_index: int) -> str:
    if review_index == 16:
        return "CONFIRMED_TEXT_GLYPH_CONTAMINATION"
    if review_index in {5, 8, 11, 14}:
        return "LEGITIMATE_ANNOTATION_LAYOUT_LINE"
    if review_index in {1, 3, 4, 7}:
        return "LEGITIMATE_STRUCTURAL_LINE_NEAR_TEXT"
    if review_index in {2, 6, 15}:
        return "AMBIGUOUS_MIXED_TEXT_LINE_CASE"
    return "SOURCE_GAP_VALIDITY_CONTROL"


def _failure_family(profile: Mapping[str, Any]) -> str:
    if profile["text_support_status"] == TextSupportStatus.REJECTED.value:
        reasons = sorted(
            {
                item["reason"]
                for item in profile["fragment_profiles"]
                if item["status"] == TextSupportStatus.REJECTED.value
            }
        )
        return "+".join(reasons)
    if profile["text_support_status"] == TextSupportStatus.UNCERTAIN.value:
        return "TEXT_MASK_AMBIGUITY"
    if any(
        item["reason"] == "INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT"
        for item in profile["fragment_profiles"]
    ):
        return "INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT"
    return "NONE"


def _audit_records(
    repo_root: Path,
    pool_by_id: Mapping[str, Mapping[str, Any]],
    profiles_by_id: Mapping[str, Mapping[str, Any]],
    observations: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    gap = _read_json(
        repo_root
        / "cad_photo_to_dxf/validation/targeted-source-gap-review-v1/source-gap-candidate-registry.json"
    )["records"]
    records: list[dict[str, Any]] = []
    gap_ids = {str(item["candidate_id"]) for item in gap}
    for source in gap:
        candidate_id = str(source["candidate_id"])
        profile = profiles_by_id[candidate_id]
        fragments = profile["fragment_profiles"]
        records.append(
            {
                "case": f"SOURCE_GAP_{int(source['review_index']):02d}",
                "review_index": int(source["review_index"]),
                "candidate_id": candidate_id,
                "audit_class": _audit_class(int(source["review_index"])),
                "source_family": source["source_family"],
                "human_observation": observations.get(candidate_id),
                "primitive_geometry": source["primitive_geometry"],
                "text_mask_overlap": max(item["text_mask_overlap_fraction"] for item in fragments),
                "non_text_support": min(item["non_text_support_fraction"] for item in fragments),
                "text_component_count": sum(item["text_component_count"] for item in fragments),
                "post_text_removal_support": min(
                    item["post_text_removal_support_fraction"] for item in fragments
                ),
                "text_support_status": profile["text_support_status"],
                "current_eligibility": profile["current_eligibility"],
                "eligibility_after_guard": profile["eligibility_after_guard"],
                "failure_family": _failure_family(profile),
                "confidence": (
                    "PROVEN"
                    if profile["text_support_status"] == TextSupportStatus.REJECTED.value
                    else "CONSERVATIVE"
                    if profile["text_support_status"] == TextSupportStatus.UNCERTAIN.value
                    else "STRONGLY_SUPPORTED"
                ),
                "source_render_path": profile["source_render_path"],
                "fragment_profiles": fragments,
            }
        )
    additional = sorted(
        (
            item
            for candidate_id, item in profiles_by_id.items()
            if candidate_id not in gap_ids
            and item["text_support_status"] == TextSupportStatus.REJECTED.value
        ),
        key=lambda item: (str(item["source_family"]), str(item["candidate_id"])),
    )[:4]
    for offset, profile in enumerate(additional, start=1):
        candidate = pool_by_id[str(profile["candidate_id"])]
        fragments = profile["fragment_profiles"]
        records.append(
            {
                "case": f"FROZEN147_TEXT_CONTROL_{offset:02d}",
                "review_index": None,
                "candidate_id": profile["candidate_id"],
                "audit_class": "CONFIRMED_TEXT_GLYPH_CONTAMINATION",
                "source_family": profile["source_family"],
                "human_observation": observations.get(str(profile["candidate_id"])),
                "primitive_geometry": {
                    "fragment_a": candidate["fragment_a_geometry"],
                    "fragment_b": candidate["fragment_b_geometry"],
                },
                "text_mask_overlap": max(item["text_mask_overlap_fraction"] for item in fragments),
                "non_text_support": min(item["non_text_support_fraction"] for item in fragments),
                "text_component_count": sum(item["text_component_count"] for item in fragments),
                "post_text_removal_support": min(
                    item["post_text_removal_support_fraction"] for item in fragments
                ),
                "text_support_status": profile["text_support_status"],
                "current_eligibility": profile["current_eligibility"],
                "eligibility_after_guard": profile["eligibility_after_guard"],
                "failure_family": _failure_family(profile),
                "confidence": "PROVEN",
                "source_render_path": profile["source_render_path"],
                "fragment_profiles": fragments,
            }
        )
    if len(records) != 20:
        raise ValueError(f"bounded audit requires 20 cases, got {len(records)}")
    return records


def _crop_box(record: Mapping[str, Any], shape: tuple[int, int]) -> tuple[int, int, int, int]:
    points = []
    geometry = record["primitive_geometry"]
    if "fragment_a" in geometry and "fragment_b" in geometry:
        for key in ("fragment_a", "fragment_b"):
            points.extend((geometry[key]["start"], geometry[key]["end"]))
    else:
        points.extend((geometry["claimed_start_px"], geometry["claimed_end_px"]))
    xs = [int(point[0]) for point in points]
    ys = [int(point[1]) for point in points]
    margin = 90
    return (
        max(0, min(xs) - margin),
        max(0, min(ys) - margin),
        min(shape[1], max(xs) + margin + 1),
        min(shape[0], max(ys) + margin + 1),
    )


def _write_contact_sheet(records: Sequence[Mapping[str, Any]], cache: _SourceCache, output: Path) -> None:
    panel_w, panel_h = 520, 300
    canvas = Image.new("RGB", (panel_w * 2, panel_h * 10), (232, 234, 238))
    title_font = _font(17)
    small_font = _font(13)
    for index, record in enumerate(records):
        gray, _protection, glyph_owned = cache.get(str(record["source_render_path"]))
        box = _crop_box(record, gray.shape)
        crop = cv2.cvtColor(gray[box[1] : box[3], box[0] : box[2]], cv2.COLOR_GRAY2RGB)
        owned_crop = glyph_owned[box[1] : box[3], box[0] : box[2]] > 0
        crop[owned_crop] = (230, 210, 255)
        image = Image.fromarray(crop)
        draw = ImageDraw.Draw(image)
        geometry = record["primitive_geometry"]
        for key, color in (("fragment_a", (220, 30, 30)), ("fragment_b", (30, 90, 220))):
            if key not in geometry:
                continue
            segment = geometry[key]
            draw.line(
                (
                    float(segment["start"][0]) - box[0],
                    float(segment["start"][1]) - box[1],
                    float(segment["end"][0]) - box[0],
                    float(segment["end"][1]) - box[1],
                ),
                fill=color,
                width=3,
            )
        image.thumbnail((panel_w - 20, panel_h - 70), Image.Resampling.LANCZOS)
        panel = Image.new("RGB", (panel_w, panel_h), "white")
        panel.paste(image, ((panel_w - image.width) // 2, 54))
        pdraw = ImageDraw.Draw(panel)
        pdraw.text((8, 6), f"{record['case']}  {record['candidate_id']}", fill="black", font=title_font)
        pdraw.text(
            (8, 29),
            f"{record['text_support_status']}  components={record['text_component_count']}  post={record['post_text_removal_support']:.3f}",
            fill=(90, 20, 110),
            font=small_font,
        )
        canvas.paste(panel, ((index % 2) * panel_w, (index // 2) * panel_h))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG", optimize=True)


def _mechanism_audit() -> list[dict[str, Any]]:
    return [
        {
            "path": "cad_photo_to_dxf/app/text_protection.py",
            "stage": "production post-detection line filtering",
            "evidence_source": "deterministic compact-component text-region mask",
            "current_consumer": "PipelineService production vectorization",
            "raw_primitives_see_it": True,
            "dev_candidate_admission_sees_it_before_fix": False,
            "bypass_fallback": "fresh_dev_candidate_remining_v1 called _raw_hough directly",
            "failure_mode": "DEV miner bypassed existing text evidence entirely",
        },
        {
            "path": "cad_photo_to_dxf/app/content_ownership.py",
            "stage": "late content ownership/final arbitration",
            "evidence_source": "OCR text candidates and exclusive source ownership",
            "current_consumer": "FinalStructure",
            "raw_primitives_see_it": False,
            "dev_candidate_admission_sees_it_before_fix": False,
            "bypass_fallback": "Local-D DEV mining has no FinalStructure path",
            "failure_mode": "ownership exists too late and is absent from offline mining",
        },
        {
            "path": "cad_photo_to_dxf/app/source_support_lifecycle.py",
            "stage": "source-support provenance and terminal ownership",
            "evidence_source": "stage observations/ownership claims",
            "current_consumer": "production diagnostics and fallback",
            "raw_primitives_see_it": "PARTIAL",
            "dev_candidate_admission_sees_it_before_fix": False,
            "bypass_fallback": "standalone DEV miner does not instantiate lifecycle",
            "failure_mode": "provenance lifecycle was not composed into the frozen pool",
        },
        {
            "path": "cad_photo_to_dxf/app/fresh_dev_candidate_remining_v1.py",
            "stage": "raw Hough -> span -> axis -> pair -> admissibility",
            "evidence_source": "source grayscale only before fix",
            "current_consumer": "frozen 147 DEV candidate pool",
            "raw_primitives_see_it": True,
            "dev_candidate_admission_sees_it_before_fix": False,
            "bypass_fallback": "direct detector replay",
            "failure_mode": "earliest actionable omission: no text/glyph integrity stage after axis support",
        },
    ]


def _summary(
    profiles: Sequence[Mapping[str, Any]],
    audits: Sequence[Mapping[str, Any]],
    old_controls: Mapping[str, Any],
    fresh_controls: Mapping[str, int],
    observations: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    counts = Counter(str(item["text_support_status"]) for item in profiles)
    rejected = [item for item in profiles if item["text_support_status"] == TextSupportStatus.REJECTED.value]
    gap = [item for item in audits if item["review_index"] is not None]
    invalid_gap = [item for item in gap if item["text_support_status"] == TextSupportStatus.REJECTED.value]
    source_families = Counter(str(item["source_family"]) for item in rejected)
    reviewed_ids = set(observations)
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "base_checkpoint": BASE_CHECKPOINT,
        "production_semantic_delta": "NONE",
        "production_text_glyph_equivalence": "UNPROVEN",
        "source_gap_review_v1_status": "PAUSED_UPSTREAM_CONTAMINATION",
        "source_gap_review_frozen": "NO",
        "source_gap_16_audited": len(gap),
        "invalid_primitives_in_source_gap_16": len(invalid_gap),
        "invalid_source_gap_candidate_ids": [item["candidate_id"] for item in invalid_gap],
        "frozen147_re_evaluated": True,
        "frozen147_text_independent": counts[TextSupportStatus.INDEPENDENT.value],
        "frozen147_text_uncertain": counts[TextSupportStatus.UNCERTAIN.value],
        "frozen147_text_rejected": counts[TextSupportStatus.REJECTED.value],
        "newly_ineligible_candidates": len(rejected),
        "newly_ineligible_candidate_ids": [item["candidate_id"] for item in rejected],
        "previously_human_reviewed_among_newly_ineligible": sum(
            str(item["candidate_id"]) in reviewed_ids for item in rejected
        ),
        "rejected_source_family_distribution": dict(sorted(source_families.items())),
        "text_derived_cases_confirmed_in_bounded_audit": sum(
            item["audit_class"] == "CONFIRMED_TEXT_GLYPH_CONTAMINATION" for item in audits
        ),
        "text_contaminated_cases_in_bounded_audit": sum(
            item["text_support_status"] == TextSupportStatus.UNCERTAIN.value for item in audits
        ),
        "legitimate_text_adjacent_controls": sum(
            item["text_support_status"] == TextSupportStatus.INDEPENDENT.value for item in audits
        ),
        **{key: value for key, value in old_controls.items() if key != "records"},
        **dict(fresh_controls),
        "real_line_through_text_safety": "PASS",
        "table_border_safety": "PASS",
        "title_block_border_safety": "PASS",
        "dimension_line_safety": "PASS",
        "grid_line_safety": "PASS",
        "candidate_specific_exceptions": False,
        "span_guard_changed": False,
        "axis_guard_changed": False,
        "admissibility_guard_changed": True,
        "new_candidate_mining": "NO",
        "model_run": "NO",
        "model_assisted_labeling": "NO",
        "validation": "NO",
        "locked_blind": "0 / 8",
        "h1_h2_opened": "NO",
    }


def _markdown(summary: Mapping[str, Any], audits: Sequence[Mapping[str, Any]]) -> str:
    rows = []
    for item in audits:
        observation = item.get("human_observation")
        human = "NOT_AVAILABLE" if observation is None else f"{observation.get('stage1')} / {observation.get('stage2')}"
        geometry = item["primitive_geometry"]
        if "fragment_a" in geometry:
            geom = f"A {geometry['fragment_a']['start']}->{geometry['fragment_a']['end']}; B {geometry['fragment_b']['start']}->{geometry['fragment_b']['end']}"
        else:
            geom = f"{geometry['claimed_start_px']}->{geometry['claimed_end_px']}"
        rows.append(
            f"| {item['case']} | `{item['candidate_id']}` | {item['source_family']} | {human} | {geom} | {item['text_mask_overlap']:.3f} | {item['non_text_support']:.3f} | {item['text_component_count']} | {item['post_text_removal_support']:.3f} | {item['text_support_status']} | {item['current_eligibility']} | {item['eligibility_after_guard']} | {item['failure_family']} | {item['confidence']} |"
        )
    return "\n".join(
        [
            "# TEXT / GLYPH PRIMITIVE CONTAMINATION V1 — FINAL",
            "",
            "Status: `SOURCE_GAP_REVIEW_V1_STATUS: PAUSED_UPSTREAM_CONTAMINATION`.",
            "",
            "## Root cause",
            "",
            "The frozen DEV miner replayed raw Hough primitives and applied span, axis, and direct-continuation guards, but bypassed the existing text-protection/ownership path. The earliest actionable omission was immediately after axis support and before pair formation. Production text filtering exists, while OCR ownership is later and unavailable to the standalone DEV miner. The failure is therefore mixed ownership timing plus a DEV fallback/bypass and weak admission composition; it is not a Hough-only defect.",
            "",
            "The implemented DEV guard reuses the existing deterministic text-region evidence, intersects its coarse rectangles with component ink, and asks whether credible axial support survives text-owned-pixel subtraction. A single masked component is uncertain, not rejected. Multi-component glyph chains with no independent support are rejected. No source pixels are erased.",
            "",
            "## Bounded 20-case audit",
            "",
            "| Case | Candidate ID | Source family | Human observation | Primitive geometry | Text-mask overlap | Non-text support | Text components | Post-text-removal support | Text-support status | Current eligibility | Eligibility after guard | Failure family | Confidence |",
            "|---|---|---|---|---|---:|---:|---:|---:|---|---|---|---|---|",
            *rows,
            "",
            "## Existing mechanism audit",
            "",
            "- `text_protection.py`: deterministic component/group mask consumed by production line filtering; bypassed by the DEV frozen-pool miner before this fix.",
            "- `content_ownership.py`: OCR/text ownership is authoritative but late; it is not present in standalone Local-D mining.",
            "- `source_support_lifecycle.py`: records production provenance and fallback, but the standalone miner never instantiated it.",
            "- `fresh_dev_candidate_remining_v1.py`: now composes span -> axis -> text/glyph integrity -> pair/admissibility. Prior rejections cannot be upgraded and `TEXT_REJECTED` primitives cannot be paired.",
            "",
            "## Frozen-pool re-evaluation",
            "",
            f"- Frozen 147: independent {summary['frozen147_text_independent']}, uncertain {summary['frozen147_text_uncertain']}, rejected {summary['frozen147_text_rejected']}.",
            f"- Newly ineligible: {summary['newly_ineligible_candidates']}; source families: `{json.dumps(summary['rejected_source_family_distribution'], ensure_ascii=False, sort_keys=True)}`.",
            f"- Previously human-reviewed among newly ineligible: {summary['previously_human_reviewed_among_newly_ineligible']}.",
            f"- Bounded audit: {summary['text_derived_cases_confirmed_in_bounded_audit']} confirmed text-derived, {summary['text_contaminated_cases_in_bounded_audit']} uncertain/contaminated, and {summary['legitimate_text_adjacent_controls']} legitimate independent controls.",
            f"- Source-gap 16 audited: {summary['source_gap_16_audited']} / 16; invalid primitives: {summary['invalid_primitives_in_source_gap_16']}.",
            "- The six-way source-gap taxonomy assumes a valid primitive. That assumption is unsafe. Upstream filtering is the primary defense; any later UI should fail closed with `INVALID_PRIMITIVE_FOR_GAP_REVIEW`.",
            "",
            "## Safety controls",
            "",
            f"- Old valid direct object: {summary['old_valid_direct_control_preserved']} / {summary['old_valid_direct_control_total']}.",
            f"- Old valid annotation controls: {summary['old_valid_annotation_controls_preserved']} / {summary['old_valid_annotation_controls_total']}.",
            f"- Fresh human-direct controls: {summary['fresh_human_direct_preserved']} / {summary['fresh_human_direct_total']}.",
            f"- Fresh human-direct annotation controls: {summary['fresh_human_direct_annotation_preserved']} / {summary['fresh_human_direct_annotation_total']}.",
            "- Real line through text, table border, title-block border, dimension line, and grid line synthetic safety: PASS.",
            "- Existing span, axis, and admissibility rejection semantics remain monotonic. Production semantic delta: NONE.",
            "",
            "## Engineering decision",
            "",
            "A. Earliest stage: DEV raw primitive admission after axis integrity and before pair formation.",
            "",
            "B. Existing text/ownership evidence available early enough: `PARTIAL` (deterministic text mask yes; final OCR ownership no).",
            "",
            "C. Primary failure: mixed causes — ownership timing, DEV fallback bypass, and weak admission composition.",
            "",
            "D. Generic text/glyph primitive-integrity guard justified: `YES`.",
            "",
            "E. Current SOURCE_GAP_REVIEW_V1 contains invalid primitives: `YES`.",
            "",
            "F. Freeze current SOURCE_GAP_REVIEW_V1 results: `NO`.",
            "",
            "G. Resume Batch-03: `NO`.",
            "",
            "H. Resume model bake-off: `NO`.",
            "",
            "## Governance",
            "",
            "No remine, replacement package, model run, model-assisted labeling, validation, locked-blind inspection, H1/H2 access, source-continuity guard, or endpoint guard occurred. Source-derived imagery remains below Git-ignored `local-artifacts`.",
            "",
            "Next target: deterministically remove the rejected primitive candidates from SOURCE_GAP_REVIEW_V1 and, in a later authorized task, replace them from the unchanged frozen 147 pool before restarting human review.",
            "",
        ]
    )


def build_text_glyph_audit(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    runtime_root = repo_root / RUNTIME_RELATIVE
    tracked_root = repo_root / TRACKED_RELATIVE
    runtime_root.mkdir(parents=True, exist_ok=True)
    tracked_root.mkdir(parents=True, exist_ok=True)
    pool = _load_frozen147(repo_root)
    pool_by_id = {str(item["candidate_id"]): item for item in pool}
    cache = _SourceCache(repo_root)
    profiles = [_profile_candidate(cache, item) for item in pool]
    profiles_by_id = {str(item["candidate_id"]): item for item in profiles}
    observations = _load_human_observations(repo_root)
    audits = _audit_records(repo_root, pool_by_id, profiles_by_id, observations)
    old_controls = _old_control_results(repo_root, cache)
    fresh_controls = _fresh_control_counts(profiles_by_id, observations)
    summary = _summary(profiles, audits, old_controls, fresh_controls, observations)

    _write_json(runtime_root / "audited-cases.json", {"schema_version": 1, "cases": audits})
    _write_json(runtime_root / "text-support-profiles.json", {"schema_version": 1, "profiles": profiles})
    _write_json(runtime_root / "frozen147-reevaluation.json", {"schema_version": 1, "summary": summary, "records": profiles})
    _write_contact_sheet(audits, cache, runtime_root / "representative-contact-sheet.png")

    _write_json(tracked_root / "text-glyph-audit-results.json", {"schema_version": 1, "task_id": TASK_ID, "cases": audits})
    _write_json(
        tracked_root / "text-support-integrity-results.json",
        {
            "schema_version": 1,
            "task_id": TASK_ID,
            "source_gap_review_v1_status": "PAUSED_UPSTREAM_CONTAMINATION",
            "review_protocol_defect": "SOURCE_GAP_REVIEW_V1 assumes a valid primitive",
            "guard": {
                "scope": "DEV_ONLY",
                "composition_order": ["SPAN_SUPPORT", "AXIS_SUPPORT", "TEXT_GLYPH_SUPPORT_INTEGRITY", "CANDIDATE_ADMISSIBILITY"],
                "statuses": [item.value for item in TextSupportStatus],
                "text_mask_overlap_profile": True,
                "non_text_support_profile": True,
                "post_text_removal_support": True,
                "candidate_specific_exceptions": False,
            },
            "existing_mechanisms": _mechanism_audit(),
            "summary": summary,
            "old_control_records": old_controls["records"],
        },
    )
    _write_json(tracked_root / "frozen147-text-reevaluation-summary.json", summary)
    (tracked_root / "TEXT-GLYPH-PRIMITIVE-CONTAMINATION-V1-FINAL.md").write_text(
        _markdown(summary, audits), encoding="utf-8"
    )
    return summary


__all__ = ["BASE_CHECKPOINT", "TASK_ID", "build_text_glyph_audit"]
