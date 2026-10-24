"""Gate 0 only: short artificial CPU/GPU test with restartable optimizer state."""

import argparse
import importlib.metadata
import importlib.util
import json
import os
import platform
import random
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import torch

from data import CLASSES, load, require, validate, write_json
from evaluate import metrics


def environment():
    return {"python": sys.version, "platform": platform.platform(), "torch": str(torch.__version__),
            "numpy": importlib.metadata.version("numpy") if importlib.util.find_spec("numpy") else "NOT_INSTALLED",
            "cuda_available": torch.cuda.is_available(),
            "cuda_device_count": torch.cuda.device_count(),
            "cuda_device_names": [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())],
            "scope": "ARTIFICIAL_ENVIRONMENT_ONLY"}


def configure(seed):
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)


def device_for(requested):
    require(requested in ("cpu", "cuda", "auto"), "Unsupported device")
    return torch.device("cuda" if requested != "cpu" and torch.cuda.is_available() else "cpu")


def check_config(config):
    require(config.get("purpose") == "ENVIRONMENT_ONLY" and config.get("real_training_enabled") is False,
            "Real supervised training is disabled in this entry")
    require(config.get("model") == "linear-18-to-3" and config.get("seed") == 314159,
            "Unrecognized Gate 0 configuration")
    require(config.get("batch_size") == 6 and config.get("learning_rate") == 0.05
            and config.get("momentum") == 0.9 and config.get("maximum_steps") == 8,
            "Gate 0 settings changed")


def run(dataset, config, out, steps=2, resume=None, requested_device="cpu"):
    start = time.perf_counter()
    check_config(config)
    summary = validate(dataset)
    require(type(steps) is int and 0 < steps <= config["maximum_steps"], "Gate 0 step budget exceeded")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    require(not (out / "checkpoint.pt").exists() and not (out / "result.json").exists(),
            "Use a new run directory; previous checkpoint is retained")
    configure(config["seed"])
    device = device_for(requested_device)
    train = [r for r in dataset["samples"] if r["split"] == "train"]
    validation = [r for r in dataset["samples"] if r["split"] == "validation"]
    x = torch.tensor([r["features"] for r in train], dtype=torch.float32)
    y = torch.tensor([CLASSES.index(r["label"]) for r in train], dtype=torch.long, device=device)
    mean, std = x.mean(0), x.std(0, unbiased=False).clamp_min(1e-6)
    model = torch.nn.Linear(18, 3).to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=config["learning_rate"], momentum=config["momentum"])
    completed, history = 0, []
    if resume:
        saved = torch.load(resume, map_location="cpu", weights_only=True)
        require(saved["dataset"] == dataset and saved["config"] == config, "Resume data/config changed")
        require(saved["format"] == "p12a-artificial-checkpoint-v1", "Checkpoint format mismatch")
        require(torch.equal(saved["mean"], mean) and torch.equal(saved["std"], std), "Train scaler mismatch")
        model.load_state_dict(saved["model_state"])
        optimizer.load_state_dict(saved["optimizer_state"])
        random.setstate(saved["python_rng"])
        torch.set_rng_state(saved["torch_rng"])
        if device.type == "cuda" and saved["cuda_rng"]:
            torch.cuda.set_rng_state_all(saved["cuda_rng"])
        completed, history = saved["completed_steps"], saved["history"]
        require(steps > completed, "Resume target must exceed completed steps")
    x = ((x - mean) / std).to(device)
    xv = ((torch.tensor([r["features"] for r in validation]) - mean) / std).to(device)
    model.train()
    for step in range(completed, steps):
        # CPU permutation state is restored even when GPU is used.
        indices = torch.randperm(len(train))[:config["batch_size"]].to(device)
        optimizer.zero_grad(set_to_none=True)
        loss = torch.nn.functional.cross_entropy(model(x[indices]), y[indices])
        require(bool(torch.isfinite(loss)), "Nonfinite artificial loss")
        loss.backward()
        gradient_finite = all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in model.parameters())
        require(gradient_finite, "Missing/nonfinite gradients")
        optimizer.step()
        history.append({"step": step + 1, "loss": float(loss.detach().cpu()), "gradient_finite": gradient_finite})
    model.eval()
    with torch.no_grad():
        probabilities = model(xv).softmax(1).cpu().tolist()
    snapshot = {
        "format": "p12a-artificial-checkpoint-v1", "dataset": dataset, "config": config,
        "completed_steps": steps, "model_state": {k: v.detach().cpu() for k, v in model.state_dict().items()},
        "optimizer_state": optimizer.state_dict(), "mean": mean, "std": std,
        "python_rng": random.getstate(), "torch_rng": torch.get_rng_state(),
        "cuda_rng": torch.cuda.get_rng_state_all() if device.type == "cuda" else [],
        "history": history, "environment": environment(), "device": str(device),
    }
    # A partial write cannot replace the previous complete checkpoint.
    with tempfile.NamedTemporaryFile(dir=out, suffix=".pt", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        torch.save(snapshot, temporary)
        os.replace(temporary, out / "checkpoint.pt")
    finally:
        temporary.unlink(missing_ok=True)
    readback = torch.load(out / "checkpoint.pt", map_location="cpu", weights_only=True)
    require(readback["completed_steps"] == steps and all(torch.equal(value, readback["model_state"][key])
            for key, value in snapshot["model_state"].items()), "Checkpoint readback mismatch")
    result = {"environment": environment(), "selected_device": str(device), "data": summary,
              "completed_steps": steps, "resumed_from_step": completed, "history": history,
              "checkpoint_readback": "PASS", "elapsed_seconds": time.perf_counter() - start,
              "model_parameters": sum(p.numel() for p in model.parameters()),
              "metrics_artificial_only": metrics(validation, probabilities),
              "real_supervised_training": "NOT_RUN", "production_changes": False,
              "predictions": probabilities}
    write_json(out / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    args = parser.parse_args()
    result = run(load(args.dataset), json.loads(args.config.read_text(encoding="utf-8")), args.out,
                 args.steps, args.resume, args.device)
    print(json.dumps({k: v for k, v in result.items() if k not in ("predictions", "metrics_artificial_only")}, indent=2))
