"""Future small research CNN runner with atomic resume. No training in P3B.

Optional torch dependency is loaded only when this command is explicitly run.
No production import, DXF output, blind loader, or cloud-VM dependency.
"""

import argparse
import os
import random
import shutil
from pathlib import Path

import numpy as np

from common import (
    LABELS,
    atomic_json,
    check_output,
    digest,
    read,
    read_rows,
    sha,
    validate_samples,
)
from benchmark import evaluate, join_labels
from features import FEATURE_NAMES, feature_vector, image_tensor


def make_model(torch):
    nn = torch.nn

    class SmallCNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.image = nn.Sequential(
                nn.Conv2d(3, 16, 5, stride=2, padding=2),
                nn.ReLU(),
                nn.Conv2d(16, 32, 3, stride=2, padding=1),
                nn.ReLU(),
                nn.Conv2d(32, 64, 3, stride=2, padding=1),
                nn.ReLU(),
                nn.AdaptiveAvgPool2d(1),
                nn.Flatten(),
            )
            self.head = nn.Sequential(
                nn.Linear(64 + len(FEATURE_NAMES), 64),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(64, 4),
            )

        def forward(self, image, features):
            return self.head(torch.cat((self.image(image), features), dim=1))

    return SmallCNN()


def save_checkpoint(torch, path, state):
    temp = path.with_suffix(".tmp")
    with temp.open("wb") as stream:
        torch.save(state, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def run(args):
    labels = read(args.labels)
    if labels.get("training_authorized") is not True:
        raise ValueError("Pilot/acceptance labels are not training-authorized")
    import torch

    rows = read_rows(args.manifest)
    labels = read(args.labels)
    if labels.get("training_authorized") is not True:
        raise ValueError("Pilot/acceptance labels are not training-authorized")
    if labels["manifest_sha256"] != sha(args.manifest):
        raise ValueError("Labels/dataset mismatch")
    rows = join_labels(rows, labels)
    validate_samples(rows)
    if any(r["split"] == "blind_test" for r in rows):
        raise ValueError("Blind sources prohibited")
    train = [r for r in rows if r["split"] == "train" and r["label"] in LABELS]
    validation = [
        r for r in rows if r["split"] == "validation" and r["label"] in LABELS
    ]
    if set(r["label"] for r in train) != set(LABELS) or not validation:
        raise ValueError(
            "Four-class human seed and independently sourced validation required"
        )
    split_manifest = read(args.splits)
    assignments = {d["source_drawing_id"]: d for d in split_manifest["drawings"]}
    for r in rows:
        if r["domain"] == "real" and (
            r["source_drawing_id"] not in assignments
            or assignments[r["source_drawing_id"]]["split"] != r["split"]
        ):
            raise ValueError("Samples differ from split manifest")
    out = check_output(args.scratch)
    seed = args.seed
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    device = torch.device(
        "cuda" if args.device == "cuda" and torch.cuda.is_available() else "cpu"
    )
    config = {
        "seed": seed,
        "batch_size": args.batch_size,
        "lr": 0.001,
        "model": "3conv-16-32-64",
        "device": str(device),
        "features": FEATURE_NAMES,
        "input": [3, 256, 256],
        "preprocess_version": "p3b-v1",
        "torch_version": str(torch.__version__),
    }
    binding = {
        "dataset_version": sha(args.manifest),
        "label_version": sha(args.labels),
        "split_manifest": split_manifest,
        "configuration": config,
    }
    model = make_model(torch).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    base = args.patch_root or args.manifest.parent
    # This is the classical train-only scaler; validation statistics never fit normalization.
    features = np.stack([feature_vector(r, base / r["patch_dir"]) for r in train])
    mean, scale = features.mean(0), np.maximum(features.std(0), 1e-6)
    epoch, history = 0, []
    checkpoint = out / "last.pt"
    if args.resume:
        # Load only this locally generated trusted checkpoint; never arbitrary third-party pickle files.
        state = torch.load(checkpoint, map_location=device, weights_only=False)
        if digest(state["binding"]) != digest(binding):
            raise ValueError(
                "Checkpoint data/labels/splits/config changed; create a new run"
            )
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        epoch, history = state["epoch"], state["metrics"]
        mean, scale = state["feature_mean"], state["feature_scale"]
        random.setstate(state["python_rng"])
        np.random.set_state(state["numpy_rng"])
        torch.set_rng_state(state["torch_rng"].cpu())
        if torch.cuda.is_available() and state["cuda_rng"] is not None:
            torch.cuda.set_rng_state_all([s.cpu() for s in state["cuda_rng"]])

    def batch(selected):
        image = torch.from_numpy(
            np.stack([image_tensor(r, base / r["patch_dir"]) for r in selected])
        ).to(device)
        f = np.stack([feature_vector(r, base / r["patch_dir"]) for r in selected])
        feat = torch.from_numpy((f - mean) / scale).to(device)
        target = torch.tensor(
            [LABELS.index(r["label"]) for r in selected], device=device
        )
        return image, feat, target

    for current in range(epoch, args.epochs):
        model.train()
        order = np.random.permutation(len(train))
        for start in range(0, len(order), args.batch_size):
            chosen = [train[i] for i in order[start : start + args.batch_size]]
            image, feat, target = batch(chosen)
            optimizer.zero_grad()
            loss = torch.nn.functional.cross_entropy(model(image, feat), target)
            loss.backward()
            optimizer.step()
        model.eval()
        predictions = []
        with torch.no_grad():
            for start in range(0, len(validation), args.batch_size):
                chosen = validation[start : start + args.batch_size]
                image, feat, _ = batch(chosen)
                probabilities = torch.softmax(model(image, feat), dim=1).cpu().numpy()
                predictions.extend(
                    {
                        "sample_id": r["sample_id"],
                        "probabilities": dict(zip(LABELS, map(float, p))),
                    }
                    for r, p in zip(chosen, probabilities)
                )
        metrics = evaluate(validation, predictions)
        history.append({"epoch": current + 1, "validation": metrics})
        state = {
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "epoch": current + 1,
            "binding": binding,
            "dataset_version": binding["dataset_version"],
            "label_version": binding["label_version"],
            "split_manifest": split_manifest,
            "seed": seed,
            "metrics": history,
            "configuration": config,
            "feature_mean": mean,
            "feature_scale": scale,
            "python_rng": random.getstate(),
            "numpy_rng": np.random.get_state(),
            "torch_rng": torch.get_rng_state(),
            "cuda_rng": torch.cuda.get_rng_state_all()
            if torch.cuda.is_available()
            else None,
        }
        save_checkpoint(torch, checkpoint, state)
        atomic_json(out / "metrics.json", history)
        if args.sync_dir:
            args.sync_dir.mkdir(parents=True, exist_ok=True)
            temp = args.sync_dir / "last.pt.tmp"
            shutil.copyfile(checkpoint, temp)
            os.replace(temp, args.sync_dir / "last.pt")
        print("Epoch", current + 1, "checkpoint saved", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Future offline research training; human seed required"
    )
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--splits", type=Path, required=True)
    ap.add_argument("--scratch", type=Path, required=True)
    ap.add_argument("--patch-root", type=Path)
    ap.add_argument("--sync-dir", type=Path)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--seed", type=int, default=314159)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    run(ap.parse_args())
