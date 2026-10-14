"""Stage-end saving only. No training, model loading, cloud login or worker starts on import."""

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SAVE_STAGES = {"A1", "B1", "C1", "D1", "FIRST_BASELINE"}
DRIVE_MOUNT = Path("/content/drive")
RUN_SUFFIX = Path("MyDrive/Image-to-CAD-ML/P3B/runs")


def save_time():
    return datetime.now(timezone.utc).isoformat()


def save_check(ok, message):
    if not ok:
        raise ValueError(message)


def save_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def new_write(path, data):
    # No replace/overwrite path. All destinations live in this session's unique run.
    with Path(path).open("xb") as stream:
        stream.write(data)
        stream.flush()


@dataclass
class SaveSession:
    mount_root: str
    run_dir: str
    run_id: str
    identity: dict
    mount_probe: object
    scope: str
    completed: dict = field(default_factory=dict)
    failed: bool = False
    pending: dict | None = None
    retry_used: int = 0


class SaveFailure(RuntimeError):
    pass


def _initialize_store(mount_root, mount_probe, run_id=None, scope="LOCAL_SIMULATION_ONLY"):
    """Injectable filesystem backend for local tests; production entry fixes /content/drive."""
    try:
        save_check(mount_probe(), "Drive is not mounted; automatic saving must stop")
        mount_root = Path(mount_root).resolve()
        base = (mount_root / RUN_SUFFIX).resolve()
        save_check(base.is_relative_to(mount_root), "Run base escapes mounted Drive")
        run_id = run_id or (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex)
        save_check(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id) is not None, "Unsafe run_id")
        run_dir = (base / run_id).resolve()
        save_check(run_dir.is_relative_to(base) and not run_dir.exists(), "Duplicate run_id; never overwrite old run")
        base.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(exist_ok=False)
        identity = {"run_id": run_id, "session_id": uuid.uuid4().hex, "created_at_utc": save_time(), "verification_scope": scope}
        probe = ("P3B bounded write/read probe " + identity["session_id"] + "\n").encode()
        path = run_dir / "initial-write-read-probe.txt"; new_write(path, probe)
        save_check(path.stat().st_size == len(probe) and path.read_bytes() == probe, "Initialization write/readback mismatch")
        identity["probe_sha256"] = hashlib.sha256(probe).hexdigest()
        identity["mounted_path_readback"] = "PASS" if scope != "LOCAL_SIMULATION_ONLY" else "LOCAL_SIMULATION_PASS"
        identity["drive_service_independent_confirmation"] = "NOT_RUN"
        new_write(run_dir / "run-identity.json", save_json_bytes(identity))
        save_check(json.loads((run_dir / "run-identity.json").read_text(encoding="utf-8")) == identity, "Run identity readback mismatch")
        session = SaveSession(str(mount_root), str(run_dir), run_id, identity, mount_probe, scope)
        print("DRIVE_INIT PASS —", scope, "run:", run_dir)
        print("Drive service independent confirmation: NOT_RUN; mounted-path readback is not an independent durability guarantee.")
        return session
    except Exception as error:
        print("SAVE_FAILED stage=DRIVE_INIT:", str(error))
        raise SaveFailure("DRIVE_INIT failed; no subsequent autosave/compute permitted") from error


def initialize_drive():
    print("挂载Drive后，本notebook代码技术上能访问整个Drive，不只输出目录。")
    print("本程序的写入范围仅 MyDrive/Image-to-CAD-ML/P3B/runs/唯一run_id；不更改共享权限。")
    save_check(input("确认后输入 DRIVE；随后仅在Colab界面完成授权：") == "DRIVE", "Drive authorization not requested")
    try:
        from google.colab import drive
        drive.mount(str(DRIVE_MOUNT))
    except Exception as error:
        print("SAVE_FAILED stage=DRIVE_INIT:", str(error))
        raise SaveFailure("User Drive mounting failed; stop") from error
    return _initialize_store(DRIVE_MOUNT, lambda: os.path.ismount(DRIVE_MOUNT),
                             scope="MOUNTED_PATH_READBACK_ONLY")


