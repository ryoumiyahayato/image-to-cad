"""A same-source replacement must be clean in the saved DXF itself."""

from copy import deepcopy
import hashlib

import ezdxf
import pytest

from app.native_objects.cad_io import export_objects
from app.native_objects.carrier_reconciliation import plan_existing_carrier_reconciliation
from app.native_objects.carrier_reconciliation_audit import cold_carrier_reconciliation
from app.native_objects.contracts import save_json
from tests.test_native_carrier_reconciliation import ROI, _source, _line


def _saved(tmp_path):
    gray, prior = _source()
    prior += [_line("independent-right-return", [330, 90], [330, 150])]
    plan = plan_existing_carrier_reconciliation(gray, ROI, prior, receiving_object_ids=[prior[0]["id"]])
    assert len(plan["objects"]) == 1
    retained = [obj for obj in prior if obj["id"] not in plan["retired_ids"]]
    saved = tmp_path / "result.dxf"
    active = retained + plan["objects"]
    sha = hashlib.sha256(gray.tobytes()).hexdigest()
    export_objects(active, saved, ROI, 200, sha)
    save_json(tmp_path / "evidence/carrier_reconciliation/adoption.json", plan)
    return gray, saved, prior, active, sha


def test_cold_saved_carrier_has_one_whole_expression_and_exact_finite_return(tmp_path):
    gray, saved, _, _, _ = _saved(tmp_path)
    report = cold_carrier_reconciliation(saved, ezdxf.readfile(saved), gray, ROI, 200, tmp_path / "evidence")
    assert report["pass"], report
    actual = [row for row in report["checks"] if row["type"] == "SAVED_RECONCILED_CARRIER_LINE"][0]
    assert actual["checks"]["actual_endpoint_1_contacts_finite_return:independent-right-return"]
    assert len(report["retired_ids"]) == 2


@pytest.mark.parametrize("change", ["retained_duplicate", "renamed_duplicate", "different_near_duplicate",
                                    "shortened_carrier", "moved_return"])
def test_cold_saved_carrier_rejects_actual_residue_or_stale_finite_binding(tmp_path, change):
    gray, saved, prior, active, sha = _saved(tmp_path)
    changed = deepcopy(active)
    if change in {"retained_duplicate", "renamed_duplicate", "different_near_duplicate"}:
        duplicate = deepcopy(prior[0])
        if change != "retained_duplicate":
            duplicate["id"] = "different-identity-old-source-expression"
        if change == "different_near_duplicate":
            duplicate["geometry"]["start"][1] += 0.2
            duplicate["geometry"]["end"][1] += 0.2
        changed.append(duplicate)
    elif change == "shortened_carrier":
        changed[-1]["geometry"]["end"][0] -= 5
    else:
        changed[0]["geometry"]["start"][0] += 1
        changed[0]["geometry"]["end"][0] += 1
    export_objects(changed, saved, ROI, 200, sha)
    report = cold_carrier_reconciliation(saved, ezdxf.readfile(saved), gray, ROI, 200, tmp_path / "evidence")
    assert not report["pass"]
