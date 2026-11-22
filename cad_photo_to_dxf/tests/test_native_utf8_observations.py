"""Keep actual UTF-8 process/file observations intact on a cp1252 host.

The child below is an explicit transport fixture, not OCR or adopted geometry.
The packaged Windows smoke remains the actual two-engine end-to-end check.
"""

from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from app.native_objects import (
    cross_engine_text as cross,
    observation_cache as raw_cache,
    pipeline,
    source_text_completion as completion,
    text_line_domains as domains,
    text_regions as text,
)
from app.native_objects.contracts import save_json
from app.native_objects.execution import run_subprocess, use_context


WORD = "\u00a9\u2014\u201d\u4e2d"
HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
TSV = HEADER + "5\t1\t1\t1\t1\t1\t2\t3\t20\t10\t98\t" + WORD + "\n"


@pytest.fixture
def cp1252_host(monkeypatch):
    read, write = Path.read_text, Path.write_text

    def read_text(path, encoding=None, errors=None, **kwargs):
        return read(path, encoding=encoding or "cp1252", errors=errors, **kwargs)

    def write_text(path, data, encoding=None, errors=None, **kwargs):
        return write(path, data, encoding=encoding or "cp1252", errors=errors, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "write_text", write_text)
    monkeypatch.setattr(subprocess, "_text_encoding", lambda: "cp1252")
    monkeypatch.delenv(raw_cache.ENVIRONMENT_VARIABLE, raising=False)


def _transport_observation(tmp_path, monkeypatch, *, managed=False):
    calls = []
    engine = {"executable": sys.executable, "version": "tesseract transport-fixture"}
    monkeypatch.setattr(text, "_resolve_tesseract", lambda *args: engine)
    child = (
        "import sys;sys.stdout.buffer.write(bytes.fromhex("
        + repr(TSV.encode("utf-8").hex())
        + "));sys.stderr.buffer.write(bytes.fromhex("
        + repr(WORD.encode("utf-8").hex())
        + "))"
    )

    def execute(_command, **kwargs):
        calls.append(kwargs)
        return run_subprocess([sys.executable, "-c", child], **kwargs)

    monkeypatch.setattr(text, "run_subprocess", execute)
    image = np.full((30, 40), 255, np.uint8)
    image[3:13, 2:22] = 0
    output = tmp_path / "text/local_ocr"
    context = (
        use_context(cancel_file=tmp_path / "cancel", event_file=tmp_path / "events.jsonl", identity={"test": "UTF8 transport"})
        if managed else nullcontext()
    )
    with context:
        words, meta = text._ocr(image, [0, 0, 40, 30], 7, output, "unicode", None)
    return image, output, words, meta, calls


@pytest.mark.parametrize("managed", [False, True])
def test_actual_child_utf8_and_saved_checkpoint_survive_cp1252(tmp_path, monkeypatch, cp1252_host, managed):
    with pytest.raises(UnicodeDecodeError):
        TSV.encode("utf-8").decode("cp1252")
    image, output, words, meta, calls = _transport_observation(tmp_path, monkeypatch, managed=managed)
    assert words[0]["text"] == WORD
    assert meta["recognition_output_encoding"] == calls[0]["encoding"] == "utf-8"
    raw = output / "unicode.tsv"
    assert raw.read_text(encoding="utf-8") == TSV
    assert (output / "unicode.stderr.txt").read_text(encoding="utf-8") == WORD
    before = {path: path.read_bytes() for path in output.iterdir()}
    replay, receipt = text._ocr(image, [0, 0, 40, 30], 7, output, "unicode", None)
    assert replay[0]["text"] == WORD and len(calls) == 1
    assert receipt["command_executed_for_this_request"] is False
    assert receipt["recognition_output_encoding"] == "utf-8"
    assert all(path.read_bytes() == data for path, data in before.items())


def test_current_raw_consumers_preserve_nonascii_text_without_recognition(tmp_path, monkeypatch, cp1252_host):
    image, output, words, _, calls = _transport_observation(tmp_path, monkeypatch)
    upstream = output.parent / "text_regions.json"
    region = {"id": "transport-case", "bbox_xyxy_px": [2, 3, 22, 13], "completeness_evidence": {"alternatives": [{"raw_tsv": "local_ocr/unicode.tsv", "context_id": "unicode"}]}}
    data = {"roi_xyxy_px": [0, 0, 40, 30], "regions": [region]}
    save_json(upstream, data)
    save_json(output.parent / "discovery_observations.json", [{**words[0], "id": "unicode-seed"}])
    collected, record = domains._collect_current_observations(image, data, None, {"source_sha256": "a" * 64, "text_path": str(upstream)}, tmp_path / "domains")
    assert [word["text"] for word in collected] == [WORD]
    assert record["actual_independent_passes"] == 1
    alternatives = cross._read_tesseract_evidence(region, data, upstream, tmp_path / "cross", image)
    assert alternatives[0]["raw_text"] == WORD
    observations = completion.BoundObservations(image, tmp_path / "completion", "a" * 64, 200)
    key = observations.ingest(output / "unicode.tsv")
    assert observations.rows[key]["words"][0]["text"] == WORD
    assert len(calls) == 1
    path = tmp_path / "completion/unicode.json"
    completion._atomic(path, {"text": WORD})
    assert completion._read(path) == {"text": WORD}
    assert WORD.encode("utf-8") in path.read_bytes()


