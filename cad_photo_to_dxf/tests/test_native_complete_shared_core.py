"""Ordinary completion enforces the same current whole-path ownership gate."""

from copy import deepcopy
import hashlib
from itertools import combinations
import math

import numpy as np
import pytest

from app.native_objects import connections
from app.native_objects.completion_stages import (
    _source_edges,
    complete_connections_without_unresolved_retirement,
)
from tests.test_native_text_graph_support import crossing_fixture


def _complete(item, directory, prior=None):
    gray, roi, texts, verified, formal, _ = item
    before_pixels, before_texts = gray.copy(), deepcopy(texts)
    before_prior = deepcopy(formal if prior is None else prior)
    result = complete_connections_without_unresolved_retirement(
        gray, roi, hashlib.sha256(gray.tobytes()).hexdigest(),
        formal if prior is None else prior, directory, text_regions=texts,
        verified_text_observations=verified,
    )
    assert np.array_equal(gray, before_pixels)
    assert texts == before_texts
    assert (formal if prior is None else prior) == before_prior
    assert result["all_existing_native_entities_retained"]
    return result


def test_ordinary_completion_keeps_all_three_real_paths_and_both_short_strokes(tmp_path):
    result = _complete(crossing_fixture(stroke_width=2), tmp_path / "connections")
    assert len(result["objects"]) == 3
    assert sum(o["source_evidence"]["source_path_length_px"] < 50 for o in result["objects"]) == 2
    checks = [proof for row in result["decisions"] for proof in row["shared_source_core_checks"]]
    assert len(checks) == 2 and all(proof["pass"] for proof in checks)
    assert all(not proof["native_duplicates_authorized"] for proof in checks)
    assert all(not row["reasons"] and row["adopted"] for row in result["decisions"])


@pytest.mark.parametrize("damage", ["missing-source-core-proof", "native-long-overlap"])
def test_ordinary_completion_rejects_unproved_sharing_or_native_overlap_after_real_extraction(tmp_path, monkeypatch, damage):
    original = connections.extract_connections
    damaged = []

    def changed_observation(*args, **kwargs):
        raw = original(*args, **kwargs)
        assert len(raw["objects"]) == 3
        old, candidate = next((a, b) for a, b in combinations(raw["objects"], 2)
                              if _source_edges(a) & _source_edges(b))
        damaged.append(candidate["id"])
        if damage == "missing-source-core-proof":
            for crossing in candidate["source_evidence"]["crossing_evidence"]:
                crossing.pop("bounded_shared_source_core", None)
                crossing.pop("bounded_aggregate_source_core", None)
        else:
            a, b = np.asarray(old["geometry"]["points"][:2], float)
            steps = math.ceil(float(np.linalg.norm(b - a)) / 0.25)
            inset = (b - a) / (2 * steps)
            candidate["geometry"]["points"].extend([(a + inset).tolist(), (b - inset).tolist()])
            candidate["geometry"]["bulges"].extend([0.0, 0.0])
        return raw

    monkeypatch.setattr(connections, "extract_connections", changed_observation)
    result = _complete(crossing_fixture(stroke_width=2), tmp_path / "connections")
    assert damaged[0] not in {row["id"] for row in result["objects"]}
    row = next(row for row in result["decisions"] if row["id"] == damaged[0])
    assert row["adopted"] is False
    assert "ANOTHER_WHOLE_PATH_OWNS_OBSERVED_SOURCE_ADJACENCIES" in row["reasons"]
    assert any(not proof["pass"] for proof in row["shared_source_core_checks"])


def test_ordinary_completion_does_not_add_an_existing_or_twice_emitted_whole_path(tmp_path, monkeypatch):
    original = connections.extract_connections

    def duplicate_discovery(*args, **kwargs):
        raw = original(*args, **kwargs)
        raw["objects"].append(deepcopy(raw["objects"][0]))
        return raw

    item = crossing_fixture(stroke_width=2)
    first = _complete(item, tmp_path / "first")
    monkeypatch.setattr(connections, "extract_connections", duplicate_discovery)
    result = _complete(item, tmp_path / "again", [*item[4], *first["objects"]])
    assert result["objects"] == []
    assert all(row["existing_adequate_ids"] for row in result["decisions"])
    assert all("EXISTING_COMPLETE_PATH_ALREADY_PRESENT_NO_DUPLICATE" in row["reasons"]
               for row in result["decisions"])
