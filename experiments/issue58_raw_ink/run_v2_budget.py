"""Replay the frozen v2 model with an explicitly declared axis resource budget.

Only the maximum number of nominated axes may change. This does not change the
candidate rules, their numerical thresholds, source pixels or selection order.
The full originally stopped receipt must be retained separately.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
from PIL import Image

spec = importlib.util.spec_from_file_location("raw_band_v2_budget_target", Path(__file__).with_name("candidates_v2.py"))
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


def run(gray, roi, maximum_seed_axes):
    if not isinstance(maximum_seed_axes, int) or maximum_seed_axes < 1:
        raise ValueError("AXIS_RESOURCE_BUDGET_MUST_BE_POSITIVE_INTEGER")
    original = deepcopy(model.POLICY)
    try:
        model.POLICY["maximum_seed_axes"] = maximum_seed_axes
        result = model.discover(gray, roi)
        result["policy"] = deepcopy(result["policy"])
        result["resource_budget_override"] = {
            "only_changed_field": "maximum_seed_axes",
            "from": original["maximum_seed_axes"], "to": maximum_seed_axes,
            "frozen_model_policy_sha256": model.base.digest(original),
            "effective_policy_sha256": model.base.digest(model.POLICY),
            "all_nominated_axes_are_processed_or_withheld": True,
            "source_and_acceptance_rules_unchanged": True,
        }
        result["resource_runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        return result
    finally:
        model.POLICY.clear()
        model.POLICY.update(original)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--roi", type=int, nargs=4, required=True)
    parser.add_argument("--maximum-seed-axes", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with Image.open(args.input) as im:
        gray = np.array(im.convert("L"))
    result = run(gray, args.roi, args.maximum_seed_axes)
    result["input_file_sha256"] = hashlib.sha256(args.input.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "axes": len(result["seed_axes"]),
                      "candidate_count": len(result["candidates"]), "resources": result["resources"],
                      "complete_recovered_objects": 0, "wall_seconds": result["wall_seconds"]}))


if __name__ == "__main__":
    main()
