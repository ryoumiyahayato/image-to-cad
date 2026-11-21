"""Import source-verified raw TSV/CTC observations, never previous CAD decisions.

This reads an explicitly supplied native publication and its recorded receipt.
It does not restore a job, read adopted-object lists, run OCR, fit geometry, or
relax any existing checkpoint/resume guard. Missing historical engine hashes
remain unknown in a separate, explicitly enabled historical TSV namespace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "cad_photo_to_dxf"
sys.path.insert(0, str(APP))


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha(path):
    from app.native_objects.execution import file_sha

    return file_sha(path)


def _inside(root, relative):
    path = (Path(root) / relative).resolve()
    if Path(root).resolve() not in path.parents:
        raise ValueError(
            "RAW_IMPORT_PATH_OUTSIDE_DECLARED_PUBLICATION:" + str(relative)
        )
    return path


def _published_file(published, manifest, relative):
    path = _inside(published, relative)
    expected = manifest["files"].get(Path(relative).as_posix())
    if expected is None:
        raise ValueError("RAW_IMPORT_FILE_NOT_IN_PUBLICATION_MANIFEST:" + str(relative))
    if _sha(path) != expected["sha256"] or path.stat().st_size != expected["bytes"]:
        raise ValueError("RAW_IMPORT_PUBLICATION_FILE_HASH_MISMATCH:" + str(relative))
    return path


def _source_crop(image, box):
    if (
        not isinstance(box, list)
        or len(box) != 4
        or any(isinstance(value, bool) or not isinstance(value, int) for value in box)
    ):
        raise ValueError("RAW_IMPORT_INVALID_SOURCE_CROP")
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= image.shape[1] and 0 <= y0 < y1 <= image.shape[0]):
        raise ValueError("RAW_IMPORT_SOURCE_CROP_OUTSIDE_IMAGE")
    return image[y0:y1, x0:x1]


def _check_png(path, expected):
    import numpy as np
    from PIL import Image

    with Image.open(path) as picture:
        actual = np.asarray(picture.convert("L"))
    if not np.array_equal(actual, expected):
        raise ValueError("RAW_IMPORT_RECOGNITION_PNG_DIFFERS_FROM_ORIGINAL_SOURCE")


def _original_engine(meta, receipt):
    original = meta.get("engine_identity")
    if (
        original
        and original.get("executable_sha256")
        and original.get("traineddata_sha256")
    ):
        return original, True
    engine = receipt["engine_identity"]
    common = {
        "name": "tesseract",
        "version": engine["engine_version"],
        "language": "eng",
        "oem": 1,
        "CPU_threads": 1,
    }
    if (
        engine.get("historical_model_byte_identity_proven") is True
        and engine.get("historical_executable_sha256")
        and engine.get("historical_model_sha256")
    ):
        common.update(
            executable_sha256=engine["historical_executable_sha256"],
            traineddata_sha256=engine["historical_model_sha256"],
        )
        return common, True
    common.update(
        historical_executable_sha256=None,
        historical_model_sha256=None,
        historical_model_byte_identity_proven=False,
    )
    return common, False


def _tesseract_record(
    relative,
    expected,
    *,
    published,
    manifest,
    receipt,
    image,
    source_sha,
    dpi,
    cache,
    proofs,
    allow_historical,
):
    import numpy as np
    from app.native_objects.observation_cache import pixels_identity, tesseract_spec

    meta_path = _published_file(published, manifest, "evidence/" + relative)
    tsv_path = _published_file(
        published, manifest, "evidence/" + str(Path(relative).with_suffix(".tsv"))
    )
    png_path = _published_file(
        published, manifest, "evidence/" + str(Path(relative).with_suffix(".png"))
    )
    meta = _read(meta_path)
    spec = meta["specification"]
    if (
        expected["meta_sha256"] != _sha(meta_path)
        or expected["tsv_sha256"] != _sha(tsv_path)
        or expected["image_sha256"] != _sha(png_path)
        or expected["specification"] != spec
        or meta.get("status") != "COMPLETED"
        or meta.get("tsv_sha256") != _sha(tsv_path)
        or meta.get("image_sha256") != _sha(png_path)
    ):
        raise ValueError("RAW_IMPORT_TSV_RECEIPT_OR_METADATA_MISMATCH")
    if (
        spec.get("source_pixels_modified") is not False
        or spec.get("pixel_scale") != [1, 1]
        or spec.get("padding_replaces_source_pixels") is not False
        or spec.get("language") != "eng"
        or spec.get("recognition_dpi") != dpi
    ):
        raise ValueError("RAW_IMPORT_TSV_SOURCE_CONFIGURATION_CHANGED")
    crop = _source_crop(image, spec["crop_xyxy_px"])
    if pixels_identity(crop)["sha256"] != spec["crop_array_sha256"]:
        raise ValueError("RAW_IMPORT_TSV_CROP_HASH_MISMATCH")
    padding = spec["external_white_padding_px"]
    if isinstance(padding, bool) or not isinstance(padding, int) or padding < 0:
        raise ValueError("RAW_IMPORT_INVALID_EXTERNAL_PADDING")
    recognition_input = np.pad(crop, padding, constant_values=255) if padding else crop
    _check_png(png_path, recognition_input)
    command = meta["command"]
    for flag, value in (
        ("--psm", str(spec["psm"])),
        ("--dpi", str(dpi)),
        ("-l", "eng"),
        ("--oem", "1"),
    ):
        if command.count(flag) != 1 or command[command.index(flag) + 1] != value:
            raise ValueError("RAW_IMPORT_TSV_COMMAND_CONFIGURATION_MISMATCH:" + flag)
    engine, exact = _original_engine(meta, receipt)
    if (
        meta["engine_version"] != engine["version"]
        or command[0] != receipt["engine_identity"]["executable"]
    ):
        raise ValueError("RAW_IMPORT_TSV_ORIGINAL_ENGINE_MISMATCH")
    if exact:
        key_spec = tesseract_spec(
            crop,
            recognition_input,
            padding=padding,
            psm=spec["psm"],
            dpi=dpi,
            engine=engine,
        )
    elif allow_historical:
        # Do not populate exact-engine fields using the receipt's current_*
        # hashes: those describe a later import inspection, not the old calls.
        from app.native_objects.observation_cache import SCHEMA

        key_spec = {
            "schema": SCHEMA,
            "kind": "historical-tesseract-tsv",
            "crop": pixels_identity(crop),
            "recognition_input": pixels_identity(recognition_input),
            "external_white_padding_px": padding,
            "psm": spec["psm"],
            "recognition_dpi": dpi,
            "engine": engine,
            "source_pixels_modified": False,
            "pixel_scale": [1, 1],
            "source_sha256": source_sha,
        }
    else:
        raise ValueError("HISTORICAL_ENGINE_BYTES_UNPROVEN_NO_EXACT_CACHE_IMPORT")
    producer = {
        "origin": "imported_verified_raw_observation",
        "original_path": relative,
        "module": "app.native_objects.text_regions",
        "module_sha256": receipt["unchanged_producers"][
            "app.native_objects.text_regions"
        ],
        "source_sha256": source_sha,
        "metadata": meta,
        "engine": engine,
        "historical_model_byte_identity_proven": exact,
        "old_adoption_loaded": False,
        "raw_text_rewritten": False,
        "evidence_blobs": {
            **proofs,
            "original_metadata": cache.blob(meta_path.read_bytes()),
            "original_recognition_png": cache.blob(png_path.read_bytes()),
        },
    }
    return cache.put(key_spec, tsv_path.read_bytes(), producer)


def _model_record(
    relative,
    expected,
    *,
    published,
    manifest,
    receipt,
    image,
    source_sha,
    cache,
    proofs,
    recognizer,
):
    from app.native_objects.independent_recognizer import prepare_model_input
    from app.native_objects.observation_cache import (
        canonical_bytes,
        digest,
        model_spec,
        pixels_identity,
    )

    record_path = _published_file(published, manifest, "evidence/" + relative)
    record = _read(record_path)
    if expected["sha256"] != _sha(record_path):
        raise ValueError("RAW_IMPORT_MODEL_RECORD_RECEIPT_MISMATCH")
    stage = Path(relative).parent.parent
    identity_path = _published_file(
        published,
        manifest,
        (Path("evidence") / stage / "model_identity.json").as_posix(),
    )
    identity = _read(identity_path)
    if (
        digest(identity) != record["model_identity_sha256"]
        or identity != receipt["model_identity"]
    ):
        raise ValueError("RAW_IMPORT_MODEL_IDENTITY_MISMATCH")
    crop_box = record["context"]["crop_xyxy_px"]
    crop = _source_crop(image, crop_box)
    actual = pixels_identity(crop)
    raw = record["raw_model_output"]
    if (
        record.get("source_pixels_modified") is not False
        or record.get("source_case_expected_text_read") is not False
        or actual["sha256"] != record["source_array_sha256"]
        or actual["sha256"] != raw["input_array_sha256"]
        or actual["sha256"] != expected["source_crop_sha256"]
        or actual["shape_px"] != raw["input_shape_px"]
    ):
        raise ValueError("RAW_IMPORT_MODEL_SOURCE_HASH_OR_POLICY_MISMATCH")
    png_path = _published_file(
        published,
        manifest,
        (Path("evidence") / stage / record["source_png"]).as_posix(),
    )
    if (
        _sha(png_path) != record["source_png_sha256"]
        or _sha(png_path) != expected["source_png_sha256"]
    ):
        raise ValueError("RAW_IMPORT_MODEL_SOURCE_PNG_HASH_MISMATCH")
    _check_png(png_path, crop)
    old_key = digest(
        {
            "source_sha256": source_sha,
            "crop": crop_box,
            "crop_sha256": actual["sha256"],
            "model_sha256": identity["model_sha256"],
        }
    )
    if record["observation_key"] != old_key:
        raise ValueError("RAW_IMPORT_ORIGINAL_MODEL_KEY_MISMATCH")
    original, tensor = prepare_model_input(crop)
    key_spec = model_spec(original, tensor, identity)
    if key_spec != model_spec(original, tensor, recognizer.identity):
        raise ValueError("RAW_IMPORT_INSTALLED_MODEL_OR_RUNTIME_DIFFERS_FROM_ORIGINAL")
    if (
        raw["model_tensor_sha256"] != key_spec["model_tensor"]["sha256"]
        or raw["model_tensor_shape"] != key_spec["model_tensor"]["shape"]
        or raw.get("source_geometry_modified") is not False
        or raw.get("raw_transcription_rewritten") is not False
        or raw.get("resize_for_model_inference_only") is not True
    ):
        raise ValueError("RAW_IMPORT_MODEL_TENSOR_OR_RAW_POLICY_MISMATCH")
    tokens = raw["raw_CTC_tokens"]
    last_time = -1
    for token in tokens:
        index, score = token["token_index"], token["score"]
        if (
            not 0 < index < len(recognizer.characters)
            or not math.isfinite(score)
            or not 0 <= score <= 1
            or token["character"] != recognizer.characters[index]
            or token["time_step"] <= last_time
        ):
            raise ValueError("RAW_IMPORT_MODEL_TOKEN_DICTIONARY_OR_SCORE_MISMATCH")
        last_time = token["time_step"]
    if "".join(token["character"] for token in tokens) != raw["raw_text"]:
        raise ValueError("RAW_IMPORT_MODEL_RAW_TEXT_DIFFERS_FROM_SAVED_TOKENS")
    producer = {
        "origin": "imported_verified_raw_observation",
        "original_path": relative,
        "module": "app.native_objects.independent_recognizer",
        "module_sha256": receipt["unchanged_producers"][
            "app.native_objects.independent_recognizer"
        ],
        "source_sha256": source_sha,
        "engine": identity,
        "old_adoption_loaded": False,
        "raw_text_rewritten": False,
        "evidence_blobs": {
            **proofs,
            "original_model_record": cache.blob(record_path.read_bytes()),
            "original_recognition_png": cache.blob(png_path.read_bytes()),
            "original_model_identity": cache.blob(identity_path.read_bytes()),
        },
    }
    return cache.put(key_spec, canonical_bytes(raw), producer)


def import_observations(
    *,
    source,
    published,
    receipt_path,
    resource_evidence,
    producer_source,
    output,
    source_audit=None,
    allow_historical_tesseract=False,
):
    from app.native_objects.independent_recognizer import IndependentRecognizer
    from app.native_objects.job import make_job
    from app.native_objects.observation_cache import ObservationCache, digest
    from app.native_objects.source_import import prepare_source

    source, published, output = (
        Path(source).resolve(),
        Path(published).resolve(),
        Path(output).resolve(),
    )
    receipt_path, producer_source = (
        Path(receipt_path).resolve(),
        Path(producer_source).resolve(),
    )
    if output.exists():
        raise FileExistsError("RAW_IMPORT_REQUIRES_NEW_CACHE_DIRECTORY")
    publication_path = published / "publication_manifest.json"
    manifest, receipt = _read(publication_path), _read(receipt_path)
    imported_path = _published_file(
        published, manifest, "evidence/import_manifest.json"
    )
    imported = _read(imported_path)
    source_sha = _sha(source)
    if any(
        value != source_sha
        for value in (
            manifest["identity"]["source_sha256"],
            receipt["source_sha256"],
            imported["source_sha256"],
        )
    ):
        raise ValueError("RAW_IMPORT_ORIGINAL_SOURCE_FILE_HASH_MISMATCH")
    if source_audit is not None:
        audit = _read(source_audit)
        if (
            audit["source_sha256"] != source_sha
            or audit["source_revision_receipt_sha256"] != _sha(receipt_path)
            or audit["code_sha256"] != manifest["identity"]["algorithm_sha256"]
        ):
            raise ValueError("RAW_IMPORT_SOURCE_AUDIT_RECEIPT_OR_CODE_BINDING_MISMATCH")
    params = imported["job"]
    job = make_job(
        source,
        output / "not_executed.dxf",
        params["roi_source_xyxy_px"],
        dpi=params["recognition_dpi"],
        page_number=params.get("page_number_1based"),
        frame_number=params.get("frame_number_1based"),
        orientation=params["orientation_clockwise_degrees"],
    )
    prepared = prepare_source(job, persist=False)
    if (
        prepared.manifest["cache_identity"] != imported["cache_identity"]
        or prepared.manifest["working_array_sha256"] != receipt["source_array_sha256"]
    ):
        raise ValueError("RAW_IMPORT_DECODED_SOURCE_SELECTION_OR_PIXELS_MISMATCH")
    producer_files = {}
    for module in (
        "app.native_objects.text_regions",
        "app.native_objects.independent_recognizer",
    ):
        path = producer_source / (module.replace(".", "/") + ".py")
        if _sha(path) != receipt["unchanged_producers"][module]:
            raise ValueError(
                "RAW_IMPORT_ORIGINAL_PRODUCER_SOURCE_HASH_MISMATCH:" + module
            )
        producer_files[module] = path
    cache = ObservationCache(
        output, create=True, allow_historical_tesseract=allow_historical_tesseract
    )
    proof_paths = {
        "original_publication_manifest": publication_path,
        "original_import_manifest": imported_path,
        "original_receipt": receipt_path,
        "original_resource_evidence": Path(resource_evidence),
        **producer_files,
    }
    if source_audit is not None:
        proof_paths["original_source_audit"] = Path(source_audit)
    proofs = {name: cache.blob(path.read_bytes()) for name, path in proof_paths.items()}
    recognizer = IndependentRecognizer() if receipt.get("independent_OCR") else None
    results = []
    for kind, rows in (
        ("tesseract", receipt["OCR"]),
        ("ppocr", receipt.get("independent_OCR", {})),
    ):
        for relative, expected in sorted(rows.items()):
            try:
                common = {
                    "published": published,
                    "manifest": manifest,
                    "receipt": receipt,
                    "image": prepared.gray,
                    "source_sha": source_sha,
                    "cache": cache,
                    "proofs": proofs,
                }
                if kind == "tesseract":
                    result = _tesseract_record(
                        relative,
                        expected,
                        **common,
                        dpi=job.dpi,
                        allow_historical=allow_historical_tesseract,
                    )
                else:
                    result = _model_record(
                        relative, expected, **common, recognizer=recognizer
                    )
                results.append(
                    {
                        "path": relative,
                        "status": "IMPORTED",
                        "kind": result["kind"],
                        "key": result["key"],
                        "payload_sha256": result["payload_sha256"],
                    }
                )
            except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
                results.append(
                    {
                        "path": relative,
                        "status": "NOT_IMPORTED",
                        "kind": kind,
                        "reason": f"{type(error).__name__}:{error}",
                    }
                )
    imported_rows = [row for row in results if row["status"] == "IMPORTED"]
    rejected = [row for row in results if row["status"] == "NOT_IMPORTED"]
    report = {
        "schema": "native-raw-observation-import-v1",
        "source_sha256": source_sha,
        "source_array_sha256": prepared.manifest["working_array_sha256"],
        "proofs": proofs,
        "original_engine_identity": receipt["engine_identity"],
        "allow_historical_tesseract": bool(allow_historical_tesseract),
        "imported_records": len(imported_rows),
        "not_imported_records": len(rejected),
        "unique_observations": len({row["key"] for row in imported_rows}),
        "counts": {
            kind: sum(row["kind"] == kind for row in imported_rows)
            for kind in sorted({row["kind"] for row in imported_rows})
        },
        "cache": cache.snapshot(),
        "records": results,
        "passed": not rejected,
        "recognition_calls": 0,
        "source_file_unchanged": _sha(source) == source_sha,
        "adoption_geometry_or_review_loaded": False,
        "old_resume_guards_modified_or_bypassed": False,
        "historical_digests_not_replaced_by_current_import_environment": True,
    }
    report_bytes = json.dumps(
        report, ensure_ascii=False, indent=2, allow_nan=False
    ).encode("utf-8")
    (output / "import_report.json").write_bytes(report_bytes)
    report["report_sha256"] = hashlib.sha256(report_bytes).hexdigest()
    report["report_content_identity"] = digest(json.loads(report_bytes))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--published", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--resource-evidence", type=Path, required=True)
    parser.add_argument("--producer-source", type=Path, required=True)
    parser.add_argument("--source-audit", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-historical-tesseract",
        action="store_true",
        help="Permit source-bound historical TSV with explicitly unproven original binary/model digests",
    )
    args = parser.parse_args()
    report = import_observations(
        source=args.source,
        published=args.published,
        receipt_path=args.receipt,
        resource_evidence=args.resource_evidence,
        producer_source=args.producer_source,
        output=args.output,
        source_audit=args.source_audit,
        allow_historical_tesseract=args.allow_historical_tesseract,
    )
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in {"records", "proofs"}
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
