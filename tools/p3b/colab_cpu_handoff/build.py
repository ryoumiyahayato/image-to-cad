"""Read-only frozen-input audit and deterministic Colab handoff builder. NEVER fits a learner."""

import argparse
import ast
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

import jsonschema
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
from common import digest, product_snapshot, read, read_rows, sha, validate_samples
from features import FEATURE_NAMES, feature_vector, image_tensor
from audit_acceptance import audit_state
from label_ui import diverse_order
import runtime

DOCS = PROJECT / "docs/product-fix-p3b"
CACHE = PROJECT.parent.parent / "image-to-cad-p3b-cache"
FINAL_NAME = "FINAL-TRAINING-DATA-FREEZE.json"
EXPECTED_FINAL_SHA = "4a4faa39a2a56811f6723fa0ccfa2322320080023c59c35a2179f40f08942795"


def check(ok, message):
    if not ok:
        raise ValueError(message)


def dump(path, value):
    runtime.write_json(path, value)


def inventory_entry(path, role):
    check(Path(path).is_file(), "NOT_FOUND: " + str(path))
    return {"path": str(Path(path).resolve()), "role": role, "size_bytes": Path(path).stat().st_size,
            "sha256": sha(path)}


def audit():
    before = product_snapshot()
    freeze = read(DOCS / FINAL_NAME)
    check(sha(DOCS / FINAL_NAME) == EXPECTED_FINAL_SHA, "Final frozen manifest identity changed")
    local = [inventory_entry(DOCS / FINAL_NAME, "final freeze")]
    bound = {}
    for name, entry in freeze["human_input_bindings"].items():
        # Only the explicit final-freeze bindings are opened. No recursive source/cache discovery.
        path = Path(entry["path"])
        check(path.is_relative_to(DOCS), "Human binding outside approved documentation")
        record = inventory_entry(path, name)
        check(record["sha256"] == entry["sha256"], "Binding checksum mismatch: " + name)
        local.append(record); bound[name] = path
    for name, key in (("model-input-v1-frozen.json", "input_contract_sha256"),
                      ("first-baseline-configuration.json", "baseline_configuration_sha256"),
                      ("final-human-reliability-provenance.jsonl", "human_provenance_sha256")):
        record = inventory_entry(DOCS / name, name)
        check(record["sha256"] == freeze[key], "Freeze identity mismatch: " + name)
        local.append(record)
    for key, snapshot in freeze["current_truth_snapshots"].items():
        record = inventory_entry(snapshot["path"], "immutable current truth snapshot")
        check(record["sha256"] == snapshot["sha256"], "Current truth snapshot mismatch: " + key)
        local.append(record)
    contract = read(DOCS / "model-input-v1-frozen.json")
    old_config = read(DOCS / "first-baseline-configuration.json")
    check(list(FEATURE_NAMES) == contract["feature_order"] and contract["feature_shape"] == [18]
          and contract["feature_dtype"] == "float32"
          and sha(HERE.parent / "features.py") == contract["feature_implementation_sha256"],
          "Feature implementation/schema mismatch")
    local.append(inventory_entry(HERE.parent / "features.py", "frozen feature implementation"))
    check(old_config["input_contract_sha256"] == freeze["input_contract_sha256"]
          and old_config["classes"] == runtime.CLASSES and old_config["seed"] == 314159
          and old_config["C"] == 1 and old_config["max_iter"] == 1000
          and old_config["class_weight"] == "balanced", "Baseline frozen configuration mismatch")
    assignments = {r["source_drawing_id"]: r for r in read(bound["split_manifest"])["drawings"]
                   if r["split"] in ("train", "validation")}
    states, manifests, histories = {}, {}, {}
    for split in ("train", "validation"):
        for review in (False, True):
            key = split + ("_re_review" if review else "_original")
            manifest_key = split + ("_re_review_manifest" if review else "_manifest")
            rows = read_rows(bound[manifest_key]); state = read(bound[key + "_labels"])
            check(all(r["split"] == split and r["domain"] == "real" for r in rows),
                  "Only frozen real train/validation manifests are allowed")
            check(len({r["sample_id"] for r in rows}) == len(rows), "Duplicate human record IDs")
            order = rows if review else diverse_order(rows)
            history = audit_state(state, rows, sha(bound[manifest_key]), presentation_order=order)
            check(history.get("FINAL_STATE_INTERNALLY_CONSISTENT") is True,
                  "Human history replay failed: " + key + " " + str(history.get("INTERNAL_ERRORS")))
            states[key] = state; manifests[key] = rows; histories[key] = history
    check(histories["validation_re_review"] == read(bound["accepted_validation_result"])["history_audit"],
          "Final validation re-review differs from accepted audit")
    provenance_rows = read_rows(DOCS / "final-human-reliability-provenance.jsonl")
    provenance_by_id = {r["sample_id"]: r for r in provenance_rows}
    result, assets, originals, exclusions, changes = {}, [], {}, [], []
    for split in ("train", "validation"):
        rows = manifests[split + "_original"]
        truth_rows = read_rows(bound[split + "_adjudication"])
        snapshots = read_rows(freeze["current_truth_snapshots"][split + "-adjudicated-truth.jsonl"]["path"])
        check(truth_rows == snapshots, "Adjudicated snapshot content mismatch: " + split)
        check(len(truth_rows) == len(rows) and {r["sample_id"] for r in truth_rows} == {r["sample_id"] for r in rows},
              "Truth population mismatch")
        truth = {r["sample_id"]: r for r in truth_rows}
        review_ids = {r["sample_id"] for r in manifests[split + "_re_review"]}
        export = []
        for row in rows:
            sid = row["sample_id"]; t = truth[sid]
            original = states[split + "_original"]; reviewed = states[split + "_re_review"]
            for field, state, state_key in (("original", original, "_original"), ("re_review", reviewed, "_re_review")):
                check(t[field + "_stage0"] == state["nomination_statuses"].get(sid)
                      and t[field + "_stage1"] == state["labels"].get(sid), "Saved human decision differs: " + sid)
            state = reviewed if sid in review_ids else original
            nomination = state["nomination_statuses"][sid]; label = state["labels"].get(sid)
            current_class = label["label"] if label else None
            ready = nomination["status"] == "VALID_TARGET" and label is not None
            check(t["current_class"] == current_class and t["current_stage0"] == nomination["status"]
                  and t["current_review_status"] == ("READY" if ready else "EXCLUDED"), "Effective label mismatch: " + sid)
            check(t["source_drawing_id"] == row["source_drawing_id"]
                  and t["source_family_id"] == row["source_family_id"], "Truth drawing/family mismatch")
            assignment = assignments[row["source_drawing_id"]]
            check(assignment["split"] == split and assignment["source_family_id"] == row["source_family_id"],
                  "Frozen source/family split mismatch")
            old_pair = (t["original_stage0"]["status"], (t["original_stage1"] or {}).get("label"))
            new_pair = ((t["re_review_stage0"] or {}).get("status"), (t["re_review_stage1"] or {}).get("label"))
            tags = ["DIRECT_HUMAN"] if sid not in review_ids else [
                "CONFIRMED_BY_REREVIEW" if old_pair == new_pair else "ADJUDICATED_CHANGED"]
            if sid in review_ids and old_pair != new_pair:
                changes.append({"sample_id": sid, "split": split, "original": old_pair, "current": new_pair})
            if current_class == "AMBIGUOUS": tags.append("HUMAN_AMBIGUOUS")
            if nomination["status"] == "INVALID_NOMINATION": tags.append("EXCLUDED_BAD_NOMINATION")
            role = "EXCLUDED" if not ready else ("ABSTENTION_EVALUATION" if current_class == "AMBIGUOUS"
                   else "SUPERVISED_TRAIN" if split == "train" else "CLASSIFICATION_EVALUATION")
            expected_prov = {"sample_id": sid, "split": split, "current_human_class": current_class,
                "current_stage0": nomination["status"], "human_reliability_provenance": tags,
                "evaluation_role": role, "exclusion_reason": nomination["status"] if not ready else None,
                "human_correctness_probability": None, "numeric_human_probability_invented": False}
            check(provenance_by_id[sid] == expected_prov, "Reliability provenance mismatch: " + sid)
            if not ready:
                exclusions.append({"sample_id": sid, "split": split, "stage0": nomination["status"]})
                continue
            check(current_class in (runtime.CLASSES if split == "train" else runtime.CLASSES + ["AMBIGUOUS"]),
                  "Invalid training/validation class")
            path = Path(row["source_path"]).resolve()
            # Allowlist is built only AFTER verifying each sample's train/validation split.
            if str(path) not in originals:
                record = inventory_entry(path, "approved " + split + " original source")
                check(record["sha256"] == row["source_sha256"], "Original source checksum mismatch: " + str(path))
                originals[str(path)] = record
            check(originals[str(path)]["sha256"] == row["source_sha256"], "Source identity disagreement")
            base = CACHE / ("real-v2-formal-seed-001" if split == "train" else "validation-v2-001")
            folder = (base / row["patch_dir"]).resolve()
            check(folder.is_relative_to(base), "Crop path escaped approved cache")
            asset_hashes = {}
            for name in ("gray", "edges", "centerline"):
                record = inventory_entry(folder / (name + ".png"), "approved input crop")
                check(record["sha256"] == contract["input_asset_sha256"][sid][name], "Crop file checksum mismatch: " + sid)
                assets.append(record); asset_hashes[name] = record["sha256"]
            with Image.open(folder / "gray.png") as image:
                check(hashlib.sha256(image.convert("L").tobytes()).hexdigest() == row["patch_sha256"], "Crop pixel hash mismatch")
            tensor = image_tensor(row, folder); vector = feature_vector(row, folder)
            check(tensor.shape == (3, 256, 256) and tensor.dtype == np.float32 and np.isfinite(tensor).all()
                  and tensor.min() >= 0 and tensor.max() <= 1 and vector.shape == (18,)
                  and vector.dtype == np.float32 and np.isfinite(vector).all(), "Input tensor / numeric defect")
            profiles = [m.get("profile") for m in (row.get("current_p3a_measurement") or []) if m.get("profile")]
            profile = profiles[0] if profiles else {}; f = row.get("features", {})
            missing = [k not in f for k in ("distance_px", "angle_delta_deg", "overlap_px")]
            missing += [row["source_dpi"] is None, False] + [False] * 5
            missing += ["source_width_px" not in profile, False]
            missing += [k not in profile for k in ("stable_fraction", "dark_core_fraction", "center_offset_px", "samples", "contrast_separated_fraction")]
            missing += [False]
            export.append({"sample_id": sid, "split": split, "domain": "real", "stage0": "VALID_TARGET",
                "label": current_class, "role": role, "features": vector.tolist(), "missing_features": missing,
                "profile_present": bool(profile), "feature_sha256": hashlib.sha256(vector.astype("<f4").tobytes()).hexdigest(),
                "source_drawing_id": row["source_drawing_id"], "source_family_id": row["source_family_id"],
                "source_dpi": row["source_dpi"], "target_kind": row["target_kind"], "source_page": row["source_page"],
                "source_bbox": row["source_bbox"], "source_sha256": row["source_sha256"], "patch_sha256": row["patch_sha256"],
                "asset_sha256": asset_hashes, "record_sha256": digest(row), "truth_record_sha256": digest(t),
                "record_reference": "docs/product-fix-p3b/" + bound[split + "_manifest"].name + "#sample_id=" + sid,
                "truth_reference": "docs/product-fix-p3b/frozen/training-data-v2-001/" + split + "-adjudicated-truth.jsonl#sample_id=" + sid,
                "human_reliability_provenance": tags})
        export.sort(key=lambda r: r["sample_id"])
        expected_ids = freeze["sample_ids"][split] + (freeze["sample_ids"]["abstention_evaluation"] if split == "validation" else [])
        check([r["sample_id"] for r in export] == sorted(expected_ids), "Included ID population mismatch")
        check(Counter(r["label"] for r in export) == Counter({c: n for c, n in freeze[split]["class_distribution"].items() if n}),
              "Frozen class counts changed")
        check(len(export) == freeze[split]["included_count"], "Included sample count mismatch")
        result[split] = export
    validate_samples(manifests["train_original"] + manifests["validation_original"])
    for field in ("sample_id", "source_drawing_id", "source_family_id", "source_sha256", "patch_sha256"):
        check(not ({r[field] for r in result["train"]} & {r[field] for r in result["validation"]}), "Cross-split leakage: " + field)
    check({r["sample_id"] for r in provenance_rows} == {r["sample_id"] for k in ("train_original", "validation_original") for r in manifests[k]},
          "Unexpected provenance sample population")
    check(sorted(({k: r[k] for k in ("sample_id", "stage0")} for r in exclusions), key=lambda r: r["sample_id"])
          == sorted(freeze["train"]["excluded"] + freeze["validation"]["excluded"], key=lambda r: r["sample_id"]),
          "Exclusions mismatch")
    local.extend(originals.values()); local.extend(assets)
    check(product_snapshot() == before, "Production files changed during audit")
    return result, freeze, contract, old_config, {"LOCAL_AVAILABLE": local, "history_audits": histories,
        "adjudication_changes": changes, "source_original_files_verified": len(originals),
        "crop_files_verified": len(assets), "excluded": exclusions, "production_snapshot": before,
        "local_environment": {"python": sys.version, "numpy": np.__version__, "Pillow": importlib.metadata.version("Pillow")}}


