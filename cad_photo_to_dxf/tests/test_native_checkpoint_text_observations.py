"""A captured raw observation must still prove its actual source and bytes."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image
import pytest

from app.native_objects import checkpoint_text_observations as raw
from app.native_objects.execution import file_sha


HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
TSV = HEADER + "5\t1\t1\t1\t1\t1\t3\t2\t7\t6\t48.5\tAB\n"


def _write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def _fixture(tmp_path):
    root = tmp_path / "original"
    root.mkdir()
    image = np.full((30, 40), 255, dtype=np.uint8)
    image[3:9, 5:12] = 0
    source = tmp_path / "source.png"
    Image.fromarray(image).save(source)
    box = [2, 1, 24, 16]
    crop = image[box[1]:box[3], box[0]:box[2]]
    assets = root / "assets"
    assets.mkdir()
    tsv, meta, png = (assets / ("sample" + extension) for extension in (".tsv", ".json", ".png"))
    tsv.write_text(TSV)
    Image.fromarray(crop).save(png)
    metadata = {
        "status": "COMPLETED", "return_code": 0,
        "specification": {
            "crop_xyxy_px": box, "crop_array_sha256": hashlib.sha256(crop.tobytes()).hexdigest(),
            "psm": 7, "pixel_scale": [1, 1], "source_pixels_modified": False,
            "language": "eng", "recognition_dpi": 200, "external_white_padding_px": 0,
            "padding_replaces_source_pixels": False,
        },
        "tsv_sha256": file_sha(tsv), "image_sha256": file_sha(png),
        "engine_version": "tesseract historical-test",
        "command": ["/author/no-longer-exists/tesseract", "/author/old/crop.png", "stdout",
                    "--psm", "7", "--dpi", "200", "-l", "eng", "--oem", "1", "tsv"],
    }
    _write(meta, metadata)
    parameters = {"roi": [0, 0, 40, 30], "dpi": 200, "orientation": 0}
    manifest = {
        "schema": raw.SCHEMA, "source_sha256": file_sha(source),
        "source_array_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        "roi_xyxy_px": parameters["roi"], "dpi": 200,
        "observations": [{"region_id": "arbitrary-label", **{
            kind: {"path": path.relative_to(root).as_posix(), "sha256": file_sha(path)}
            for kind, path in (("tsv", tsv), ("meta", meta), ("png", png))
        }}],
    }
    path = root / "request.json"
    _write(path, manifest)
    return dict(root=root, image=image, source=source, tsv=tsv, meta=meta, png=png,
                parameters=parameters, manifest=manifest, path=path)


def _asset(fixture):
    return {"path": str(fixture["path"]), "sha256": file_sha(fixture["path"])}


def _verify(fixture, **kwargs):
    return raw.verify_source_observations(_asset(fixture), fixture["source"],
                                         file_sha(fixture["source"]), fixture["parameters"], **kwargs)


def _refresh(fixture):
    for key in ("tsv", "meta", "png"):
        fixture["manifest"]["observations"][0][key]["sha256"] = file_sha(fixture[key])
    _write(fixture["path"], fixture["manifest"])


def test_actual_capture_survives_old_directory_removal_without_ocr(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Cold verification must never request recognition")

    monkeypatch.setattr(raw.BoundObservations, "request", forbidden)
    monkeypatch.setattr(raw.BoundObservations, "scan", forbidden)
    original_sha = file_sha(fixture["path"])
    capture = tmp_path / "job/inputs/source_observations"
    asset = raw.capture_source_observations(fixture["path"], capture, fixture["source"],
                                           file_sha(fixture["source"]), fixture["parameters"])
    assert asset["sha256"] == original_sha
    shutil.rmtree(fixture["root"])
    before = {str(path): file_sha(path) for path in capture.rglob("*") if path.is_file()}
    result = raw.verify_source_observations(asset, fixture["source"], file_sha(fixture["source"]),
                                            fixture["parameters"], gray=fixture["image"])
    assert result["validated"] and result["new_OCR_calls"] == 0
    observation = result["observations"][0]
    assert [(word["text"], word["confidence"], word["bbox_xyxy_px"]) for word in observation["words"]] == [("AB", 48.5, [5, 3, 12, 9])]
    assert observation["provenance"]["historical_model_byte_identity_proven"] is False
    assert observation["provenance"]["command_executed_for_this_request"] is False
    assert all(capture in Path(item["path"]).parents for item in observation["files"].values())
    assert before == {str(path): file_sha(path) for path in capture.rglob("*") if path.is_file()}


def test_alias_of_same_source_is_not_an_extra_observation(tmp_path):
    fixture = _fixture(tmp_path)
    fixture["manifest"]["observations"].append(deepcopy(fixture["manifest"]["observations"][0]))
    _write(fixture["path"], fixture["manifest"])
    result = _verify(fixture)
    assert len(result["observations"]) == len(result["aliases"]) == 1
    assert result["aliases"][0]["extra_vote"] is False


@pytest.mark.parametrize("key", ["tsv", "meta", "png"])
def test_changed_captured_asset_fails_closed(tmp_path, key):
    fixture = _fixture(tmp_path)
    asset = raw.capture_source_observations(fixture["path"], tmp_path / "captured", fixture["source"],
                                           file_sha(fixture["source"]), fixture["parameters"])
    captured = Path(asset["path"]).parent / fixture["manifest"]["observations"][0][key]["path"]
    captured.write_bytes(captured.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="ASSET_HASH_MISMATCH"):
        raw.verify_source_observations(asset, fixture["source"], file_sha(fixture["source"]), fixture["parameters"])


@pytest.mark.parametrize("name", ["../outside.tsv", "/tmp/outside.tsv", "assets\\sample.tsv", "C:/outside.tsv"])
def test_noncontained_or_nonportable_asset_paths_fail(tmp_path, name):
    fixture = _fixture(tmp_path)
    fixture["manifest"]["observations"][0]["tsv"]["path"] = name
    _write(fixture["path"], fixture["manifest"])
    with pytest.raises(ValueError, match="PATH_NOT_CONTAINED_POSIX"):
        _verify(fixture)


def test_symlink_cannot_escape_the_observation_root(tmp_path):
    fixture = _fixture(tmp_path)
    external = tmp_path / "outside.tsv"
    external.write_bytes(fixture["tsv"].read_bytes())
    fixture["tsv"].unlink()
    fixture["tsv"].symlink_to(external)
    with pytest.raises(ValueError, match="PATH_ESCAPES_MANIFEST"):
        _verify(fixture)


def test_rehashed_recognition_png_still_must_equal_original_source(tmp_path):
    fixture = _fixture(tmp_path)
    with Image.open(fixture["png"]) as opened:
        pixels = np.array(opened)
    pixels[0, 0] = 0
    Image.fromarray(pixels).save(fixture["png"])
    metadata = json.loads(fixture["meta"].read_text())
    metadata["image_sha256"] = file_sha(fixture["png"])
    _write(fixture["meta"], metadata)
    _refresh(fixture)
    with pytest.raises(ValueError, match="RECOGNITION_PNG_NOT_ORIGINAL_CROP"):
        _verify(fixture)


def test_supplied_prepared_pixels_are_rechecked(tmp_path):
    fixture = _fixture(tmp_path)
    changed = fixture["image"].copy()
    changed[0, 0] = 0
    with pytest.raises(ValueError, match="SOURCE_ARRAY_HASH_MISMATCH"):
        _verify(fixture, gray=changed)


@pytest.mark.parametrize("change,reason", [
    ("pixel_scale", "RAW_CONFIGURATION_NOT_FROZEN"),
    ("crop_hash", "RAW_SOURCE_PIXELS_MISMATCH"),
    ("cropped_outside_roi", "RAW_CROP_OUTSIDE_TASK_ROI"),
    ("missing_command_value", "ENGINE_COMMAND_CONFIG_MISMATCH"),
    ("forged_validated", "MANIFEST_FIELDS_INVALID"),
])
def test_changed_configuration_cannot_authorize_old_observations(tmp_path, change, reason):
    fixture = _fixture(tmp_path)
    metadata = json.loads(fixture["meta"].read_text())
    if change == "pixel_scale":
        metadata["specification"]["pixel_scale"] = [2, 2]
    elif change == "crop_hash":
        metadata["specification"]["crop_array_sha256"] = "a" * 64
    elif change == "cropped_outside_roi":
        metadata["specification"]["crop_xyxy_px"] = [2, 1, 41, 16]
    elif change == "missing_command_value":
        metadata["command"] = ["tesseract", "--psm"]
    else:
        fixture["manifest"]["validated"] = True
    _write(fixture["meta"], metadata)
    _refresh(fixture)
    with pytest.raises(ValueError, match=reason):
        _verify(fixture)


@pytest.mark.parametrize("tsv", ["not-tsv", TSV.replace("\t7\t6\t", "\t70\t6\t"), TSV.replace("48.5", "nan")])
def test_malformed_raw_words_cannot_silently_disappear(tmp_path, tsv):
    fixture = _fixture(tmp_path)
    fixture["tsv"].write_text(tsv)
    metadata = json.loads(fixture["meta"].read_text())
    metadata["tsv_sha256"] = file_sha(fixture["tsv"])
    _write(fixture["meta"], metadata)
    _refresh(fixture)
    with pytest.raises(ValueError, match="TSV_"):
        _verify(fixture)


def test_capture_never_overwrites_an_existing_checkpoint(tmp_path):
    fixture = _fixture(tmp_path)
    directory = tmp_path / "captured"
    directory.mkdir()
    marker = directory / "already-valid"
    marker.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        raw.capture_source_observations(fixture["path"], directory, fixture["source"],
                                        file_sha(fixture["source"]), fixture["parameters"])
    assert marker.read_bytes() == b"keep"


def _current_job(tmp_path, *, count=1, derived=False):
    fixture = _fixture(tmp_path)
    root = tmp_path / "job/evidence"
    originals = root / "text/local_ocr"
    originals.mkdir(parents=True)
    for key in ("tsv", "meta", "png"):
        shutil.copyfile(fixture[key], originals / fixture[key].name)
    texts = {"source_array_sha256": fixture["manifest"]["source_array_sha256"],
             "source_size_px": [40, 30], "roi_xyxy_px": fixture["parameters"]["roi"],
             "regions": [{"id": "row-" + str(index), "completeness_evidence": {
                 "alternatives": [{"raw_tsv": "local_ocr/sample.tsv", "status": "COMPLETED"}]
             }} for index in range(count)]}
    path = root / "completed_text.json"
    if derived:
        path = root / "derived/completed_text.json"
        path.parent.mkdir()
        texts["region_evidence_roots"] = {row["id"]: "../text" for row in texts["regions"]}
    _write(path, texts)
    return fixture, root, path, texts


def _current_verify(fixture, root, path, texts):
    return raw.verify_current_job_observations(
        texts, root, fixture["source"], file_sha(fixture["source"]), fixture["parameters"],
        text_artifact_path=path, gray=fixture["image"],
    )


@pytest.mark.parametrize("derived", [False, True])
def test_ordinary_job_uses_only_its_declared_actual_raw_files(tmp_path, monkeypatch, derived):
    fixture, root, path, texts = _current_job(tmp_path, derived=derived)

    def forbidden(*args, **kwargs):
        pytest.fail("The adapter must not scan a previous directory or request OCR")

    monkeypatch.setattr(raw.BoundObservations, "scan", forbidden)
    monkeypatch.setattr(raw.BoundObservations, "request", forbidden)
    before = {str(p): file_sha(p) for p in root.rglob("*") if p.is_file()}
    shutil.rmtree(fixture["root"])
    result = _current_verify(fixture, root, path, texts)
    assert result["validated"] and len(result["observations"]) == 1
    assert result["observations"][0]["words"][0]["text"] == "AB"
    assert result["new_OCR_calls"] == 0
    assert all(file_sha(p) == digest for p, digest in before.items())
    assert Path(result["manifests"][0]["path"]).parent == root


@pytest.mark.parametrize("texts,reason", [
    (None, "NO_CURRENT_TEXT_REGIONS"),
    ({"regions": []}, "NO_CURRENT_TEXT_REGIONS"),
    ({"regions": [{"id": "without-observations"}]}, "NO_DECLARED_RAW_OBSERVATIONS"),
])
def test_empty_or_synthetic_text_inputs_remain_conservative(tmp_path, texts, reason):
    result = raw.verify_current_job_observations(
        texts, tmp_path / "not-created", tmp_path / "not-read.png", "a" * 64,
        {"roi": [0, 0, 40, 30], "dpi": 200, "orientation": 0},
        text_artifact_path=tmp_path / "not-read.json",
    )
    assert result["validated"] is False and result["observations"] == []
    assert result["reason"] == reason and result["new_OCR_calls"] == 0


def test_current_job_batches_more_than_64_references_without_extra_votes(tmp_path):
    fixture, root, path, texts = _current_job(tmp_path, count=65)
    result = _current_verify(fixture, root, path, texts)
    assert len(result["manifests"]) == 2 and len(result["observations"]) == 65
    assert len({row["key"] for row in result["observations"]}) == 1
    for asset in result["manifests"]:
        manifest = json.loads(Path(asset["path"]).read_text())
        assert len(manifest["observations"]) <= 64


@pytest.mark.parametrize("name,reason", [
    ("local_ocr/missing.tsv", "CURRENT_DECLARED_RAW_MISSING_OR_ESCAPED"),
    ("../../../author/old.tsv", "CURRENT_REFERENCE_OUTSIDE_JOB"),
    ("/author/old.tsv", "CURRENT_REFERENCE_NOT_RELATIVE_POSIX"),
])
def test_declared_missing_or_old_absolute_raw_paths_are_rejected(tmp_path, name, reason):
    fixture, root, path, texts = _current_job(tmp_path)
    texts["regions"][0]["completeness_evidence"]["alternatives"][0]["raw_tsv"] = name
    _write(path, texts)
    with pytest.raises(ValueError, match=reason):
        _current_verify(fixture, root, path, texts)


def test_current_job_corrupt_raw_is_not_treated_as_absent_evidence(tmp_path):
    fixture, root, path, texts = _current_job(tmp_path)
    (root / "text/local_ocr/sample.tsv").write_text(TSV.replace("AB", "BA"))
    with pytest.raises(ValueError, match="CURRENT_RAW_METADATA_PAYLOAD_HASH_MISMATCH"):
        _current_verify(fixture, root, path, texts)


def test_current_text_memory_must_match_the_saved_stage(tmp_path):
    fixture, root, path, texts = _current_job(tmp_path)
    texts["regions"][0]["text"] = "unbound change"
    with pytest.raises(ValueError, match="CURRENT_TEXT_ARTIFACT_CONTENT_MISMATCH"):
        _current_verify(fixture, root, path, texts)


def test_fresh_source_contact_evidence_survives_json_then_detects_real_drift(tmp_path):
    from app.native_objects.text_regions import _source_label_contacts

    fixture, root, path, texts = _current_job(tmp_path)
    labels = np.zeros(fixture["image"].shape, dtype=np.int32)
    labels[fixture["image"] == 0] = 1
    contacts = _source_label_contacts(
        labels, fixture["parameters"]["roi"], [5, 3, 12, 9], {1}
    )
    assert contacts and {row["edge"] for row in contacts} == {
        "left", "right", "top", "bottom"
    }
    texts["regions"][0]["completeness_evidence"]["current_boundary_assessment"] = {
        "actual_source_component_contacts_effective_input": contacts,
    }
    _write(path, texts)
    assert texts == json.loads(path.read_text())
    verified = _current_verify(fixture, root, path, texts)
    assert verified["validated"] and verified["new_OCR_calls"] == 0

    # No late cold-read or permissive comparison may hide a changed live count.
    contacts[0]["component_pixel_counts"][0][1] += 1
    with pytest.raises(ValueError, match="CURRENT_TEXT_ARTIFACT_CONTENT_MISMATCH"):
        _current_verify(fixture, root, path, texts)