def ensure_save_session(session, previous=None, allow_failed=False):
    save_check(isinstance(session, SaveSession), "Drive initialization has not passed")
    save_check(not session.failed or allow_failed, "SAVE_FAILED is pending; use one save-only retry or manual download; do not recompute")
    save_check(session.mount_probe(), "Drive mount unavailable")
    run_dir = Path(session.run_dir).resolve()
    base = (Path(session.mount_root).resolve() / RUN_SUFFIX).resolve()
    save_check(run_dir.parent == base and run_dir.name == session.run_id, "Run directory escaped allowlist")
    save_check(json.loads((run_dir / "run-identity.json").read_text(encoding="utf-8")) == session.identity,
               "Run identity changed; stop without overwriting")
    if previous:
        save_check(previous in session.completed, previous + " has no verified COMPLETE marker")
        completion = session.completed[previous]
        save_check(save_hash(completion["marker_path"]) == completion["marker_sha256"], "Previous completion marker changed")
    return run_dir


def file_identity(folder):
    paths = sorted(Path(folder).iterdir())
    save_check(paths and all(p.is_file() and not p.is_symlink() for p in paths), "Stage must contain actual flat local files")
    return [{"name": p.name, "size_bytes": p.stat().st_size, "sha256": save_hash(p)} for p in paths]


def prepare_save_stage(stage, content, data_identity):
    save_check(stage in SAVE_STAGES and content, "Unknown/empty save stage")
    local = Path(tempfile.mkdtemp(prefix="p3b-stage-")) / ("p3b-" + stage); local.mkdir()
    print("LOCAL_STAGE_DIR stage=" + stage + ":", local)
    for name, data in content.items():
        save_check(Path(name).name == name and name not in ("COMPLETE.json", "stage-manifest.json", "checksums.sha256"), "Unsafe stage filename")
        save_check(isinstance(data, bytes), "Only fully generated local artifact bytes may be saved")
        new_write(local / name, data)
    records = file_identity(local)
    new_write(local / "checksums.sha256", "".join(r["sha256"] + "  " + r["name"] + "\n" for r in records).encode())
    new_write(local / "stage-manifest.json", save_json_bytes({"stage": stage, "prepared_at_utc": save_time(),
        "status": "LOCAL_PREPARED_NOT_DRIVE_COMPLETE", "data_identity": data_identity, "files": records}))
    return str(local)


