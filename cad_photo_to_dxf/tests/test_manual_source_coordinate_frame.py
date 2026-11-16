"""Manual source matching uses the emitted contour frame, never a looser tolerance."""
import ezdxf
import numpy as np
import pytest

from app.core import manual_text_recovery as manual
from app.core.review_project import ReviewProjectError
from app.export.document_export import DocumentPage
from app.export.trace_document_export import export_trace_document_streaming
from tests.test_manual_text_recovery import confirm, layout, project  # noqa: F401


@pytest.mark.parametrize("paper", [(100., 100.), (200., 100.), (50., 150.)])
def test_complete_manual_backup_follows_raster_centers(project, tmp_path, paper):
    record = layout(project, confirm(project))
    path = tmp_path / "paper.dxf"
    export_trace_document_streaming(
        [DocumentPage(1, None, paper, final_structure=project.baseline,
                      text_review=project.validated_review())], path)
    doc = ezdxf.readfile(path)
    backups = [e for e in doc.modelspace().query("LWPOLYLINE") if e.has_xdata(manual.APPID)]
    assert len(backups) == 1
    expected = [[(x + .5) * paper[0] / 1000., (1000. - y - .5) * paper[1] / 1000.]
                for x, y in record["evidence"]["contours"][0]["points"]]
    assert np.allclose(backups[0].get_points("xy"), expected, rtol=0, atol=1e-7)
    assert doc.layers.get(backups[0].dxf.layer).is_frozen()
    assert [e.dxf.text for e in doc.modelspace().query("TEXT")] == ["7", "1"]


def test_wrong_manual_source_frame_still_blocks_export(project, tmp_path, monkeypatch):
    layout(project, confirm(project))
    original = manual.emit

    def wrong_frame(*args, **kwargs):
        kwargs.pop("source_transform", None)
        return original(*args, **kwargs)

    monkeypatch.setattr(manual, "emit", wrong_frame)
    output = tmp_path / "wrong.dxf"
    with pytest.raises(ReviewProjectError, match="complete manual source boundary"):
        export_trace_document_streaming(
            [DocumentPage(1, None, (100., 100.), final_structure=project.baseline,
                          text_review=project.validated_review())], output)
    assert not output.exists()
