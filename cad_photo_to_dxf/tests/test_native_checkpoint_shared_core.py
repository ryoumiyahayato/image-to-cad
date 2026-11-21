"""Current four-port source support is shareable; native long lines are not."""

from copy import deepcopy
from itertools import combinations
import math

import numpy as np
import pytest

from app.native_objects.connection_checkpoint import _source_edges, adopt_checkpoint_paths
from app.native_objects.text_graph_support import prove_shared_core_overlap
from tests.test_native_text_graph_support import crossing_fixture, extract


@pytest.fixture
def crossing(tmp_path):
    item = crossing_fixture(stroke_width=2)
    found = extract(item, tmp_path / "discovery")
    assert len(found["objects"]) == 3
    return item, found["objects"]


def _shared_pair(objects):
    first, second = next((a, b) for a, b in combinations(objects, 2)
                         if _source_edges(a) & _source_edges(b))
    return deepcopy(first), deepcopy(second)


def test_current_four_port_core_keeps_three_complete_independent_paths(crossing):
    item, objects = crossing
    before = deepcopy(objects)
    source = item[0].copy()
    result = adopt_checkpoint_paths(item[0], objects, item[4])
    assert len(result["objects"]) == 3
    assert result["retired_ids"] == []
    assert result["uncertainties"] == []
    shared = [proof for row in result["decisions"] for proof in row["shared_source_core_checks"]]
    assert len(shared) == 2 and all(proof["pass"] for proof in shared)
    assert all(proof["native_duplicates_authorized"] is False for proof in shared)
    assert all(proof["source_recomputed"] for row in shared for proof in row["current_core_proofs"])
    lengths = [row["source_evidence"]["source_path_length_px"] for row in result["objects"]]
    assert sum(length < 50 for length in lengths) == 2  # Both real short crossing strokes survive.
    assert objects == before
    assert np.array_equal(item[0], source)


@pytest.mark.parametrize("damage", ["missing-core", "source-changed", "outside-core-source", "native-long-overlap"])
def test_shared_source_requires_current_bounded_core_without_duplicate_native_length(crossing, damage):
    item, objects = crossing
    old, candidate = _shared_pair(objects)
    gray = item[0].copy()
    if damage == "missing-core":
        for row in candidate["source_evidence"]["crossing_evidence"]:
            row.pop("bounded_shared_source_core", None)
            row.pop("bounded_aggregate_source_core", None)
    elif damage == "source-changed":
        gray[10, 10] = 0
    elif damage == "outside-core-source":
        candidate["source_evidence"]["source_path_points"].extend(
            deepcopy(old["source_evidence"]["source_path_points"][:2]))
    else:
        # Exact finite overlap with half a sampling-step phase shift. Point to
        # point sampling alone misses this coincident long native segment.
        a, b = np.asarray(old["geometry"]["points"][:2], float)
        steps = math.ceil(float(np.linalg.norm(b - a)) / 0.25)
        inset = (b - a) / (2 * steps)
        candidate["geometry"]["points"].extend([(a + inset).tolist(), (b - inset).tolist()])
        candidate["geometry"]["bulges"].extend([0.0, 0.0])
    current = prove_shared_core_overlap(gray, candidate, old)
    assert current["pass"] is False
    if damage == "native-long-overlap":
        assert current["reason"] == "NATIVE_OVERLAP_EXTENDS_OUTSIDE_PROVEN_SOURCE_CORE"
    original = deepcopy([old, candidate])
    result = adopt_checkpoint_paths(gray, [candidate], [old])
    assert result["objects"] == [] and result["retired_ids"] == []
    assert result["uncertainties"]
    assert "ANOTHER_WHOLE_PATH_OWNS_OBSERVED_SOURCE_ADJACENCIES" in result["decisions"][0]["reasons"]
    assert [old, candidate] == original


def test_repeated_discovery_of_existing_complete_paths_does_not_duplicate_them(crossing):
    item, objects = crossing
    result = adopt_checkpoint_paths(item[0], objects, [*item[4], *deepcopy(objects)])
    assert result["objects"] == result["retired_ids"] == result["uncertainties"] == []
    assert all(row["decision"] == "RETAIN_EXISTING_COMPLETE_PATH_NO_DUPLICATE" for row in result["decisions"])