def _copy_new_checked(source, destination):
    destination = Path(destination)
    partial = destination.with_name(destination.name + ".part")
    save_check(not destination.exists(), "Destination exists; overwrite prohibited")
    with Path(source).open("rb") as src, partial.open("xb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
        dst.flush()
    save_check(partial.stat().st_size == Path(source).stat().st_size and save_hash(partial) == save_hash(source), "Drive partial readback SHA256 mismatch")
    partial.rename(destination)
    save_check(save_hash(destination) == save_hash(source), "Drive final-path readback SHA256 mismatch")


def make_local_backup(folder):
    folder = Path(folder); path = folder.parent / (folder.name + "-manual-backup.zip")
    if not path.exists():
        with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for p in sorted(folder.iterdir()): archive.write(p, folder.name + "/" + p.name)
    return str(path)


def save_stage(session, stage, local_folder, retry=False):
    """Copy immutable local files, verify mounted readback, then publish completion marker."""
    snapshot = []
    try:
        snapshot = file_identity(local_folder)
        run_dir = ensure_save_session(session, allow_failed=retry)
        save_check(stage in SAVE_STAGES and stage not in session.completed, "Stage already saved or unknown; no overwrite")
        if retry:
            save_check(session.pending and session.pending["files"] == snapshot and session.pending["stage"] == stage,
                       "Local pending artifact/hash changed; retry blocked")
        stage_dir = run_dir / stage; stage_dir.mkdir(exist_ok=True)
        attempt_dir = stage_dir / ("attempt-" + uuid.uuid4().hex); attempt_dir.mkdir(exist_ok=False)
        save_check(attempt_dir.resolve().is_relative_to(run_dir), "Attempt escaped unique run")
        for item in snapshot:
            _copy_new_checked(Path(local_folder) / item["name"], attempt_dir / item["name"])
            save_check((attempt_dir / item["name"]).stat().st_size == item["size_bytes"]
                       and save_hash(attempt_dir / item["name"]) == item["sha256"], "Saved identity mismatch")
        save_check(file_identity(local_folder) == snapshot, "Local artifacts changed during copy")
        completion = {"status": "COMPLETE", "stage": stage, "run_id": session.run_id,
            "completed_at_utc": save_time(), "verification_scope": session.scope,
            "mounted_path_readback": "PASS" if session.scope != "LOCAL_SIMULATION_ONLY" else "LOCAL_SIMULATION_PASS",
            "drive_service_independent_confirmation": "NOT_RUN", "files": snapshot,
            "retry": retry, "limit": "No guarantee of remote service persistence or Colab survival"}
        marker = attempt_dir / "COMPLETE.json"
        marker_bytes = save_json_bytes(completion)
        # Completion appears only after all payload readbacks. Pending/partial files are never completion markers.
        pending_marker = attempt_dir / "completion.pending"
        new_write(pending_marker, marker_bytes)
        save_check(pending_marker.read_bytes() == marker_bytes, "Completion pending readback failed")
        pending_marker.rename(marker)
        save_check(marker.read_bytes() == marker_bytes, "Completion marker readback failed; completion not confirmed")
        session.completed[stage] = {"marker_path": str(marker), "marker_sha256": save_hash(marker),
                                    "completed_at_utc": completion["completed_at_utc"]}
        session.failed = False; session.pending = None
        print("SAVE_COMPLETE stage=" + stage, "scope=" + session.scope, "marker=" + str(marker))
        print("MOUNTED_READBACK_VERIFIED; DRIVE_SERVICE_CONFIRMED=NOT_RUN")
        return session.completed[stage]
    except Exception as error:
        print("SAVE_FAILED stage=" + stage + ": " + str(error))
        backup = None
        try:
            if Path(local_folder).is_dir():
                backup = make_local_backup(local_folder)
        except Exception as backup_error:
            print("SAVE_FAILED stage=" + stage + " local backup creation also failed:", str(backup_error))
        if isinstance(session, SaveSession):
            session.failed = True
            if not retry and stage not in session.completed and snapshot:
                session.pending = {"stage": stage, "local_folder": str(local_folder), "files": snapshot, "backup_zip": backup}
        print("临时成果保留：", local_folder, "手动备份ZIP：", backup)
        print("停止后续计算/自动保存。使用备用下载单元；修正原因后最多一次 SAVE_RETRY_ONLY，不会训练。")
        raise SaveFailure("SAVE_FAILED " + stage + "; local backup: " + str(backup)) from error


def save_generated_stage(session, stage, factory):
    try:
        content, identity = factory()
        local = prepare_save_stage(stage, content, identity)
        return save_stage(session, stage, local)
    except SaveFailure:
        raise
    except Exception as error:
        if isinstance(session, SaveSession): session.failed = True
        print("SAVE_FAILED stage=" + stage + " during local generation:", str(error))
        print("Existing PREFLIGHT/TRAIN_RUN/RESULT_ZIP objects remain in session; no COMPLETE marker. See LOCAL_STAGE_DIR if printed.")
        raise SaveFailure("SAVE_FAILED " + stage + " local preparation; stop and preserve existing local results") from error


def retry_pending_save_only(session, reason=None):
    save_check(isinstance(session, SaveSession) and session.failed and session.pending, "No pending SAVE_FAILED stage")
    save_check(session.retry_used == 0, "The one bounded save-only retry has been used; download manually")
    reason = reason if reason is not None else input("请说明已修正的保存故障（如已恢复挂载/网络/权限）：").strip()
    save_check(bool(reason and reason.strip()), "A concrete corrected-fault reason is required")
    session.retry_used += 1
    print("SAVE_RETRY_ONLY —", session.pending["stage"], "reason:", reason, "(no training/evaluation)")
    return save_stage(session, session.pending["stage"], session.pending["local_folder"], retry=True)


def download_local_backup(session, result_zip=None):
    path = result_zip if result_zip and Path(result_zip).is_file() else (
        session.pending["backup_zip"] if isinstance(session, SaveSession) and session.pending else None)
    save_check(path is not None and Path(path).is_file(), "No local backup ready; use the file browser paths printed above")
    print("MANUAL_DOWNLOAD:", path)
    from google.colab import files
    files.download(str(path))


def preflight_save_content(receipt, anchors):
    rows, matrices, docs, identity = guarded_inputs(receipt, anchors)
    report = {"status": "PASS", "data_identity": identity, "train": len(rows["train"]), "validation": len(rows["validation"]),
              "feature_count": 18, "leakage": "NONE", "blind_inputs": 0, "AMBIGUOUS": anchors["manifest"]["ambiguous_sample_ids"]}
    return {"preflight-report.json": save_json_bytes(report), "environment.json": save_json_bytes(environment()),
            "data-identity.json": save_json_bytes(identity), "feature-schema.json": save_json_bytes(docs["feature-schema.json"]),
            "class-map.json": save_json_bytes(docs["class-map.json"]), "training-config.json": save_json_bytes(docs["training-config.json"])}, identity


def training_save_content(receipt, anchors, run):
    guarded_run(receipt, anchors, run)
    content = {"logistic-pipeline.joblib": model_bytes(run["model"]), "training-config.json": save_json_bytes(run["config"]),
        "training-log.json": save_json_bytes({"status": "TRAIN_COMPLETE", "started_at_utc": run["started_at_utc"],
            "logged_at_utc": save_time(), "model_sha256": run["model_sha256"], "fit_samples": 94, "feature_count": 18,
            "scaler_n_samples_seen": int(run["model"].named_steps["scaler"].n_samples_seen_),
            "solver_iterations": run["model"].named_steps["classifier"].n_iter_.tolist(),
            "environment": run["environment"], "data_identity": run["identity"],
            "scope": "EXPLORATORY_BASELINE_ONLY; no claim of exclusive remote execution history"})}
    return content, run["identity"]


def validation_save_content(receipt, anchors, run):
    guarded_run(receipt, anchors, run)
    save_check(run["validation"] is not None and hash_bytes(canonical(run["validation"])) == run["validation_sha256"], "Validation identity mismatch")
    local = Path(tempfile.mkdtemp(prefix="p3b-csv-"))
    value = run["validation"]; predictions = value["predictions"]
    write_csv(local / "predictions.csv", predictions, list(predictions[0]))
    matrix = value["metrics"]["overall"]["confusion_matrix"]
    write_csv(local / "confusion-matrix.csv", [{"truth": c, **dict(zip(CLASSES, matrix[i]))}
              for i, c in enumerate(CLASSES)], ["truth"] + CLASSES)
    return {"metrics.json": save_json_bytes(value["metrics"]), "predictions.csv": (local / "predictions.csv").read_bytes(),
            "confusion-matrix.csv": (local / "confusion-matrix.csv").read_bytes(),
            "abstention-evaluation.json": save_json_bytes(value["abstention"])}, run["identity"]


def export_save_content(result_zip, data_identity, completed):
    path = Path(result_zip)
    save_check(path.is_file(), "Final ZIP not generated")
    return {"p3b-baseline-results.zip": path.read_bytes(), "export-log.json": save_json_bytes({"exported_at_utc": save_time(),
            "zip_size_bytes": path.stat().st_size, "zip_sha256": save_hash(path), "prior_stage_markers": completed,
            "verification": "Mounted-path readback only; no independent Drive service confirmation"})}, data_identity
