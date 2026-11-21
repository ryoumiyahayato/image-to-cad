"""Large diagnostic provenance remains recoverable without per-region copies."""

import copy
import json
from pathlib import Path
import shutil

import numpy as np
import pytest

from app.native_objects import text_line_domains as domains
from app.native_objects import text_regions as text


def scope_fixture():
    labels = np.zeros((30, 50), dtype=np.int32)
    labels[5:13, 5:14] = 1
    labels[:, 20] = 9
    domain = {
        "bbox_xyxy_px": [4, 4, 15, 14],
        "glyph_neighbor_separation": {"external_continuations": [{"label": 9}]},
    }
    words = [
        {"id": "inside", "text": "ABC", "bbox_xyxy_px": [5, 5, 14, 13]},
        *[
            {
                "id": f"outside-{i}",
                "text": "IABC",
                "bbox_xyxy_px": [5, 5, 21, 13],
                "observation_key": f"raw-pass-{i}",
                "observation_provenance": {
                    "source_identity": "synthetic-unchanged-source",
                    "receipt": "saved-original-evidence-" * 400,
                },
            }
            for i in range(30)
        ],
    ]
    return words, domain, labels, [0, 0, 50, 30]


def test_every_raw_word_and_scope_decision_survives_without_repeated_provenance(
    tmp_path,
):
    words, domain, labels, roi = scope_fixture()
    originals, original_labels = copy.deepcopy(words), labels.copy()
    stage = tmp_path / "evidence" / "text_domain_recovery"
    ledger = stage / "current_observations.json"
    text._dump(ledger, words)
    archive = domains.ScopeObservationEvidence(stage)
    archive.register(words, existing_path=ledger)
    old_kept, old_rejected = domains.scope_words_to_source_domain(
        words, domain, labels, roi
    )
    new_kept, compact = domains.scope_words_to_source_domain(
        words, domain, labels, roi, evidence=archive
    )
    assert new_kept == old_kept == [words[0]]
    assert len(compact) == len(old_rejected) == 30
    for old, new in zip(old_rejected, compact):
        reference = new["raw_word_reference"]
        restored = domains.read_scope_observation(stage.parent, reference)
        assert restored == old["raw_word"]
        assert reference["word_index_zero_based"] == words.index(restored)
        assert reference["sha256"] == text._sha(ledger)
        assert {
            k: v for k, v in new.items() if k not in {"raw_word", "raw_word_reference"}
        } == {k: v for k, v in old.items() if k != "raw_word"}
    assert len(json.dumps(compact)) < len(json.dumps(old_rejected)) / 5
    assert words == originals
    assert np.array_equal(labels, original_labels)
    # Another region / copied pass has the same immutable ledger, not another
    # full-page word list disguised as a new independent observation.
    archive.register(copy.deepcopy(words))
    assert list(stage.rglob("*.json")) == [ledger]


def test_scope_reference_survives_downstream_copy_and_task_relocation(tmp_path):
    words, domain, labels, roi = scope_fixture()
    first_root = tmp_path / "first" / "evidence"
    stage = first_root / "text_domain_recovery"
    archive = domains.ScopeObservationEvidence(stage)
    archive.register(words)
    _, rejected = domains.scope_words_to_source_domain(
        words, domain, labels, roi, evidence=archive
    )
    downstream = first_root / "source_text_completion" / "text_regions.json"
    text._dump(downstream, copy.deepcopy(rejected))
    relocated = tmp_path / "delivered" / "evidence"
    shutil.copytree(first_root, relocated)
    copied = json.loads(
        (relocated / "source_text_completion" / "text_regions.json").read_text()
    )
    reference = copied[0]["raw_word_reference"]
    assert domains.read_scope_observation(relocated, reference) == words[1]
    assert not Path(reference["path"]).is_absolute()
    with pytest.raises(ValueError, match="RAW_WORD_INDEX_INVALID"):
        domains.read_scope_observation(
            relocated, {**reference, "word_index_zero_based": -1}
        )
    with pytest.raises(ValueError, match="RAW_WORD_HASH_MISMATCH"):
        domains.read_scope_observation(
            relocated, {**reference, "word_sha256": "0" * 64}
        )
    ledger_path = relocated / reference["path"]
    raw = json.loads(ledger_path.read_text())
    raw[1]["text"] = "different raw observation"
    text._dump(ledger_path, raw)
    with pytest.raises(ValueError, match="LEDGER_HASH_MISMATCH"):
        domains.read_scope_observation(relocated, reference)


def test_scope_evidence_rejects_unsaved_or_different_raw_words(tmp_path):
    words, _, _, _ = scope_fixture()
    archive = domains.ScopeObservationEvidence(tmp_path / "stage")
    with pytest.raises(ValueError, match="NO_SAVED_LEDGER"):
        archive.reference(words[0])
    wrong = tmp_path / "stage" / "wrong.json"
    text._dump(wrong, words[1:])
    with pytest.raises(ValueError, match="LEDGER_CONTENT_MISMATCH"):
        archive.register(words, existing_path=wrong)
