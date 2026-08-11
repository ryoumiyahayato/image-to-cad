"""Explicit contract dispatch for editable-text validation.

V1 remains the historical validator and intentionally rejects V2.  Callers
that want V2 must name it explicitly; this dispatcher is the only supported
cross-version selection boundary.
"""

from __future__ import annotations

from typing import Any

try:
    from . import editable_text_regression_contract as v1
    from . import editable_text_v2_contract as v2
except ImportError:  # Direct script/module use from ``cad_photo_to_dxf/scripts``.
    import editable_text_regression_contract as v1
    import editable_text_v2_contract as v2


PHASE12_CONTRACT = v1.PHASE12_CONTRACT
V1_CONTRACT = v1.EDITABLE_TEXT_CONTRACT
V2_CONTRACT = v2.V2_CONTRACT


def dispatch_contract(contract: str | None) -> tuple[str, Any]:
    """Resolve a named contract to its owning validator module.

    No default is allowed.  In particular, passing V2 to the historical V1
    ``require_explicit_contract`` remains an error, preserving the V1 replay
    contract while making the V2 choice explicit at the caller boundary.
    """

    value = (contract or "").strip()
    if not value:
        raise ValueError(
            "A contract version is required; pass --contract "
            f"{V1_CONTRACT} or {V2_CONTRACT}."
        )
    if value == PHASE12_CONTRACT:
        return "phase12", v1
    if value == V1_CONTRACT:
        return "v1", v1
    if value == V2_CONTRACT:
        return "v2", v2
    raise ValueError(f"Unknown editable-text contract: {value}")


__all__ = [
    "PHASE12_CONTRACT",
    "V1_CONTRACT",
    "V2_CONTRACT",
    "dispatch_contract",
]
