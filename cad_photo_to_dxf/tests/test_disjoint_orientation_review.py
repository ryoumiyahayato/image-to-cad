"""Additional disjoint window votes require corroboration, not expected text."""
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.ocr.long_line_orientation import LongLineOrientationClassifier
class Classifier:
    cls_image_shape = (3, 48, 192)
    cls_thresh = 0.9

    def __init__(self, votes, label="180"):
        self.votes, self.label, self.calls = votes, label, []

    def __call__(self, crops):
        self.calls.append(crops)
        labels = (
            [(self.label, 0.999)] * len(crops) if len(self.calls) == 1 else self.votes
        )
        return SimpleNamespace(
            cls_res=labels,
            elapse=0.01,
            img_list=[
                cv2.rotate(crop, cv2.ROTATE_180) if label == "180" else crop.copy()
                for crop, (label, score) in zip(crops, labels)
            ],
        )


def _source(width=401):
    image = np.full((32, width, 3), 255, np.uint8)
    image[4:18, 3:7] = 0
    image[20:24, -20:-4] = 0
    return image





class Recognition:
    def __init__(self, texts=('ARBITRARY SOURCE LABEL', 'ARBITRARY SOURCE LABEL'), scores=(.98,.97)):
        self.texts, self.scores, self.calls = texts, scores, []

    def __call__(self, images):
        self.calls.append(images)
        return SimpleNamespace(txts=self.texts, scores=self.scores)


@pytest.mark.parametrize('votes', [
    [('180',.53),('0',.99),('0',.98)],
    [('0',.99),('0',.98),('180',.53)],
])
def test_additional_disjoint_pair_needs_stable_unrotated_source(votes):
    src = _source(401); rec = Recognition()
    out = LongLineOrientationClassifier(Classifier(votes), rec)([src])
    assert out.cls_res == [('0',.98)]
    assert np.array_equal(out.img_list[0], src)
    assert np.array_equal(rec.calls[0][0], src)
    pad=max(2,round(src.shape[0]*.1))
    assert np.array_equal(rec.calls[0][1][pad:-pad,pad:-pad], src)
    assert np.all(rec.calls[0][1][:pad] == 255)


@pytest.mark.parametrize('texts,scores', [
    (('ABCDEF','ABCOEF'),(.999,.999)),
    (('ABCDEF','ABCDEF'),(.94,.999)),
    (('ABCDEF','ABCDEF'),(.999,float('nan'))),
    (('ABCDEF',),(.999,)),
    (('6/6','6/6'),(.999,.999)),
    (('',''),(.999,.999)),
])
def test_disagreement_or_insufficient_reading_preserves_original_decision(texts,scores):
    src=_source(); rec=Recognition(texts,scores)
    out=LongLineOrientationClassifier(Classifier([('180',.53),('0',.99),('0',.98)]),rec)([src])
    assert out.cls_res == [('180',.999)]
    assert np.array_equal(out.img_list[0], cv2.rotate(src,cv2.ROTATE_180))


def test_overlap_is_not_two_independent_votes():
    src=_source(300);rec=Recognition()
    out=LongLineOrientationClassifier(Classifier([('180',.53),('0',.99),('0',.98)]),rec)([src])
    assert out.cls_res == [('180',.999)]
    assert not rec.calls


@pytest.mark.parametrize('votes', [
    [('180',.99),('0',.99),('0',.99)],
    [('0',.99),('180',.99),('0',.99)],
    [('180',.99),('180',.99),('180',.99)],
])
def test_confident_reverse_window_is_not_overridden(votes):
    src=_source();rec=Recognition()
    out=LongLineOrientationClassifier(Classifier(votes),rec)([src])
    assert out.cls_res == [('180',.999)]
    assert not rec.calls


def test_recognition_failure_preserves_original():
    def broken(_): raise RuntimeError('optional recognizer unavailable')
    src=_source();out=LongLineOrientationClassifier(Classifier([('180',.53),('0',.99),('0',.98)]),broken)([src])
    assert out.cls_res == [('180',.999)]


def test_version_separates_modified_direction():
    from app.core.processing import ProductionProcessingConfig
    assert 'disjoint-window-reading-v2' in ProductionProcessingConfig().algorithm_version
