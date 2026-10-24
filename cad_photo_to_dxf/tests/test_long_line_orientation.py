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


def test_original_pixels_restored_only_after_disjoint_upright_edge_votes():
    source = _source()
    classifier = Classifier([("0", 0.99), ("0", 0.63), ("0", 0.98)])
    result = LongLineOrientationClassifier(classifier)([source])
    assert np.array_equal(result.img_list[0], source)
    assert result.cls_res == [("0", 0.98)]
    assert all(crop.shape == (32, 128, 3) for crop in classifier.calls[1])
    assert np.array_equal(classifier.calls[1][0], source[:, :128])
    assert np.array_equal(classifier.calls[1][-1], source[:, -128:])


@pytest.mark.parametrize(
    "votes",
    [
        [("180", 0.99)] * 3,
        [("0", 0.94), ("0", 0.99), ("0", 0.99)],
        [("0", 0.99), ("180", 0.99), ("0", 0.99)],
        [("0", 0.99), ("0", float("nan")), ("0", 0.99)],
        [("0", 0.99), ("?", 0.1), ("0", 0.99)],
        [("0", 0.99)],
    ],
)
def test_reverse_uncertain_invalid_or_contradictory_windows_preserve_backend(votes):
    source = _source()
    result = LongLineOrientationClassifier(Classifier(votes))([source])
    assert np.array_equal(result.img_list[0], cv2.rotate(source, cv2.ROTATE_180))
    assert result.cls_res == [("180", 0.999)]


@pytest.mark.parametrize("width,label", [(255, "180"), (401, "0")])
def test_short_or_already_upright_line_does_not_trigger_review(width, label):
    classifier = Classifier([], label)
    LongLineOrientationClassifier(classifier)([_source(width)])
    assert len(classifier.calls) == 1


def test_installed_engine_uses_input_adapter():
    from app.ocr import ocr_recognition

    engine = ocr_recognition._get_rapidocr_engine()
    assert isinstance(engine.text_cls, LongLineOrientationClassifier)


def test_cache_identity_separates_old_orientation_outputs():
    from dataclasses import replace
    from app.core.processing import ProductionProcessingConfig

    config = ProductionProcessingConfig()
    assert "long-line-orientation-v1" in config.algorithm_version
    assert (
        replace(
            config,
            algorithm_version=config.algorithm_version.replace(
                "-long-line-orientation-v1", ""
            ),
        )
        != config
    )
