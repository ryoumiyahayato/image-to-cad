from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from app.version import PRODUCT_STATUS, product_status_payload
from main import build_parser
from scripts.versioning import require_product_release_approval


APP_ROOT = Path(__file__).resolve().parents[1]


def test_current_entry_distinguishes_target_from_shipped_pipeline() -> None:
    payload = product_status_payload()
    assert payload["status"] == PRODUCT_STATUS == "LOCAL_NO_GO"
    assert payload["running_pipeline"] == "native-objects"
    assert payload["native_object_reconstruction_verified"] is False
    assert payload["reference_geometry_counts_as_reconstruction"] is False
    help_text = " ".join(build_parser().format_help().split())
    assert "LOCAL_NO_GO" in help_text
    assert "Default engine: native-objects" in build_parser().description
    assert product_status_payload("legacy")["running_pipeline"] == "preserved_main_baseline"


@pytest.mark.parametrize("version,status", [
    ("0.3.0-dev", "LOCAL_NO_GO"),
    ("0.3.0", "LOCAL_NO_GO"),
    ("0.3.0-dev", "GO"),
    ("0.3.0", "NOT_RUN"),
])
def test_release_rejects_unaccepted_status_and_development_versions(version, status) -> None:
    with pytest.raises(RuntimeError, match="Formal release blocked"):
        require_product_release_approval(version, status)


def test_actual_release_command_fails_closed_before_building() -> None:
    result = subprocess.run(
        [sys.executable, "-c", (
            "from scripts.versioning import require_product_release_approval; "
            "require_product_release_approval()"
        )],
        cwd=APP_ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "0.3.0-dev / LOCAL_NO_GO" in result.stderr
    assert "Formal release blocked" in result.stderr


def test_release_workflow_checks_approval_before_dependency_installation() -> None:
    workflow = (APP_ROOT.parent / ".github/workflows/release.yml").read_text(encoding="utf-8")
    gate = workflow.index("Require current product release approval")
    dependencies = workflow.index("Install application dependencies and pinned FreeCAD")
    assert gate < dependencies
    assert "require_product_release_approval()" in workflow


@pytest.mark.parametrize("chosen_suffix,selected_filter,expected_dwg", [
    ("", "Drawing Exchange Format (*.dxf)", False),
    (".dwg", "AutoCAD DWG (*.dwg)", True),
])
def test_gui_export_defaults_to_dxf_but_preserves_explicit_dwg(
    tmp_path, monkeypatch, chosen_suffix, selected_filter, expected_dwg,
) -> None:
    from app.gui import export_dialogs

    monkeypatch.chdir(tmp_path)
    chosen = tmp_path / f"result{chosen_suffix}"

    def choose(_window, _title, default_path, filters):
        assert default_path.endswith("drawing-page.dxf")
        assert filters.split(";;")[0] == "Drawing Exchange Format (*.dxf)"
        return str(chosen), selected_filter

    monkeypatch.setattr(export_dialogs.QFileDialog, "getSaveFileName", choose)
    result = export_dialogs._select_output_path(None, default_name="drawing-page.dxf")
    expected = chosen if expected_dwg else chosen.with_suffix(".dxf")
    assert result == (expected, expected_dwg)