def test_pipeline_discovery_and_verified_cache_use_utf8_on_cp1252(tmp_path, cp1252_host):
    cache, output = tmp_path / "cache", tmp_path / "next"
    cache.mkdir()
    output.mkdir()
    image = np.full((30, 40), 255, np.uint8)
    words = [{"text": WORD, "confidence": 98, "bbox_xyxy_px": [2, 3, 22, 13], "context_id": "unicode", "psm": 11}]
    payload = cache / "observations.json"
    save_json(payload, words)
    sha = hashlib.sha256(payload.read_bytes()).hexdigest()
    save_json(cache / "completed_stages.json", {"discovery": {"path": "observations.json", "sha256": sha}})
    save_json(cache / "manifest.json", {"source_array_sha256": text.source_array_sha256(image), "source_size_px": [40, 30], "roi_xyxy_px": [0, 0, 40, 30], "coordinate_system": "source_pixels_top_left", "observations_file": "observations.json", "observations_sha256": sha})
    restored = pipeline._discovery_for_resume(cache, output, {})
    assert json.loads(restored.read_text(encoding="utf-8")) == words
    result, receipt = text._cached_observations(cache, image, [0, 0, 40, 30])
    assert result[0]["text"] == WORD and receipt["enabled"]
    assert hashlib.sha256(payload.read_bytes()).hexdigest() == sha


@pytest.mark.parametrize("windows,nonascii,known_utf8,rejected", [(True, True, False, True), (True, False, False, False), (False, True, False, False), (True, True, True, False)])
def test_legacy_encoding_receipt_does_not_rewrite_or_reject_valid_ascii_linux(tmp_path, monkeypatch, cp1252_host, windows, nonascii, known_utf8, rejected):
    image, output, _, _, calls = _transport_observation(tmp_path, monkeypatch)
    raw, meta_path = output / "unicode.tsv", output / "unicode.json"
    if not nonascii:
        raw.write_text(TSV.replace(WORD, "ASCII"), encoding="utf-8")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["command"][0] = "C:\\old\\tesseract.exe" if windows else "/usr/bin/tesseract"
    if not known_utf8:
        meta.pop("recognition_output_encoding")
    meta["tsv_sha256"] = hashlib.sha256(raw.read_bytes()).hexdigest()
    save_json(meta_path, meta)
    before = {path: path.read_bytes() for path in output.iterdir()}
    if rejected:
        with pytest.raises(ValueError, match="LEGACY_WINDOWS_NONASCII_OCR_ENCODING_UNVERIFIED"):
            text._ocr(image, [0, 0, 40, 30], 7, output, "unicode", None)
    else:
        words, receipt = text._ocr(image, [0, 0, 40, 30], 7, output, "unicode", None)
        assert words[0]["text"] == (WORD if nonascii else "ASCII")
        assert receipt["command_executed_for_this_request"] is False
    assert len(calls) == 1
    assert all(path.read_bytes() == data for path, data in before.items())


def test_raw_cache_rejects_unverified_windows_nonascii_without_extra_ocr_or_rewriting(tmp_path, monkeypatch, cp1252_host):
    cache = raw_cache.ObservationCache(tmp_path / "cache", create=True)
    monkeypatch.setenv(raw_cache.ENVIRONMENT_VARIABLE, str(cache.root))
    executable = tmp_path / "tesseract.exe"
    executable.write_bytes(b"unexecuted transport fixture")
    (tmp_path / "eng.traineddata").write_bytes(b"test language identity")
    engine = {"executable": str(executable), "version": "tesseract transport-fixture", "list_langs_output": f'List of available languages in "{tmp_path}" (1):\neng\n'}
    monkeypatch.setattr(text, "_resolve_tesseract", lambda *args: engine)
    monkeypatch.setattr(text, "run_subprocess", lambda *a, **kw: pytest.fail("rejected cache triggered new OCR"))
    image = np.full((30, 40), 255, np.uint8)
    identity = raw_cache.tesseract_identity(engine)
    specification = raw_cache.tesseract_spec(image, image, padding=0, psm=7, dpi=200, engine=identity)
    cache.put(specification, TSV.encode("utf-8"), raw_cache.producer_identity(text.__file__, engine=identity, metadata={"command": ["C:\\old\\tesseract.exe"]}))
    before = {path: path.read_bytes() for path in cache.root.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="LEGACY_WINDOWS_NONASCII_OCR_ENCODING_UNVERIFIED"):
        text._ocr(image, [0, 0, 40, 30], 7, tmp_path / "next", "unicode", None)
    assert all(path.read_bytes() == data for path, data in before.items())
