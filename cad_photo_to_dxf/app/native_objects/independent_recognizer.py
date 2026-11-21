"""Local recognition-only PP-OCRv6 small, with explicit raw CTC evidence.

Uses the project's pinned RapidOCR 3.9.2 model and its published normalization
and greedy CTC decoding. No detector, orientation classifier, dictionary
correction, remote inference, or expected text is used. Confidence is reported
in this model's own units, never converted into a Tesseract confidence.
"""

from __future__ import annotations
import hashlib
import math
from pathlib import Path
import time
import cv2
import numpy as np
from .execution import check_cancel
from .offline_runtime import private_onnxruntime, runtime_privacy_status


MODEL_SHA256 = "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884"
POLICY = {
    "version": "local-ppocrv6-recognition-only-v1",
    "height": 48,
    "minimum_canvas_width": 320,
    "batch_size": 1,
    "CPU_threads": 1,
    "recognition_source_pixels_rewritten": False,
    "normalization_is_model_input_only": True,
    "expected_transcriptions_or_dictionary_correction": False,
    "download_at_runtime": False,
}


def prepare_model_input(crop):
    """Deterministic model normalization; also verifies imported raw evidence."""
    original = np.asarray(crop, dtype=np.uint8)
    if original.ndim != 2 or original.size == 0:
        raise ValueError("RECOGNIZER_REQUIRES_NONEMPTY_ORIGINAL_GRAYSCALE_CROP")
    h, w = original.shape
    resized_width = int(math.ceil(POLICY["height"] * w / h))
    canvas_width = max(POLICY["minimum_canvas_width"], resized_width)
    rgb = cv2.cvtColor(original, cv2.COLOR_GRAY2BGR)
    resized = cv2.resize(rgb, (resized_width, POLICY["height"]))
    normalized = resized.astype(np.float32).transpose(2, 0, 1) / 255.0
    normalized = (normalized - 0.5) / 0.5
    tensor = np.zeros((1, 3, POLICY["height"], canvas_width), dtype=np.float32)
    tensor[0, :, :, :resized_width] = normalized
    return original, tensor


class IndependentRecognizer:
    def __init__(self, model_path=None):
        ort = private_onnxruntime()

        if model_path is None:
            import importlib.util

            specification = importlib.util.find_spec("rapidocr")
            if specification is None or not specification.origin:
                raise RuntimeError("PINNED_LOCAL_RECOGNITION_MODEL_NOT_AVAILABLE")
            model_path = (
                Path(specification.origin).parent / "models/PP-OCRv6_rec_small.onnx"
            )
        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError("LOCAL_RECOGNITION_MODEL_MISSING:" + str(path))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != MODEL_SHA256:
            raise ValueError("LOCAL_RECOGNITION_MODEL_SHA_MISMATCH")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        self.session = ort.InferenceSession(
            str(path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        raw_characters = self.session.get_modelmeta().custom_metadata_map["character"]
        self.characters = ["blank"] + raw_characters.splitlines() + [" "]
        self.input_name = self.session.get_inputs()[0].name
        self.identity = {
            "name": "PP-OCRv6_rec_small",
            "distribution": "RapidOCR 3.9.2",
            "model_path": str(path),
            "model_sha256": digest,
            "ONNXRuntime": ort.__version__,
            "providers": self.session.get_providers(),
            "character_dictionary_sha256": hashlib.sha256(
                raw_characters.encode()
            ).hexdigest(),
            "policy": POLICY,
            "runtime_privacy": runtime_privacy_status(),
        }

    def recognize(self, crop):
        import json
        from .observation_cache import (
            canonical_bytes,
            configured_cache,
            model_spec,
            producer_identity,
        )

        check_cancel()
        start = time.perf_counter()
        original, tensor = prepare_model_input(crop)
        h, w = original.shape
        cache = configured_cache()
        cache_spec = (
            model_spec(original, tensor, self.identity) if cache is not None else None
        )
        cached = cache.lookup(cache_spec) if cache is not None else None
        if cached is not None:
            # Return the original raw record unchanged, including its original
            # producer timing. The task's usage ledger records the reuse and
            # distinguishes that timing from current worker CPU/wall use.
            self.last_observation = {
                "raw_observation_cache": cached[1],
                "model_inference_executed_for_this_request": False,
            }
            return json.loads(cached[0])
        predictions = self.session.run(None, {self.input_name: tensor})[0][0]
        if predictions.shape[-1] != len(self.characters):
            raise ValueError("CTC_DICTIONARY_MODEL_DIMENSION_MISMATCH")
        indices = predictions.argmax(axis=1)
        scores = predictions.max(axis=1)
        selected = np.ones(len(indices), dtype=bool)
        selected[1:] = indices[1:] != indices[:-1]
        selected &= indices != 0
        tokens = [
            {
                "time_step": int(index),
                "token_index": int(indices[index]),
                "character": self.characters[int(indices[index])],
                "score": float(scores[index]),
            }
            for index in np.flatnonzero(selected)
        ]
        raw = "".join(t["character"] for t in tokens)
        confidence = float(np.mean([t["score"] for t in tokens])) if tokens else None
        result = {
            "raw_text": raw,
            "model_mean_confidence": confidence,
            "minimum_emitted_character_confidence": min(
                (t["score"] for t in tokens), default=None
            ),
            "raw_CTC_tokens": tokens,
            "input_shape_px": [h, w],
            "input_array_sha256": hashlib.sha256(original.tobytes()).hexdigest(),
            "model_tensor_shape": list(tensor.shape),
            "model_tensor_sha256": hashlib.sha256(tensor.tobytes()).hexdigest(),
            "resize_for_model_inference_only": True,
            "source_geometry_modified": False,
            "raw_transcription_rewritten": False,
            "wall_seconds": time.perf_counter() - start,
        }
        receipt = None
        if cache is not None:
            receipt = cache.put(
                cache_spec,
                canonical_bytes(result),
                producer_identity(__file__, engine=self.identity),
            )
        self.last_observation = {
            "raw_observation_cache": receipt,
            "model_inference_executed_for_this_request": True,
        }
        return result
