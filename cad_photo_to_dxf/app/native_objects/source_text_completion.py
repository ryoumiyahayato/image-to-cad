"""Continue finite source-bound text queues without repeating recognition.

This is a new producer. The frozen v7/v8 recognition and acceptance producers
are not modified. A historical observation becomes usable evidence only after
its original bytes, unmodified source crop, engine/configuration and applicable
word positions have been verified again. Old failures remain in their files.
The 24-item limit is a batch size, not permission to discard the remaining
frozen quarter-region queue. No new crop search or expected string is used.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from .evidence_paths import relative_evidence_path
import shutil
import time

from . import text_regions as base, text_line_domains as domains
from . import text_block_rescue as blocks, cross_engine_text as cross
from . import independent_recognizer as independent
from . import text_confirmation as confirmation_module
from . import text_context_ownership as context_ownership
from .contracts import validate_text_regions
from .execution import check_cancel


POLICY = {
    "version": "source-bound-finite-queue-completion-v1",
    "batch_size": 24,
    "new_crop_search": False,
    "old_complete_regions_immutable": True,
    "source_pixels_modified": False,
    "existing_acceptance_thresholds_changed": False,
    "same_source_configuration_counted_once": True,
    "prior_failed_decisions_preserved": True,
}


def _digest(value):
    return cross._digest(value)


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".pending")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _spec(image, crop, psm, dpi):
    x0, y0, x1, y1 = crop
    return {
        "crop_xyxy_px": list(crop),
        "psm": int(psm),
        "crop_array_sha256": base.source_array_sha256(image[y0:y1, x0:x1]),
        "pixel_scale": [1, 1],
        "source_pixels_modified": False,
        "language": "eng",
        "recognition_dpi": int(dpi),
        "external_white_padding_px": 0,
        "padding_replaces_source_pixels": False,
    }


class BoundObservations:
    """Content-addressed raw evidence, including existing incomplete attempts."""

    def __init__(self, image, output, source_sha, dpi):
        self.image, self.output = image, Path(output)
        self.source_sha, self.dpi = source_sha, int(dpi)
        self.rows, self.by_path, self.aliases = {}, {}, []
        self.model_rows = {}
        self.scope_evidence = domains.ScopeObservationEvidence(self.output)
        self.new_tesseract_calls = self.new_model_calls = 0
        self.engine = None

    def ingest(self, raw):
        from PIL import Image
        import numpy as np

        raw = Path(raw).resolve()
        if str(raw) in self.by_path:
            return self.by_path[str(raw)]
        meta_path, png = raw.with_suffix(".json"), raw.with_suffix(".png")
        meta = _read(meta_path)
        spec = meta["specification"]
        if meta.get("status") != "COMPLETED" or meta.get("tsv_sha256") != base._sha(
            raw
        ):
            raise ValueError("COMPLETION_RAW_TSV_HASH_OR_STATUS:" + str(raw))
        if not png.is_file() or meta.get("image_sha256") != base._sha(png):
            raise ValueError("COMPLETION_RAW_INPUT_PNG_HASH:" + str(png))
        box = list(spec["crop_xyxy_px"])
        if not base._inside(box, [0, 0, self.image.shape[1], self.image.shape[0]]):
            raise ValueError("COMPLETION_RAW_CROP_OUTSIDE_SOURCE")
        x0, y0, x1, y1 = box
        crop = self.image[y0:y1, x0:x1]
        if base.source_array_sha256(crop) != spec["crop_array_sha256"]:
            raise ValueError("COMPLETION_RAW_SOURCE_PIXELS_MISMATCH")
        if (
            spec.get("source_pixels_modified")
            or spec.get("pixel_scale") != [1, 1]
            or spec.get("padding_replaces_source_pixels")
            or spec.get("language") != "eng"
            or spec.get("recognition_dpi") != self.dpi
        ):
            raise ValueError("COMPLETION_RAW_CONFIGURATION_NOT_FROZEN")
        padding = int(spec.get("external_white_padding_px", 0))
        with Image.open(png) as im:
            actual = np.asarray(im.convert("L"))
        expected = np.pad(crop, padding, constant_values=255) if padding else crop
        if not np.array_equal(actual, expected):
            raise ValueError("COMPLETION_RECOGNITION_PNG_NOT_ORIGINAL_CROP")
        command = meta.get("command", [])
        for flag, value in (
            ("--psm", str(spec["psm"])),
            ("--dpi", str(self.dpi)),
            ("-l", "eng"),
            ("--oem", "1"),
        ):
            if flag not in command or command[command.index(flag) + 1] != value:
                raise ValueError("COMPLETION_ENGINE_COMMAND_CONFIG_MISMATCH:" + flag)
        if not str(meta.get("engine_version", "")).startswith("tesseract "):
            raise ValueError("COMPLETION_ENGINE_IDENTITY_MISSING")
        key = base._observation_context_key(spec)
        observation_key = base.raw_observation_key(meta)
        if (
            key in self.rows
            and self.rows[key]["meta"]["tsv_sha256"] != meta["tsv_sha256"]
        ):
            raise ValueError("COMPLETION_SAME_SOURCE_CONFIG_DIFFERENT_RAW_RESULT")
        origin = [
            box[0] - padding,
            box[1] - padding,
            box[2] + padding,
            box[3] + padding,
        ]
        context = "bound-" + key[:16]
        words = base._parse_tsv(raw.read_text(encoding="utf-8"), origin, context, spec["psm"])
        provenance = {
            **base.raw_observation_provenance(meta),
            "source_sha256": self.source_sha,
            "specification": spec,
            "raw_tsv_sha256": meta["tsv_sha256"],
            "metadata_sha256": base._sha(meta_path),
            "recognition_input_sha256": meta["image_sha256"],
            "engine_command": command,
            "engine_version": meta["engine_version"],
            "raw_text_unchanged": True,
            "original_source_bytes_rechecked": True,
        }
        for number, word in enumerate(words):
            word.update(
                id=context + "-" + str(number),
                observation_key=observation_key,
                observation_provenance=provenance,
            )
        row = {
            "key": key,
            "observation_key": observation_key,
            "raw": str(raw),
            "meta": meta,
            "words": words,
            "context_id": context,
            "provenance": provenance,
        }
        if key in self.rows:
            self.aliases.append(
                {
                    "path": str(raw),
                    "canonical_path": self.rows[key]["raw"],
                    "observation_key": observation_key,
                    "extra_vote": False,
                }
            )
        else:
            self.rows[key] = row
            self.scope_evidence.register(words)
        self.by_path[str(raw)] = key
        return key

    def scan(self, root):
        root = Path(root)
        for stage in ("text", "text_domain_recovery", "text_block_rescue"):
            for directory in ("discovery_ocr", "local_ocr"):
                for path in sorted((root / stage / directory).glob("*.tsv")):
                    self.ingest(path)
        for path in sorted((self.output / "local_ocr").glob("*.tsv")):
            self.ingest(path)
        for path in sorted(
            (root / "cross_engine_text/model_observations").glob("*.json")
        ):
            self.ingest_model(path, root / "cross_engine_text")
        for path in sorted((self.output / "model_observations").glob("*.json")):
            self.ingest_model(path, self.output)

    def ingest_model(self, path, root):
        from PIL import Image
        import numpy as np

        record = _read(path)
        crop = record["context"]["crop_xyxy_px"]
        x0, y0, x1, y1 = crop
        actual = base.source_array_sha256(self.image[y0:y1, x0:x1])
        if (
            actual != record["source_array_sha256"]
            or actual != record["raw_model_output"]["input_array_sha256"]
        ):
            raise ValueError("COMPLETION_MODEL_SOURCE_HASH_MISMATCH")
        png = (Path(root) / record["source_png"]).resolve()
        if base._sha(png) != record["source_png_sha256"]:
            raise ValueError("COMPLETION_MODEL_PNG_HASH_MISMATCH")
        with Image.open(png) as im:
            if not np.array_equal(
                np.asarray(im.convert("L")), self.image[y0:y1, x0:x1]
            ):
                raise ValueError("COMPLETION_MODEL_PNG_NOT_ORIGINAL_CROP")
        identity = _read(Path(root) / "model_identity.json")
        if (
            identity.get("model_sha256") != independent.MODEL_SHA256
            or _digest(identity) != record["model_identity_sha256"]
        ):
            raise ValueError("COMPLETION_MODEL_IDENTITY_MISMATCH")
        key = _digest(
            {
                "source_sha256": self.source_sha,
                "crop": crop,
                "crop_sha256": actual,
                "model_sha256": independent.MODEL_SHA256,
            }
        )
        if key != record["observation_key"]:
            receipt = record.get("raw_observation_cache")
            if not receipt or record.get("source_context_key") != key:
                raise ValueError("COMPLETION_MODEL_CONFIGURATION_KEY_MISMATCH")
            from .observation_cache import digest, model_spec

            original, tensor = independent.prepare_model_input(self.image[y0:y1, x0:x1])
            actual_key = digest(model_spec(original, tensor, identity))
            if (
                record["observation_key"] != actual_key
                or receipt.get("key") != actual_key
            ):
                raise ValueError("COMPLETION_MODEL_RAW_OBSERVATION_KEY_MISMATCH")
        record = copy.deepcopy(record)
        record["source_png"] = relative_evidence_path(png, self.output)
        if key in self.model_rows:
            if _digest(record["raw_model_output"]) != _digest(
                self.model_rows[key]["raw_model_output"]
            ):
                raise ValueError("COMPLETION_SAME_MODEL_CONTEXT_DIFFERENT_OUTPUT")
        self.model_rows[key] = record

    def alternative(self, key, box, previous_role=None):
        row = self.rows[key]
        meta, raw = row["meta"], Path(row["raw"])
        words = copy.deepcopy(row["words"])
        relative = relative_evidence_path(raw, self.output)
        return {
            "context_id": row["context_id"],
            "psm": meta["specification"]["psm"],
            "crop_xyxy_px": list(meta["specification"]["crop_xyxy_px"]),
            "status": "COMPLETED",
            "raw_tsv": relative,
            "observation_key": row["observation_key"],
            "observation_provenance": row["provenance"],
            "raw_artifact": {
                "path": relative,
                "sha256": meta["tsv_sha256"],
                "status": "SAVED_RAW_TSV",
            },
            "evidence_role": "current_candidate",
            "upstream_evidence_role": previous_role,
            "evidence_rebinding": "raw/source/config verified; all current source and word gates rerun",
            "words": base._select_line(words, box),
            "all_words": words,
        }

    def request(self, crop, psm, progress):
        specification = _spec(self.image, crop, psm, self.dpi)
        key = base._observation_context_key(specification)
        if key not in self.rows:
            name = "source-" + key
            _, meta = base._ocr(
                self.image,
                crop,
                psm,
                self.output / "local_ocr",
                name,
                progress,
                padding_px=0,
                dpi=self.dpi,
            )
            self.new_tesseract_calls += int(
                meta.get("command_executed_for_this_request", True)
            )
            self.ingest(self.output / "local_ocr" / (name + ".tsv"))
        return key

    def request_model(self, context, region_id, labels, roi, slices, model_path):
        from PIL import Image

        crop = context["crop_xyxy_px"]
        x0, y0, x1, y1 = crop
        pixels = self.image[y0:y1, x0:x1]
        crop_hash = base.source_array_sha256(pixels)
        key = _digest(
            {
                "source_sha256": self.source_sha,
                "crop": crop,
                "crop_sha256": crop_hash,
                "model_sha256": independent.MODEL_SHA256,
            }
        )
        if key in self.model_rows:
            result = copy.deepcopy(self.model_rows[key])
            # Recheck source geometry in the current effective input.
            result["source_domain_audit"] = domains.inspect_source_domain(
                labels, roi, crop, component_slices=slices
            )
            return result
        if self.engine is None:
            self.engine = independent.IndependentRecognizer(model_path)
            _atomic(self.output / "model_identity.json", self.engine.identity)
        rawdir = self.output / "model_observations"
        rawdir.mkdir(exist_ok=True)
        png = rawdir / (key + ".png")
        Image.fromarray(pixels).save(png)
        raw = self.engine.recognize(pixels)
        if raw.get("input_array_sha256") != crop_hash:
            raise ValueError("COMPLETION_MODEL_INPUT_CHANGED")
        observation = copy.deepcopy(getattr(self.engine, "last_observation", {}))
        receipt = observation.get("raw_observation_cache") or {}
        result = {
            **observation,
            "observation_key": receipt.get("key", key),
            "source_context_key": key,
            "region_id": region_id,
            "context": context,
            "source_array_sha256": crop_hash,
            "source_png": relative_evidence_path(png, self.output),
            "source_png_sha256": base._sha(png),
            "raw_model_output": raw,
            "model_identity_sha256": _digest(self.engine.identity),
            "source_domain_audit": domains.inspect_source_domain(
                labels, roi, crop, component_slices=slices
            ),
            "source_case_expected_text_read": False,
            "source_pixels_modified": False,
        }
        _atomic(rawdir / (key + ".json"), result)
        self.model_rows[key] = result
        self.new_model_calls += int(
            observation.get("model_inference_executed_for_this_request", True)
        )
        return copy.deepcopy(result)


def freeze_queue(text_data, evidence_root):
    """Use only already proposed crops/configurations, excluding completed rows."""
    root = Path(evidence_root)
    line = _read(root / "text_domain_recovery/selection.json")
    block = _read(root / "text_block_rescue/policy_and_selection.json")
    model = _read(root / "cross_engine_text/policy_and_selection.json")
    by_id = {r["id"]: r for r in text_data["regions"]}
    pending = {rid for rid, r in by_id.items() if not r["complete"]}
    selected = set(line["selected_region_ids"])
    line_queue = [
        r
        for r in line["all_region_decisions"]
        if r["eligible"]
        and r["region_id"] not in selected
        and r["region_id"] in pending
    ]
    line_queue.sort(
        key=lambda r: (
            -r["pollution"]["score"],
            -r["anchor_line"]["context_support"],
            r["region_id"],
        )
    )
    block_queue = [
        r for r in block["omitted"] if any(rid in pending for rid in r["region_ids"])
    ]
    selected = set(model["selected_region_ids"])
    model_queue = [
        r
        for r in model["all_region_decisions"]
        if r["eligible"]
        and r["region_id"] not in selected
        and not r["control_only"]
        and r["region_id"] in pending
    ]
    model_queue.sort(
        key=lambda r: (
            not r["enclosed"],
            r["bbox_xyxy_px"][1],
            r["bbox_xyxy_px"][0],
            r["region_id"],
        )
    )
    queue = [
        {"stage": "rebind", "region_id": r["id"]}
        for r in sorted(
            (r for r in text_data["regions"] if not r["complete"]),
            key=lambda r: (r["bbox_xyxy_px"][1], r["bbox_xyxy_px"][0], r["id"]),
        )
    ]
    queue += [
        {"stage": "line", "region_id": r["region_id"], "plan": r} for r in line_queue
    ]
    queue += [
        {"stage": "block", "region_ids": r["region_ids"], "plan": r}
        for r in block_queue
    ]
    queue += [
        {"stage": "model", "region_id": r["region_id"], "plan": r} for r in model_queue
    ]
    for number, row in enumerate(queue):
        row["queue_index"] = number
        row["batch_index"] = number // POLICY["batch_size"]
    return queue, {
        "line_remaining_records": len(line_queue),
        "line_aliases_not_extra_recognition": sum(
            r.get("not_attempted_reason")
            == "SAME_SOURCE_DOMAIN_AND_CONFIGURATION_ALREADY_SELECTED"
            for r in line_queue
        ),
        "block_remaining_groups": len(block_queue),
        "model_remaining_pending_regions": len(model_queue),
        "line_Tesseract_request_upper_bound_before_dedup": sum(
            len(r["fixed_psm"]) for r in line_queue
        ),
        "block_Tesseract_request_upper_bound_before_dedup": sum(
            len(r["passes"]) for r in block_queue
        ),
        "model_request_upper_bound_before_dedup": sum(
            len(r["contexts"]) for r in model_queue
        ),
        "old_complete_controls_not_repeated": True,
    }


def _associated_keys(text_data, upstream, root, store):
    result = {r["id"]: set() for r in text_data["regions"]}

    def ingest(region, directory):
        if region["id"] not in result:
            raise ValueError("COMPLETION_UNBOUND_REGION_ID")
        for alt in region.get("completeness_evidence", {}).get("alternatives", []):
            artifact = alt.get("raw_artifact", {})
            raw = (Path(directory) / (artifact.get("path") or alt["raw_tsv"])).resolve()
            if artifact.get("sha256") and base._sha(raw) != artifact["sha256"]:
                raise ValueError("COMPLETION_REGION_RAW_BINDING_MISMATCH")
            key = store.ingest(raw)
            spec = store.rows[key]["meta"]["specification"]
            if (
                list(alt["crop_xyxy_px"]) != spec["crop_xyxy_px"]
                or alt["psm"] != spec["psm"]
            ):
                raise ValueError("COMPLETION_REGION_RAW_CONFIGURATION_MISMATCH")
            if (
                alt.get("observation_key")
                and alt["observation_key"] != store.rows[key]["observation_key"]
            ):
                raise ValueError("COMPLETION_REGION_OBSERVATION_IDENTITY_MISMATCH")
            result[region["id"]].add(key)

    for r in text_data["regions"]:
        # Unchanged upstream regions retain their explicit per-region root.
        # Both artifact.path and raw_tsv belong to that producer's directory.
        # Never infer a developer's old folder or take a same-name substitute.
        rr = copy.deepcopy(r)
        directory = Path(upstream).parent
        region_root = directory / text_data.get("region_evidence_roots", {}).get(
            r["id"], "."
        )
        ingest(rr, region_root)
    for path in sorted(
        (Path(root) / "text_domain_recovery/region_recoveries").glob("*.json")
    ):
        row = _read(path)
        ingest(row["new"], path.parent.parent)
    for path in sorted(
        (Path(root) / "text_block_rescue/region_attempts").glob("*.json")
    ):
        row = _read(path)
        if row.get("candidate"):
            ingest(row["candidate"], path.parent.parent)
    return result


def evaluate_bound_region(
    old,
    keys,
    store,
    image,
    roi,
    glyphs,
    labels,
    slices,
    extra_reasons=(),
    source_domain=None,
):
    """Rerun the unchanged text and source gates; no recognition is performed."""
    alternatives = [
        store.alternative(k, old["bbox_xyxy_px"], "historical_or_current_verified_raw")
        for k in sorted(keys)
    ]
    # Preserve the original discovery conflict/prefix witnesses as well as
    # associated local observations. Rebinding must not erase a disagreement.
    original_keys = set(keys) | {
        k for k, row in store.rows.items() if "discovery_ocr" in Path(row["raw"]).parts
    }
    originals = [w for k in sorted(original_keys) for w in store.rows[k]["words"]]
    scope_exclusions = []
    if source_domain and source_domain.get("glyph_neighbor_separation"):
        originals, scope_exclusions = domains.scope_words_to_source_domain(
            originals, source_domain, labels, roi, evidence=store.scope_evidence
        )
        for alternative in alternatives:
            selected, excluded = domains.scope_words_to_source_domain(
                alternative["words"],
                source_domain,
                labels,
                roi,
                evidence=store.scope_evidence,
            )
            alternative["words"] = selected
            alternative["source_scope_excluded_raw_words"] = excluded
    seed = {
        "id": old["id"],
        "bbox_xyxy_px": old["bbox_xyxy_px"],
        "enclosure": copy.deepcopy(old.get("enclosure")),
        "origin": "source_verified_finite_completion",
        "seed_observation_ids": old.get("discovery_observation_ids", []),
        "glyph_labels": [],
        "discovery_strings": sorted(
            {old.get("text", "")}
            | {cross._raw_text(a["words"]) for a in alternatives if a["words"]}
        ),
    }
    if source_domain and source_domain.get("glyph_neighbor_separation"):
        seed["bbox_xyxy_px"] = source_domain["glyph_neighbor_separation"][
            "glyph_core_box"
        ]
        seed["discovery_strings"] = sorted(
            {cross._raw_text(a["words"]) for a in alternatives if a["words"]}
        )
    candidate = base._complete_region(
        seed, alternatives, originals, image, roi, glyphs, labels
    )
    reasons, boundary, clean = set(extra_reasons), [], set()
    if not old.get("enclosure"):
        for alternative in alternatives:
            crop = list(alternative["crop_xyxy_px"])
            inspection = domains.inspect_source_domain(
                labels, roi, crop, component_slices=slices
            )
            box = candidate["bbox_xyxy_px"]
            row_domain = {
                "bbox_xyxy_px": [
                    crop[0],
                    max(crop[1], box[1] - 2),
                    crop[2],
                    min(crop[3], box[3] + 2),
                ],
                "bounded_scan_has_no_white_stop": False,
                "bounded_prefix_scan_has_no_white_stop": False,
            }
            unread, local = domains._unread_boundary_ink(image, candidate, row_domain)
            local = sorted(set(local + inspection["unresolved_reasons"]))
            if not local:
                clean.add(alternative["observation_key"])
            boundary.append(
                {
                    "observation_key": alternative["observation_key"],
                    "actual_OCR_crop_xyxy_px": crop,
                    "source_domain": inspection,
                    "row_audit_strip": row_domain,
                    "unread_source": unread,
                    "unresolved_reasons": local,
                }
            )
        if len(clean) < 2:
            reasons.add("BLOCK_CONTEXT_LACKS_TWO_COMPLETE_CURRENT_SOURCE_DOMAINS")
            reasons.update(why for row in boundary for why in row["unresolved_reasons"])
    candidate["unresolved_reasons"] = sorted(
        set(candidate["unresolved_reasons"]) | reasons
    )
    candidate["complete"] = bool(
        candidate["words"] and not candidate["unresolved_reasons"]
    )
    candidate["status"] = (
        "TEXT_PROPOSAL_PENDING_SOURCE_REVIEW"
        if candidate["complete"]
        else "UNRESOLVED_TEXT_REGION"
    )
    candidate["source_completion_evidence"] = {
        "prior_region_digest": _digest(old),
        "rebound_observation_keys": sorted(keys),
        "current_source_boundary_checks": boundary,
        "distinct_complete_source_domains": sorted(clean),
        "source_or_confidence_gates_relaxed": False,
        "prior_unresolved_reasons_preserved": old["unresolved_reasons"],
    }
    if source_domain and source_domain.get("glyph_neighbor_separation"):
        candidate["source_completion_evidence"]["glyph_neighbor_separation"] = (
            source_domain["glyph_neighbor_separation"]
        )
        candidate["source_completion_evidence"][
            "raw_observations_excluded_from_current_scope"
        ] = scope_exclusions
    candidate["retained_unassigned_old_context"] = copy.deepcopy(
        old.get("retained_unassigned_old_context")
        or {
            "bbox_xyxy_px": old.get("inspection_bbox_xyxy_px", old["bbox_xyxy_px"]),
            "compact_source_ink_mask": old["compact_source_ink_mask"],
            "meaning": "prior unknown source retained; no source erasure authorized",
        }
    )
    return candidate


def refine_source_text_completion(
    image,
    text_data,
    output_dir,
    *,
    source_sha,
    upstream_path,
    evidence_root,
    dpi,
    progress_callback=None,
    completed_ocr_checkpoint=None,
    model_path=None,
    run_remaining=True,
):
    """Pipeline entry. Resume only this producer/input/plan; never old decisions.

    evidence_root is the verified task evidence directory containing text,
    text_domain_recovery, text_block_rescue and cross_engine_text. All outputs
    belong to output_dir. run_remaining=False is an explicitly labelled no-OCR
    rebind diagnostic; a production continuation must use its default True.
    """
    import numpy as np
    import cv2
    from PIL import Image
    from scipy.ndimage import find_objects

    started, cpu = time.perf_counter(), time.process_time()
    image = np.asarray(image)
    if image.dtype != np.uint8 or image.ndim != 2:
        raise TypeError("COMPLETION_REQUIRES_ORIGINAL_UINT8_GRAYSCALE")
    roi, upstream, root, output = (
        list(text_data["roi_xyxy_px"]),
        Path(upstream_path),
        Path(evidence_root),
        Path(output_dir),
    )
    validate_text_regions(text_data, image.shape, roi)
    if _digest(_read(upstream)) != _digest(text_data):
        raise ValueError("COMPLETION_UPSTREAM_NOT_SAVED_INPUT")
    source_array_hash = base.source_array_sha256(image)
    if source_array_hash != text_data["source_array_sha256"]:
        raise ValueError("COMPLETION_SOURCE_ARRAY_MISMATCH")
    for stage in ("text_domain_recovery", "text_block_rescue", "cross_engine_text"):
        saved = _read(root / stage / "completed_stages.json")
        if (
            saved["source_array_sha256"] != source_array_hash
            or saved["source_sha256"] != source_sha
            or saved["roi_xyxy_px"] != roi
        ):
            raise ValueError("COMPLETION_STAGE_SOURCE_BINDING_MISMATCH:" + stage)
    queue, counts = freeze_queue(text_data, root)
    if not run_remaining:
        queue = [row for row in queue if row["stage"] == "rebind"]
    dependencies = [
        {"module": m.__name__, "sha256": base._sha(m.__file__)}
        for m in (base, domains, blocks, cross, independent, confirmation_module, context_ownership)
    ]
    manifest = {
        "schema": "finite-source-completion-v1",
        "policy": POLICY,
        "producer_sha256": base._sha(__file__),
        "dependencies": dependencies,
        "source_sha256": source_sha,
        "source_array_sha256": source_array_hash,
        "upstream_sha256": base._sha(upstream),
        "roi_xyxy_px": roi,
        "dpi": int(dpi),
        "run_remaining": bool(run_remaining),
        "queue": queue,
        "queue_sha256": _digest(queue),
        "counts": counts,
        "frozen_plan_files": {
            (root / p).relative_to(root).as_posix(): base._sha(root / p)
            for p in (
                "text_domain_recovery/selection.json",
                "text_block_rescue/policy_and_selection.json",
                "cross_engine_text/policy_and_selection.json",
            )
        },
    }
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("COMPLETION_REQUIRES_NEW_OUTPUT_OR_EXPLICIT_RESUME_COPY")
    output.mkdir(parents=True, exist_ok=True)
    if completed_ocr_checkpoint is not None:
        if _read(Path(completed_ocr_checkpoint) / "frozen_manifest.json") != manifest:
            raise ValueError("COMPLETION_RESUME_PRODUCER_SOURCE_OR_QUEUE_CHANGED")
        shutil.copytree(completed_ocr_checkpoint, output, dirs_exist_ok=True)
    _atomic(output / "frozen_manifest.json", manifest)
    store = BoundObservations(image, output, source_sha, dpi)
    store.scan(root)
    keys = _associated_keys(text_data, upstream, root, store)
    bound_count = len(store.rows)
    _atomic(
        output / "raw_source_binding.json",
        {
            "unique_verified_Tesseract_observations": bound_count,
            "verified_existing_model_observations": len(store.model_rows),
            "aliases": store.aliases,
            "observations": [
                {
                    "key": k,
                    "raw": r["raw"],
                    "tsv_sha256": r["meta"]["tsv_sha256"],
                    "specification": r["meta"]["specification"],
                    "engine_version": r["meta"]["engine_version"],
                }
                for k, r in sorted(store.rows.items())
            ],
            "all_original_pixels_and_raw_outputs_verified": True,
        },
    )
    planned_tess, planned_model = set(), set()
    for item in queue:
        if item["stage"] == "line":
            plan = item["plan"]
            calls = [(plan["domain"]["bbox_xyxy_px"], psm) for psm in plan["fixed_psm"]]
        elif item["stage"] == "block":
            calls = [(p["crop_xyxy_px"], p["psm"]) for p in item["plan"]["passes"]]
        else:
            calls = []
        planned_tess.update(
            base._observation_context_key(_spec(image, crop, psm, dpi))
            for crop, psm in calls
        )
        if item["stage"] == "model":
            for context in item["plan"]["contexts"]:
                crop = context["crop_xyxy_px"]
                x0, y0, x1, y1 = crop
                planned_model.add(
                    _digest(
                        {
                            "source_sha256": source_sha,
                            "crop": crop,
                            "crop_sha256": base.source_array_sha256(
                                image[y0:y1, x0:x1]
                            ),
                            "model_sha256": independent.MODEL_SHA256,
                        }
                    )
                )
    bounds = {
        "Tesseract_new_call_upper_bound": len(planned_tess - set(store.rows)),
        "model_new_call_upper_bound": len(planned_model - set(store.model_rows)),
        "Tesseract_exact_prior_requests_reused": len(planned_tess & set(store.rows)),
        "model_exact_prior_requests_reused": len(planned_model & set(store.model_rows)),
        "may_skip_further_if_region_completed": True,
    }
    _atomic(output / "finite_call_bounds.json", bounds)
    initial_bounds_path = output / "initial_finite_call_bounds.json"
    if initial_bounds_path.exists():
        initial_bounds = _read(initial_bounds_path)
    else:
        initial_bounds = bounds
        _atomic(initial_bounds_path, initial_bounds)
    result = copy.deepcopy(text_data)
    result["region_evidence_roots"] = {
        r["id"]: relative_evidence_path(
            upstream.parent
            / text_data.get("region_evidence_roots", {}).get(r["id"], "."),
            output,
        )
        for r in text_data["regions"]
    }
    # A pass may finish just before cancellation and before its region-state
    # checkpoint. Count its verified raw artifact, not only the last cursor.
    cursor = 0
    prior_new_tess = len(
        {
            store.by_path[str(p.resolve())]
            for p in (output / "local_ocr").glob("*.tsv")
            if _read(p.with_suffix(".json")).get(
                "command_executed_for_this_request", True
            )
        }
    )
    prior_new_model = sum(
        _read(p).get("model_inference_executed_for_this_request", True)
        for p in (output / "model_observations").glob("*.json")
    )
    if (output / "completion_state.json").exists():
        state = _read(output / "completion_state.json")
        if state["manifest_sha256"] != _digest(manifest):
            raise ValueError("COMPLETION_STATE_MANIFEST_MISMATCH")
        result, cursor = state["text_data"], state["next_queue_index"]
        keys = {rid: set(values) for rid, values in state["associated_keys"].items()}
        if any(key not in store.rows for values in keys.values() for key in values):
            raise ValueError("COMPLETION_STATE_HAS_UNBOUND_RAW")
        if (
            prior_new_tess < state["new_Tesseract_calls"]
            or prior_new_model < state["new_model_calls"]
        ):
            raise ValueError("COMPLETION_CHECKPOINT_RAW_CALL_ACCOUNTING_LOSS")
    regions = {r["id"]: r for r in result["regions"]}
    cv2.setNumThreads(1)
    _, labels, glyphs = base._component_evidence(image, roi)
    slices = find_objects(labels)
    records = []
    try:
        for index, item in enumerate(queue[cursor:], cursor):
            check_cancel("SOURCE_COMPLETION:" + str(index))
            rids = item.get("region_ids") or [item["region_id"]]
            pending = [rid for rid in rids if not regions[rid]["complete"]]
            if progress_callback:
                progress_callback(
                    {
                        "stage": "source_completion_item",
                        "queue_index": index,
                        "total": len(queue),
                        "batch_index": item["batch_index"],
                        "method": item["stage"],
                        "region_ids": rids,
                    }
                )
            newkeys = []
            if pending and item["stage"] in ("line", "block"):
                plan = item["plan"]
                passes = (
                    [
                        {"crop_xyxy_px": plan["domain"]["bbox_xyxy_px"], "psm": psm}
                        for psm in plan["fixed_psm"]
                    ]
                    if item["stage"] == "line"
                    else plan["passes"]
                )
                for p in passes:
                    newkeys.append(
                        store.request(p["crop_xyxy_px"], p["psm"], progress_callback)
                    )
            for rid in pending:
                old = copy.deepcopy(regions[rid])
                keys[rid].update(newkeys)
                if item["stage"] == "model":
                    alternatives = [
                        store.alternative(k, old["bbox_xyxy_px"])
                        for k in sorted(keys[rid])
                    ]
                    for a in alternatives:
                        a["raw_text"] = cross._raw_text(a["words"])
                        a["all_words_above_unchanged_threshold"] = cross._confident(
                            a["words"]
                        )
                    model_records = [
                        store.request_model(c, rid, labels, roi, slices, model_path)
                        for c in item["plan"]["contexts"]
                    ]
                    candidate, assessment = cross._evaluate(
                        old, alternatives, model_records, image, roi, glyphs, labels
                    )
                    accepted = bool(
                        candidate
                        and assessment["approved_by_cross_engine_and_source_checks"]
                    )
                else:
                    candidate = evaluate_bound_region(
                        old,
                        keys[rid],
                        store,
                        image,
                        roi,
                        glyphs,
                        labels,
                        slices,
                        source_domain=item["plan"]["domain"]
                        if item["stage"] == "line"
                        else None,
                    )
                    if item["stage"] == "line":
                        plan = item["plan"]
                        unread, reasons = domains._unread_boundary_ink(
                            image, candidate, plan["domain"]
                        )
                        inspection = domains.inspect_source_domain(
                            labels,
                            roi,
                            plan["domain"]["bbox_xyxy_px"],
                            component_slices=slices,
                        )
                        reasons += inspection["unresolved_reasons"]
                        if plan["domain"].get("crop_crosses_roi"):
                            reasons.append(
                                "REFINED_SOURCE_DOMAIN_CROSSES_REQUESTED_ROI"
                            )
                        candidate["unresolved_reasons"] = sorted(
                            set(candidate["unresolved_reasons"] + reasons)
                        )
                        candidate["complete"] = bool(
                            candidate["words"] and not candidate["unresolved_reasons"]
                        )
                        candidate["source_completion_evidence"][
                            "frozen_line_domain"
                        ] = {
                            "plan": plan,
                            "inspection": inspection,
                            "unread_source": unread,
                        }
                    accepted = bool(candidate["complete"])
                    assessment = None
                record = {
                    "queue_item": item,
                    "region_id": rid,
                    "old": old,
                    "candidate": candidate,
                    "cross_engine_assessment": assessment,
                    "adopted_into_text_contract": accepted,
                    "failure_preserves_previous_region": not accepted,
                }
                _atomic(
                    output / "region_attempts" / (f"{index:04d}-" + rid + ".json"),
                    record,
                )
                records.append(
                    {
                        "region_id": rid,
                        "method": item["stage"],
                        "adopted": accepted,
                        "new_text": candidate["text"] if candidate else None,
                    }
                )
                if accepted:
                    regions[rid].clear()
                    regions[rid].update(candidate)
                    result["region_evidence_roots"][rid] = "."
            _atomic(
                output / "completion_state.json",
                {
                    "manifest_sha256": _digest(manifest),
                    "next_queue_index": index + 1,
                    "text_data": result,
                    "associated_keys": {
                        rid: sorted(values) for rid, values in keys.items()
                    },
                    "new_Tesseract_calls": prior_new_tess + store.new_tesseract_calls,
                    "new_model_calls": prior_new_model + store.new_model_calls,
                },
            )
            if (
                prior_new_tess + store.new_tesseract_calls
                > initial_bounds["Tesseract_new_call_upper_bound"]
                or prior_new_model + store.new_model_calls
                > initial_bounds["model_new_call_upper_bound"]
            ):
                raise RuntimeError("COMPLETION_EXCEEDED_FROZEN_UNIQUE_CALL_BOUND")
    except BaseException as exc:
        _atomic(
            output / "external_or_program_stop.json",
            {
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "next_recoverable_state": "completion_state.json"
                if (output / "completion_state.json").exists()
                else None,
                "verified_raw_passes_are_individually_saved": True,
                "prior_success_files_unchanged": True,
            },
        )
        raise
    result, context_ownership_audit = context_ownership.derive_context_ownership(
        image, result, store.model_rows.values(), store.rows.values(),
        labels=labels, slices=slices, glyphs=glyphs,
    )
    _atomic(output / "text_context_ownership_audit.json", context_ownership_audit)
    regions = {region["id"]: region for region in result["regions"]}
    for group in result["groups"]:
        rows = [regions[rid] for rid in group["region_ids"]]
        group.update(
            text="\n".join(r["text"] for r in rows),
            complete=all(r["complete"] for r in rows),
            bbox_xyxy_px=base._box_union([r["bbox_xyxy_px"] for r in rows]),
            unresolved_reasons=sorted(
                {reason for r in rows for reason in r["unresolved_reasons"]}
            ),
            lines=[
                {
                    "region_id": r["id"],
                    "text": r["text"],
                    "bbox_xyxy_px": r["bbox_xyxy_px"],
                    "complete": r["complete"],
                    "word_ids": [w["id"] for w in r["words"]],
                }
                for r in rows
            ],
        )
        group["numeric_label"] = (
            len(rows) == 1 and bool(group["text"]) and group["text"].isdigit()
        )
    result["uncertainties"] = [
        {
            "region_id": r["id"],
            "text": r["text"],
            "bbox_xyxy_px": r["bbox_xyxy_px"],
            "reasons": r["unresolved_reasons"],
        }
        for r in result["regions"]
        if not r["complete"]
    ]
    immutable = [
        {"region_id": r["id"], "unchanged": _digest(r) == _digest(regions[r["id"]])}
        for r in text_data["regions"]
        if r["complete"]
    ]
    if not all(row["unchanged"] for row in immutable):
        raise RuntimeError("COMPLETION_CHANGED_PREVIOUS_COMPLETE_REGION")
    if (
        base.source_array_sha256(image) != source_array_hash
        or base._sha(upstream) != manifest["upstream_sha256"]
    ):
        raise RuntimeError("COMPLETION_MODIFIED_SOURCE_OR_UPSTREAM")
    combined = np.zeros((roi[3] - roi[1], roi[2] - roi[0]), dtype=np.uint8)
    for region in result["regions"]:
        masks = [region["compact_source_ink_mask"]]
        if region.get("retained_unassigned_old_context"):
            masks.append(
                region["retained_unassigned_old_context"]["compact_source_ink_mask"]
            )
        for mask in masks:
            for y, a, b in mask["runs_y_x0_x1"]:
                combined[y - roi[1], a - roi[0] : b - roi[0]] = 255
    Image.fromarray(combined).save(output / "compact_glyph_candidate_mask.png")
    result["bbox_overlay"] = base._overlay(image, roi, result["regions"], output)
    result["text_candidate_mask"] = {
        "path": "compact_glyph_candidate_mask.png",
        "origin_xy_px": roi[:2],
        "size_px": [roi[2] - roi[0], roi[3] - roi[1]],
        "coordinate_system": "source_pixels_top_left",
        "source_erasure_authorized": False,
        "old_unknown_context_mask_retained": True,
    }
    producer = {
        "module": __name__,
        "sha256": base._sha(__file__),
        "dependencies": dependencies,
        "source_sha256": source_sha,
        "source_array_sha256": source_array_hash,
        "upstream_path": str(upstream),
        "upstream_sha256": manifest["upstream_sha256"],
        "raw_source_pixels_modified": False,
        "manual_transcription_supplied": False,
    }
    summary = {
        "policy": POLICY,
        "frozen_queue_counts": counts,
        "finite_call_bounds": initial_bounds,
        "remaining_call_bounds_at_this_invocation": bounds,
        "run_remaining": bool(run_remaining),
        "completed_queue_items": len(queue),
        "new_Tesseract_calls": prior_new_tess + store.new_tesseract_calls,
        "new_model_calls": prior_new_model + store.new_model_calls,
        "verified_prior_Tesseract_observations": bound_count,
        "changes_this_invocation": records,
        "old_complete_region_checks": immutable,
        "source_and_upstream_unchanged": True,
        "wall_seconds": time.perf_counter() - started,
        "process_cpu_seconds": time.process_time() - cpu,
        "new_complete_region_ids": [
            r["id"]
            for r in result["regions"]
            if r["complete"]
            and not next(x for x in text_data["regions"] if x["id"] == r["id"])[
                "complete"
            ]
        ],
        "product_GO": False,
    }
    confirmation = confirmation_module.build_confirmation_index(
        image, result, store.model_rows.values(), glyphs=glyphs
    )
    context_ownership.attach_confirmation_context(confirmation, result)
    _atomic(output / "text_confirmation_index.json", confirmation)
    result["text_confirmation_index"] = {
        "path": "text_confirmation_index.json",
        "sha256": base._sha(output / "text_confirmation_index.json"),
        "pending_region_count": len(confirmation["pending_regions"]),
        "failure_type_counts": confirmation["failure_type_counts"],
        "automatic_content_adoption": False,
    }
    result.update(
        producer=producer,
        status="SOURCE_COMPLETION_FINITE_QUEUE_FINISHED"
        if run_remaining
        else "SOURCE_REBIND_DIAGNOSTIC_ONLY",
        source_completion_summary=summary,
    )
    validate_text_regions(result, image.shape, roi)
    _atomic(output / "text_regions.json", result)
    _atomic(output / "completed_text.json", result)
    _atomic(output / "summary.json", summary)
    _atomic(
        output / "completed_stages.json",
        {
            "source_sha256": source_sha,
            "source_array_sha256": source_array_hash,
            "roi_xyxy_px": roi,
            "source_size_px": result["source_size_px"],
            "coordinate_system": "source_pixels_top_left",
            "text": {
                "path": "completed_text.json",
                "sha256": base._sha(output / "completed_text.json"),
                "producer_module": __name__,
                "producer_sha256": base._sha(__file__),
                "dependency_producers": dependencies,
            },
        },
    )
    return result