def cell(kind, name, source):
    value = {"cell_type": kind, "id": name, "metadata": {"name": name}, "source": source.splitlines(keepends=True)}
    if kind == "code": value.update(execution_count=None, outputs=[])
    return value


def notebook(anchors):
    # Runtime is embedded verbatim. No helper-script upload, Drive mount or repository needed.
    helper = (HERE / "runtime.py").read_text(encoding="utf-8")
    setup = '''import subprocess, sys
from importlib.metadata import version, PackageNotFoundError
pins = {"numpy":"2.2.6", "scipy":"1.15.3", "scikit-learn":"1.7.2", "joblib":"1.5.2", "threadpoolctl":"3.6.0"}
if not (3, 10) <= sys.version_info[:2] <= (3, 13):
    raise RuntimeError("Python 3.10–3.13 required; stop if this Colab version is incompatible")
changed = False
for package, wanted in pins.items():
    try:
        changed = changed or version(package) != wanted
    except PackageNotFoundError:
        changed = True
if changed:
    subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
                   + [name + "==" + wanted for name, wanted in pins.items()], check=True)
    print("安装成功。请点击‘运行时 → 重新启动会话’，再运行 A1。不要点击全部运行。")
else:
    print("依赖版本已一致，可以运行 A1 PRE-FLIGHT。")
'''
    cells = [cell("markdown", "intro", "# P3B Colab CPU 首次基线\n仅离线研究；EXPLORATORY_BASELINE_ONLY。\n"
                 "94 个训练样本，50 个验证样本（49 个分类评估＋1 个 AMBIGUOUS 单列）。\n"
                 "先将硬件加速器设为 **无 / CPU**。通过左侧文件区上传 `p3b-colab-inputs.zip`。\n"
                 "按阶段逐个运行，不使用‘全部运行’。TRAIN / VALIDATE / EXPORT 均需人工输入确认词。\n"
                 "运行环境被回收后文件会丢失，请下载结果。无需 GPU、Drive 或 MCP。\n"),
             cell("markdown", "phase-a", "## Phase A — PRE-FLIGHT\n**A0 依赖准备**：人工运行安装单元；若安装了依赖，重新启动会话后再运行 A1。\n"
                  "依赖安装或兼容性失败必须停止。固定版本用于可复现 CPU 研究。\n"),
             cell("code", "A0-install", setup),
             cell("markdown", "a1-guide", "**A1 PRE-FLIGHT**：检查 ZIP、校验和、冻结样本与标签、18 个特征、缺失标识、来源隔离及环境。\n"
                  "末尾必须显示 `PRE-FLIGHT PASS`。任何 FAIL 都会阻止训练。\n"),
             cell("code", "A1-preflight", helper + "\nANCHORS = " + repr(anchors) + '''
PREFLIGHT = None
TRAIN_RUN = globals().get("TRAIN_RUN")
INPUT_ZIP = Path("/content/p3b-colab-inputs.zip")
PREFLIGHT = preflight(INPUT_ZIP, ANCHORS)
'''),
             cell("markdown", "phase-b", "## Phase B — TRAIN\n确认预检 PASS 后手动运行 B1，并输入 `TRAIN`。\n"
                  "仅 LogisticRegression（balanced，C=1，max_iter=1000，seed=314159）。Pipeline 的 scaler 只拟合训练集。\n"
                  "禁止 CNN 或验证集调参。重复训练会被当前会话拦截。\n"),
             cell("code", "B1-train", '''if globals().get("TRAIN_RUN") is not None:
    raise RuntimeError("Training already completed; continue to VALIDATE")
TRAIN_RUN = train_manual(globals().get("PREFLIGHT"), ANCHORS)
'''),
             cell("markdown", "phase-c", "## Phase C — VALIDATE\n手动运行 C1，输入 `VALIDATE`。本会话只评估一次。\n"
                  "报告混淆矩阵、各类指标、FMR 分子/分母、SINGLE 行动覆盖率及按来源、图样、DPI、目标类型分组结果。\n"
                  "冻结的 0.5/0.8/0.9/0.95/0.99/0.995 阈值只作探索性报告，不挑选‘最佳’阈值。\n"
                  "原始 predict_proba 未校准；一个 AMBIGUOUS 案例不能证明拒判可靠，也不能证明生产合并安全。\n"),
             cell("code", "C1-validate", "METRICS = validate_manual(globals().get('PREFLIGHT'), ANCHORS, globals().get('TRAIN_RUN'))\n"),
             cell("markdown", "phase-d", "## Phase D — EXPORT\n手动运行 D1，输入 `EXPORT`；下载 `p3b-baseline-results.zip` 并交回 Codex。\n"
                  "仅离线研究，不自动上传或写入产品目录。joblib/pickle 只加载可信来源的模型；需要相同 Python 主/次版本及所记录的依赖版本。\n"),
             cell("code", "D1-export", "RESULT_ZIP = export_manual(globals().get('PREFLIGHT'), ANCHORS, globals().get('TRAIN_RUN'))\n")]
    return {"nbformat": 4, "nbformat_minor": 5, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"}, "colab": {"name": "p3b-colab-cpu-baseline.ipynb", "provenance": []}}, "cells": cells}


def deterministic_zip(directory, output):
    files = sorted(directory.iterdir())
    check(all(p.is_file() for p in files), "Only actual input files may be zipped")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for p in files:
            info = zipfile.ZipInfo(directory.name + "/" + p.name, date_time=(2026, 10, 8, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED; info.external_attr = 0o100644 << 16
            archive.writestr(info, p.read_bytes(), compresslevel=9)


def build(out):
    check(not out.exists(), "Delivery directory already exists; choose a new empty version instead of overwriting")
    rows, freeze, contract, old_config, audit_report = audit()
    # Outputs are created only AFTER all required real inputs pass audit.
    out.mkdir(parents=True)
    package = out / runtime.ROOT_NAME; package.mkdir()
    for split in ("train", "validation"):
        (package / (split + "-features.jsonl")).write_text(
            "".join(json.dumps(r, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" for r in rows[split]), encoding="utf-8")
    manifest = {"dataset_version": freeze["dataset_version"], "frozen_manifest_sha256": sha(DOCS / FINAL_NAME),
        "input_contract_sha256": freeze["input_contract_sha256"], "label_provenance_sha256": freeze["human_provenance_sha256"],
        "split_manifest_sha256": freeze["human_input_bindings"]["split_manifest"]["sha256"],
        "included_splits": ["train", "validation"], "blind_inputs": 0, "synthetic_inputs": 0,
        "ambiguous_sample_ids": freeze["sample_ids"]["abstention_evaluation"], "excluded": audit_report["excluded"]}
    for split in ("train", "validation"):
        manifest[split] = {"count": len(rows[split]), "sample_ids": [r["sample_id"] for r in rows[split]],
            "class_counts": dict(Counter(r["label"] for r in rows[split])),
            "drawings": sorted({r["source_drawing_id"] for r in rows[split]}),
            "source_families": sorted({r["source_family_id"] for r in rows[split]})}
    config = {k: old_config[k] for k in ("dataset_version", "seed", "C", "class_weight", "max_iter", "classes", "thresholds_for_reporting")}
    config.update(model="LogisticRegression", solver="lbfgs", tol=1e-4, scaling="training-only StandardScaler",
        feature_count=18, scope=runtime.MARKER, probability_interpretation="uncalibrated_scores",
        thresholds_role="Frozen exploratory reporting only; no best threshold selection",
        manual_training_only=True, original_configuration_sha256=freeze["baseline_configuration_sha256"],
        authorization="This handoff prepares files only. Future Colab TRAIN requires the user's manual action.")
    schema = {"feature_count": 18, "feature_order": list(FEATURE_NAMES), "dtype": "float32",
        "implementation_sha256": contract["feature_implementation_sha256"],
        "training_normalization": contract["numerical_normalization"], "missing_value_policy": contract["missing_values"],
        "missing_features": "18 booleans in feature order; absent underlying value uses existing zero default. Metadata only, not extra model features.",
        "dpi_semantics": "Effective source/render DPI, not asserted acquisition DPI. Unknown is null and its dpi_known=0.",
        "known_limits": contract["known_limit"]}
    provenance = {"DATA_INTEGRITY": "PASS", "LABEL_PROVENANCE": "VERIFIED", "human_labels_infallible": False,
        "HUMAN_LABEL_CERTAINTY": "No claim of absolute semantic correctness; pixel support is not semantic truth",
        "final_manifest_sha256": sha(DOCS / FINAL_NAME), "bound_input_hashes": {
            k: {"reference": str(Path(v["path"]).relative_to(PROJECT)).replace("\\", "/"), "sha256": v["sha256"]}
            for k, v in freeze["human_input_bindings"].items()},
        "final_provenance_sha256": freeze["human_provenance_sha256"],
        "label_history_replay": {k: "PASS" for k in audit_report["history_audits"]},
        "verified_source_files": audit_report["source_original_files_verified"], "verified_crop_files": audit_report["crop_files_verified"],
        "blind_source_access": "NONE", "adjudicated_changes_count": len(audit_report["adjudication_changes"]),
        "historical_state": "Original false training_authorized metadata preserved; no local fit, no labels rewritten",
        "local_extraction_environment": audit_report["local_environment"]}
    for name, value in (("dataset-manifest.json", manifest), ("training-config.json", config), ("feature-schema.json", schema),
                        ("freeze-provenance.json", provenance), ("class-map.json", {"classes": runtime.CLASSES,
                            "class_to_index": {c: i for i, c in enumerate(runtime.CLASSES)}, "AMBIGUOUS": "ABSTENTION_EVALUATION_ONLY"})):
        dump(package / name, value)
    sums = "".join(sha(p) + "  " + p.name + "\n" for p in sorted(package.iterdir()))
    (package / "checksums.sha256").write_text(sums, encoding="utf-8")
    zip_path = out / "p3b-colab-inputs.zip"; deterministic_zip(package, zip_path)
    anchors = {"zip_sha256": sha(zip_path), "checksums_sha256": sha(package / "checksums.sha256"),
               "manifest": manifest, "config": config, "feature_order": list(FEATURE_NAMES)}
    nb = notebook(anchors); nb_path = out / "p3b-colab-cpu-baseline.ipynb"; dump(nb_path, nb)
    jsonschema.Draft4Validator(read(HERE / "nbformat.v4.5.schema.json")).validate(nb)
    check(len({c["id"] for c in nb["cells"]}) == len(nb["cells"]), "Duplicate notebook cell IDs")
    for c in nb["cells"]:
        if c["cell_type"] == "code":
            ast.parse("".join(c["source"]), filename=c["id"])
            check(c["execution_count"] is None and c["outputs"] == [], "Notebook must be unexecuted")
    check("C:\\Users" not in json.dumps(nb) and "mount(" not in json.dumps(nb), "Local absolute path / Drive dependency")
    receipt = runtime.preflight(zip_path, anchors, require_ml=False)
    runtime.guarded_inputs(receipt, anchors, require_ml=False)
    tests = boundary_tests(zip_path, anchors, receipt)
    # Execute EXACT embedded A1 helpers plus PRE-FLIGHT only; no B/C/D or installation.
    source = "".join(next(c["source"] for c in nb["cells"] if c["id"] == "A1-preflight"))
    tree = ast.parse(source)
    check(isinstance(tree.body[-1], ast.Assign) and isinstance(tree.body[-1].value, ast.Call)
          and tree.body[-1].value.func.id == "preflight", "Unexpected A1 execution boundary")
    namespace = {"__name__": "p3b_local_notebook_preflight"}
    exec(compile(ast.Module(body=tree.body[:-1], type_ignores=[]), "A1-preflight-helpers", "exec"), namespace)
    embedded_receipt = namespace["preflight"](zip_path, namespace["ANCHORS"], require_ml=False)
    namespace["guarded_inputs"](embedded_receipt, namespace["ANCHORS"], require_ml=False)
    check(product_snapshot() == audit_report["production_snapshot"], "Production files changed during packaging")
    for record in audit_report["LOCAL_AVAILABLE"]:
        # Sources/crops were already hashed; frozen docs and implementation are rechecked at the end.
        if record["role"] not in ("approved input crop", "approved train original source", "approved validation original source"):
            check(sha(record["path"]) == record["sha256"], "Frozen input changed during packaging")
    reproduction = out / "reproduction"; reproduction.mkdir()
    for name in ("build.py", "runtime.py", "nbformat.v4.5.schema.json"):
        shutil.copyfile(HERE / name, reproduction / name)
    (out / "README-中文.md").write_text(readme(), encoding="utf-8")
    git = subprocess.run(["git", "status", "--short"], cwd=PROJECT, capture_output=True, text=True).stdout
    audit_report.update(DATA_INTEGRITY="PASS", LABEL_PROVENANCE="VERIFIED", HUMAN_LABEL_CERTAINTY="不宣称全部标签绝对正确",
        LOCAL_STATIC_CHECK="PASS", LOCAL_DATA_PREFLIGHT="PASS", ML_DEPENDENCY_CHECK="NOT_RUN_LOCAL_DATA_ONLY",
        COLAB_CPU_EXECUTION="NOT_RUN", ACTUAL_LOGISTIC_TRAINING="NOT_RUN", ACTUAL_VALIDATION_METRICS="NOT_AVAILABLE",
        CLOUD_VERIFIED=[], CHATGPT_LIBRARY_COMPLETE_DATASET_STATUS="UNVERIFIED", GOOGLE_DRIVE_DATASET_STATUS="NOT_VERIFIED",
        boundary_tests=tests, notebook_schema={"source": "https://raw.githubusercontent.com/jupyter/nbformat/v5.10.4/nbformat/v4/nbformat.v4.5.schema.json",
            "sha256": sha(HERE / "nbformat.v4.5.schema.json"), "validator": "jsonschema.Draft4Validator"},
        notebook_code_cells_checked=[c["id"] for c in nb["cells"] if c["cell_type"] == "code"],
        ACTIVE_CHECKOUT=str(PROJECT), AGENTS_INSTRUCTIONS_READ="NOT_FOUND", GIT_STATUS=git,
        outer_git_status="UNAVAILABLE: bad signature 0x00000000; fatal index file corrupt. Left untouched.",
        historical_discrepancies="NONE in final counts/config. Earlier validation had 3 AMBIGUOUS; accepted re-review changes two to TRUE_PARALLEL. Train rank 40 becomes excluded. No data edited.",
        existing_runner_compatibility="classical.py / benchmark.py / train_small.py use obsolete four-class contract; not executed",
        notebook_or_existing_packager="NOT_FOUND before this handoff",
        BLIND_TOUCHED="NO; split registry metadata only, no blind source/crop opened, hashed, rendered or exported",
        production_files_verified_unchanged=len(audit_report["production_snapshot"]),
        input_members=[{"name": p.name, "size_bytes": p.stat().st_size, "sha256": sha(p)} for p in sorted(package.iterdir())],
        deliverables=[inventory_entry(p, "deliverable") for p in (nb_path, zip_path, out / "README-中文.md")],
        HANDOFF_STATUS="READY_FOR_MANUAL_COLAB")
    dump(out / "LOCAL-PREPARATION-REPORT.json", audit_report)
    (out / "HANDOFF-REPORT.md").write_text(report_text(out, nb_path, zip_path, manifest, audit_report), encoding="utf-8")
    paths = sorted(p for p in out.rglob("*") if p.is_file())
    (out / "checksums.sha256").write_text("".join(sha(p) + "  " + p.relative_to(out).as_posix() + "\n" for p in paths), encoding="utf-8")
    print(json.dumps({"HANDOFF_STATUS": "READY_FOR_MANUAL_COLAB", "directory": str(out), "notebook_sha256": sha(nb_path),
                      "zip_size": zip_path.stat().st_size, "zip_sha256": sha(zip_path), "tests": tests}, indent=2))


def boundary_tests(zip_path, anchors, receipt):
    tests = []
    def rejects(name, action):
        try:
            action()
        except (ValueError, TypeError):
            tests.append(name + ": PASS (rejected)")
        else:
            raise ValueError("Guard failed to reject " + name)
    rejects("missing preflight receipt", lambda: runtime.train_manual(None, anchors))
    rejects("local data-only receipt cannot train", lambda: runtime.train_manual(receipt, anchors))
    payload = runtime.archive_payload(zip_path, anchors)
    bad = dict(payload)
    rows = [json.loads(line) for line in bad["train-features.jsonl"].decode().splitlines()]
    rows[0]["label"] = "AMBIGUOUS"
    bad["train-features.jsonl"] = "\n".join(json.dumps(r) for r in rows).encode()
    rejects("AMBIGUOUS cannot enter supervision", lambda: runtime.validate_payload(bad, anchors))
    bad = dict(payload); modified = read_json_bytes(bad["training-config.json"]); modified["C"] = 2
    bad["training-config.json"] = json.dumps(modified).encode()
    rejects("altered hyperparameter", lambda: runtime.validate_payload(bad, anchors))
    bad = dict(payload); rows = [json.loads(line) for line in bad["validation-features.jsonl"].decode().splitlines()]
    rows[0]["source_family_id"] = read_json_bytes(payload["dataset-manifest.json"])["train"]["source_families"][0]
    bad["validation-features.jsonl"] = "\n".join(json.dumps(r) for r in rows).encode()
    rejects("source-family leakage", lambda: runtime.validate_payload(bad, anchors))
    crop = Path(receipt.root) / "train-features.jsonl"; original = crop.read_bytes()
    try:
        crop.write_bytes(original + b"\n")
        rejects("post-preflight file mutation", lambda: runtime.guarded_inputs(receipt, anchors, require_ml=False))
    finally:
        crop.write_bytes(original)
    bad = dict(payload); rows = [json.loads(line) for line in bad["validation-features.jsonl"].decode().splitlines()]
    rows[0]["split"] = "blind_test"
    bad["validation-features.jsonl"] = "\n".join(json.dumps(r) for r in rows).encode()
    rejects("blind-tagged input", lambda: runtime.validate_payload(bad, anchors))
    return tests


def read_json_bytes(value):
    return json.loads(value)


def readme():
    return """# P3B Colab CPU 操作说明

1. 打开 https://colab.research.google.com/ ，在「文件 → 上传笔记本」选择本目录的 `p3b-colab-cpu-baseline.ipynb`。
2. 「运行时 → 更改运行时类型」选择 Python 3，硬件加速器选择「无 / CPU」。无需 GPU/TPU 或付费计算。
3. 点击左侧文件夹图标，再点上传；上传本目录的 `p3b-colab-inputs.zip`，保留原文件名。它应位于 `/content/p3b-colab-inputs.zip`。不要解压、修改或另外拼装数据。
4. 手动运行 **A0-install**。如果安装了依赖，按提示点击「运行时 → 重新启动会话」，之后再运行 A1。安装失败或版本不兼容时停止，不要跳过错误。
5. 手动运行 **A1-preflight（PRE-FLIGHT）**，确认末尾显示 **PRE-FLIGHT PASS**。出现 FAIL 时停止并将错误交回 Codex。
6. 手动运行 **B1-train（TRAIN）**，在输入框输入 `TRAIN` 并回车。
7. 训练完成后运行 **C1-validate（VALIDATE）**，输入 `VALIDATE`。这只进行一次冻结验证，不据此调整参数或阈值。
8. 运行 **D1-export（EXPORT）**，输入 `EXPORT`；下载 `p3b-baseline-results.zip`。若下载未弹出，可从 Colab 左侧文件区进入打印的结果目录，找到结果 ZIP 下载。
9. 把结果 ZIP 交回 Codex 分析。不要把模型复制到 Image to CAD 的生产目录。

请逐个单元运行，不点击「全部运行」。输入确认词用于保证训练、验证和导出由你手动启动。
Colab 临时环境可能被回收；重启机器或会话被回收后可能需要重新上传文件。及时下载结果。
这次模型很小、使用 CPU 即可，但不保证具体耗时或 Colab 资源额度。无需 Drive、MCP、Gemini CLI 或远程代理。

数据为真实冻结的 94 个训练样本与 50 个验证样本；其中 1 个 AMBIGUOUS 只单独评估，不改成三类标签，也不用于训练。
依赖固定为 Python 3.10–3.13、numpy 2.2.6、scipy 1.15.3、scikit-learn 1.7.2、joblib 1.5.2、threadpoolctl 3.6.0。
训练使用 18 个特征、训练集标准化、balanced 类别权重、C=1、max_iter=1000、seed=314159；无 CNN。
6 个拒判阈值仅作预先冻结的探索报告；输出分数未校准，不能当作可靠真实概率。
SINGLE action coverage 的分母是全部 50 个验证样本；FALSE_MERGE_RATE 的分母始终是全部真实 TRUE_PARALLEL，包括被拒判的情况。
结果标记 EXPLORATORY_BASELINE_ONLY，不能宣布生产几何合并安全。

`logistic-pipeline.joblib` 使用 pickle 机制。仅加载可信来源的模型，并使用导出 environment.json 记录的相同 Python 主/次版本及完全相同的依赖版本。

本目录 `checksums.sha256` 校验交付文件；输入 ZIP 内另有逐成员校验和，notebook 会自动检查。
`HANDOFF-REPORT.md` 是完整交接报告，`LOCAL-PREPARATION-REPORT.json` 含文件、来源哈希与本地检查证据。

复现打包（开发者操作；不会训练）：活动项目根目录执行项目已有 Python 环境下的
`python tools/p3b/colab_cpu_handoff/build.py --out local-artifacts/product-fix-p3b/colab-cpu-新版本`。
输出目录必须尚不存在。脚本只读取冻结 train/validation 与明确引用的源文件和缓存；若缺失必须从报告列出的原路径/冻结来源恢复，不能补造数据。
`reproduction/` 保存本次脚本与 Jupyter schema 副本；可对照校验和恢复到活动项目的同名工具目录复现。
"""


def report_text(out, nb_path, zip_path, manifest, audit_report):
    fields = {"ACTIVE_CHECKOUT": str(PROJECT), "AGENTS_INSTRUCTIONS_READ": "NOT_FOUND (workspace, applicable parents and P3B paths inspected)",
        "GIT_STATUS": "Outer: index corrupt, untouched. Active: existing dirty worktree; full status in LOCAL-PREPARATION-REPORT.json",
        "TRAINING_DATA_FREEZE": "PASS", "DATA_INTEGRITY": "PASS", "LABEL_PROVENANCE": "VERIFIED",
        "HUMAN_LABEL_CERTAINTY": "不宣称全部标签绝对正确；像素贴合不等于图形语义真值",
        "TRAIN_SAMPLE_COUNT": 94, "VALIDATION_SAMPLE_COUNT": 50,
        "TRAIN_CLASS_COUNTS": manifest["train"]["class_counts"], "VALIDATION_CLASS_COUNTS": manifest["validation"]["class_counts"],
        "AMBIGUOUS_POLICY": "1 validation case ABSTENTION_EVALUATION; 0 hard training labels; 49 ordinary classification cases",
        "FEATURE_COUNT": 18, "FEATURE_SCHEMA_VERIFIED": "YES", "TRAIN_VALIDATION_LEAKAGE": "NONE", "BLIND_TOUCHED": "NO",
        "FROZEN_MANIFEST_SHA256": manifest["frozen_manifest_sha256"], "CLOUD_INPUT_STATUS": "NOT_VERIFIED",
        "CHATGPT_LIBRARY_COMPLETE_DATASET_STATUS": "UNVERIFIED", "GOOGLE_DRIVE_DATASET_STATUS": "NOT_VERIFIED",
        "NOTEBOOK_CREATED": "YES", "NOTEBOOK_PATH": str(nb_path), "NOTEBOOK_SIZE": nb_path.stat().st_size,
        "NOTEBOOK_SHA256": sha(nb_path), "INPUT_PACKAGE_CREATED": "YES", "INPUT_PACKAGE_PATH": str(zip_path),
        "INPUT_PACKAGE_SIZE": str(zip_path.stat().st_size) + " bytes", "INPUT_PACKAGE_SHA256": sha(zip_path),
        "CHECKSUM_MANIFEST": str(out / "checksums.sha256"), "README_PATH": str(out / "README-中文.md"),
        "LOCAL_STATIC_CHECK": "PASS", "LOCAL_DATA_PREFLIGHT": "PASS (ML dependency check not run; no sklearn installed)",
        "COLAB_CPU_EXECUTION": "NOT_RUN", "ACTUAL_LOGISTIC_TRAINING": "NOT_RUN", "ACTUAL_VALIDATION_METRICS": "NOT_AVAILABLE",
        "CNN_TRAINED": "NO", "PRODUCTION_CODE_CHANGED": "NO", "DXF_CHANGED": "NO", "OCR_CHANGED": "NO",
        "GOOGLE_LOGIN_ATTEMPTED": "NO", "DRIVE_MOUNTED": "NO", "MCP_REQUIRED": "NO", "PAID_COMPUTE_STARTED": "NO",
        "BACKGROUND_TASKS_CREATED": "NO", "HANDOFF_STATUS": "READY_FOR_MANUAL_COLAB",
        "NEXT_USER_ACTION": "打开 Colab，上传 notebook 和输入 ZIP；A0 后运行 A1 PRE-FLIGHT，PASS 后逐个手动运行 B1/C1/D1。"}
    body = "# IMAGE TO CAD — P3B COLAB CPU HANDOFF REPORT\n\n```text\n" + "\n".join(k + ": " + str(v) for k, v in fields.items()) + "\n```\n"
    body += "\n本轮实际核验 4 份 V2 人工记录的 schema、样本摘要、标签版本、历史与 undo replay，并逐样本核对当前复核覆盖规则、冻结视图和来源分组。"
    body += f"核验 {audit_report['source_original_files_verified']} 个原始来源文件、{audit_report['crop_files_verified']} 个输入裁片文件 SHA256。"
    body += "18 个特征从已绑定实现重新提取，训练统计量与冻结值一致；未 fit 任何分类器。6 个 X/U 排除（5 INVALID_NOMINATION，1 UNCLEAR_TARGET）。\n"
    body += "\n历史最终计数/种子/特征/参数与本轮一致。更早验证记录中的两个 AMBIGUOUS 已按保存的人工复核变为 TRUE_PARALLEL；原始答案保留。"
    body += "现有四分类 runner 未复用作三分类训练入口。历史 MCP 兼容限制不适用于本轮手动上传方案。\n"
    body += "\n静态检查：使用官方 Jupyter nbformat v4.5 schema 通过验证，所有代码单元 AST 可解析，执行计数为空、输出为空。"
    body += "实际执行同一嵌入式 A1 数据预检（本地关闭 ML 版本检查），以及缺少预检、数据-only receipt、改动超参数、训练混入 AMBIGUOUS、来源泄漏、预检后文件变更、Blind 标记拒绝测试。"
    body += "这些检查不是 Colab 或模型训练通过的证明。\n"
    body += "\n输入包只含数值特征和必要元数据，保留记录引用/来源/裁片/特征哈希，不包含原始图样、旧标签文件、Blind、凭据或大型缓存。"
    body += "只有已冻结排除项的 ID/原因作为审计元数据；不会当成监督标签。输入、配置、校验清单与 ZIP 哈希绑定在 notebook 中；每阶段重新检查。\n"
    body += "\nLOCAL_AVAILABLE、全部具体哈希、Git 状态、来源变更与测试证据见 LOCAL-PREPARATION-REPORT.json。CLOUD_VERIFIED 为空；没有查询或登录 Library / Drive。"
    body += "交付目录全部文件总量与校验清单可直接核对。生产 app/tests 的本轮前后快照一致；原有修改保留，无提交或清理。\n"
    body += "\n依赖/API 依据：[scikit-learn 1.7 LogisticRegression](https://scikit-learn.org/1.7/modules/generated/sklearn.linear_model.LogisticRegression.html)、"
    body += "[模型持久化条件](https://scikit-learn.org/stable/model_persistence.html)、[官方 notebook schema](https://raw.githubusercontent.com/jupyter/nbformat/v5.10.4/nbformat/v4/nbformat.v4.5.schema.json)。\n"
    return body


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        build(args.out.resolve())
    except FileNotFoundError as error:
        print("BLOCKED_MISSING_REQUIRED_INPUT: " + str(error), file=sys.stderr)
        print("Restore the exact frozen file/cache from its recorded SHA256 source; never regenerate labels or use placeholders.", file=sys.stderr)
        raise
