"""A changed local routing policy cannot inherit an old proposal cache."""

import hashlib
from pathlib import Path

import pytest

from app.native_objects import connection_core_routes
from app.native_objects.completion_stages import _check_completion_dependencies


def _attested_payload():
    return {
        "discovery": {
            "dependency_producers": {
                connection_core_routes.__name__: hashlib.sha256(
                    Path(connection_core_routes.__file__).read_bytes()
                ).hexdigest()
            }
        }
    }


def test_unchanged_local_route_policy_can_reuse_its_source_proposal():
    _check_completion_dependencies("connections", _attested_payload())


def test_changed_helper_rejects_old_attestation(tmp_path, monkeypatch):
    payload = _attested_payload()
    changed = tmp_path / "changed_route_policy.py"
    changed.write_text("# A different route implementation\n")
    monkeypatch.setattr(connection_core_routes, "__file__", str(changed))
    with pytest.raises(ValueError, match="ROUTE_DEPENDENCY_CHANGED_OR_MISSING"):
        _check_completion_dependencies("connections", payload)


@pytest.mark.parametrize(
    "payload", [{}, {"discovery": {}}, {"discovery": {"dependency_producers": {}}}]
)
def test_unattested_historical_proposal_fails_closed(payload):
    with pytest.raises(ValueError, match="ROUTE_DEPENDENCY_CHANGED_OR_MISSING"):
        _check_completion_dependencies("connections", payload)


def test_extra_unrecognized_dependency_is_not_silently_ignored():
    payload = _attested_payload()
    payload["discovery"]["dependency_producers"]["app.native_objects.unknown"] = (
        "0" * 64
    )
    with pytest.raises(ValueError, match="ROUTE_DEPENDENCY_CHANGED_OR_MISSING"):
        _check_completion_dependencies("connections", payload)


def test_door_payload_does_not_claim_the_unrelated_connection_policy():
    _check_completion_dependencies("doors", {"raw_generation": {}})


def test_derived_text_revision_binds_confirmation_and_context_policies():
    from app.native_objects import source_text_completion as completion
    from app.native_objects import revision_resume as resume

    names = [*resume._PRODUCERS, *resume._DERIVED_PRODUCERS]
    producers = {
        "app.native_objects." + name: hashlib.sha256(
            Path(resume.__file__).with_name(name + ".py").read_bytes()
        ).hexdigest()
        for name in names
    }
    for dependency in (completion.confirmation_module, completion.context_ownership):
        assert dependency.__name__ in producers
    resume._producer_checks(producers)
    producers[completion.confirmation_module.__name__] = "0" * 64
    with pytest.raises(ValueError):
        resume._producer_checks(producers)
