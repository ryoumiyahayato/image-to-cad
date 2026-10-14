from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from app.ocr.auxiliary_recognition import TextCandidate
from app.geometry.line_detect import LineSegment
from app.geometry.optimized_trace import _assign_and_reconcile


def test_new_committed_piece_still_must_pass_semantic_ownership():
    binary = np.full((120,180),255,np.uint8)
    cv2.rectangle(binary,(20,30),(140,70),0,-1)
    text = TextCandidate('TEXT',(20,30,120,40),0.99,'text_candidate',approved=True,reviewed=True)
    rejected_restore = LineSegment(25,50,130,50)
    # Exercise the boundary against a faulty reconciliation admission, rather
    # than trusting that one implementation can never violate another's veto.
    ledger = SimpleNamespace(
        consolidate_detector_aliases=lambda lines: tuple(lines),
        reconcile=lambda **kwargs: SimpleNamespace(lines=(rejected_restore,)),
    )
    with pytest.raises(AssertionError, match='Ownership rejected'):
        _assign_and_reconcile(binary,line_candidates=[],texts=(text,),logos=(),signatures=(),
                              graphic_mask=np.zeros_like(binary),signature_mask=np.zeros_like(binary),
                              reconciliation_ledger=ledger,late_restorations=[],performance_callback=None)
