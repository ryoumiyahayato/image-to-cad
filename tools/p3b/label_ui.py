"""Two-stage local review. V1 is frozen and never accepted by this UI."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
import uuid

from PIL import Image, ImageTk

from common import LABELS, atomic_json, digest, read, read_rows, sha, validate_samples
from target_view import target_overlay, target_zoom, annotated_zoom

NOMINATION_STATUSES = ("VALID_TARGET", "INVALID_NOMINATION", "UNCLEAR_TARGET")


class LabelStore:
    def __init__(
        self, path, manifest, annotator, purpose="30-sample UI acceptance only"
    ):
        self.path = Path(path)
        self.annotator = annotator
        self.manifest_sha = sha(manifest)
        self.state = (
            read(path)
            if self.path.exists()
            else {
                "schema_version": "p3b-label-v2",
                "manifest_sha256": self.manifest_sha,
                "labels": {},
                "nomination_statuses": {},
                "skipped": {},
                "events": [],
                "review_log": [],
                "cursor_sample_id": None,
                "revision": 0,
                "training_authorized": False,
                "purpose": purpose,
            }
        )
        if self.state.get("schema_version") != "p3b-label-v2":
            raise ValueError(
                "V1 is frozen PILOT_V1_UNVERIFIED; use a NEW V2 label file"
            )
        if self.state["manifest_sha256"] != self.manifest_sha:
            raise ValueError("Labels belong to a different manifest; do not overwrite")
        if self.state["purpose"] != purpose or self.state["training_authorized"]:
            raise ValueError(
                "Wrong review purpose or unexpected training authorization"
            )
        self.session_id = str(uuid.uuid4())

    def log(self, action, **fields):
        self.state["review_log"].append(
            {
                "action": action,
                "session_id": self.session_id,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                **fields,
            }
        )

    def event(self, sample, action):
        sid = sample["sample_id"]
        self.state["events"].append(
            {
                "sample_id": sid,
                "action": action,
                "previous_label": self.state["labels"].get(sid),
                "previous_nomination": self.state["nomination_statuses"].get(sid),
                "previous_skip": self.state["skipped"].get(sid),
            }
        )

    def nominate(self, sample, status):
        if status not in NOMINATION_STATUSES:
            raise ValueError("Invalid nomination status")
        if sample.get("label_contract") != "p3b-label-v2":
            raise ValueError("Frozen V1 samples cannot receive V2 decisions")
        if status == "VALID_TARGET":
            metrics = sample.get("quality", {}).get("metrics", {})
            geometry = sample.get("candidate_geometry", [])
            supported = (
                all(
                    metrics.get(prefix + "_SOURCE_SUPPORT_RATIO", 0) > 0
                    for prefix in ("A", "B")[: len(geometry)]
                )
                if geometry
                else metrics.get("TARGET_INK_PIXELS", 0) >= 4
            )
            if not supported:
                raise ValueError(
                    "Zero source support cannot enter Stage 1; use X for an invalid nomination."
                )
        sid = sample["sample_id"]
        self.event(sample, "nomination")
        self.state["nomination_statuses"][sid] = {
            "status": status,
            "annotator": self.annotator,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "sample_sha256": digest(sample),
            "provenance": "human_stage_0_review",
        }
        if status != "VALID_TARGET":
            self.state["labels"].pop(sid, None)
        self.state["skipped"].pop(sid, None)
        self.log("nomination", sample_id=sid, status=status)
        self.save()

    def assign(self, sample, label):
        if label not in LABELS:
            raise ValueError("Unknown physical class")
        sid = sample["sample_id"]
        nomination = self.state["nomination_statuses"].get(sid, {})
        if nomination.get("status") != "VALID_TARGET" or nomination.get(
            "sample_sha256"
        ) != digest(sample):
            raise ValueError(
                "Stage 0 first: V = valid target. Unsupported candidates are X; unclear targets are U."
            )
        self.event(sample, "label")
        self.state["labels"][sid] = {
            "label": label,
            "annotator": self.annotator,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "provenance": "human_source_review_after_stage_0",
            "sample_sha256": digest(sample),
            "nomination_status": "VALID_TARGET",
            "rubric_version": "p3b-rubric-v2",
            "training_authorized": False,
        }
        self.state["skipped"].pop(sid, None)
        self.log("physical_class", sample_id=sid, label=label)
        self.save()

    def skip(self, sample):
        sid = sample["sample_id"]
        self.event(sample, "skip")
        self.state["skipped"][sid] = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
        }
        self.log("skip", sample_id=sid)
        self.save()

    def present(self, sample, index):
        self.state["cursor_sample_id"] = sample["sample_id"]
        self.log("present", sample_id=sample["sample_id"], queue_rank=index + 1)
        self.save()

    def undo(self):
        if not self.state["events"]:
            return None
        event = self.state["events"].pop()
        sid = event["sample_id"]
        for field, previous in (
            ("labels", "previous_label"),
            ("nomination_statuses", "previous_nomination"),
            ("skipped", "previous_skip"),
        ):
            value = event[previous]
            if value is None:
                self.state[field].pop(sid, None)
            else:
                self.state[field][sid] = value
        self.state["cursor_sample_id"] = sid
        self.log("undo", sample_id=sid, reversed_action=event["action"])
        self.save()
        return sid

    def save(self):
        self.state["revision"] += 1
        self.state["label_version"] = digest(
            {
                "labels": self.state["labels"],
                "nomination_statuses": self.state["nomination_statuses"],
            }
        )
        atomic_json(self.path, self.state)


def diverse_order(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["source_drawing_id"]].append(row)
    return [
        groups[group][i]
        for i in range(max((len(g) for g in groups.values()), default=0))
        for group in sorted(groups)
        if i < len(groups[group])
    ]


class LabelApp:
    def __init__(
        self,
        window,
        manifest,
        labels,
        annotator,
        patch_root=None,
        mode="acceptance",
        on_complete=None,
    ):
        rows = read_rows(manifest)
        validate_samples(rows)
        simplified = mode in ("validation", "validation-suspect")
        expected_split = "validation" if simplified else "train"
        if any(r["split"] != expected_split for r in rows):
            raise ValueError(
                f"This review is {expected_split}-only; no other split may enter"
            )
        if any(
            r.get("label_contract") != "p3b-label-v2"
            or not r.get("quality", {}).get("HUMAN_QUEUE_ELIGIBLE")
            or not (r.get("candidate_geometry") or r.get("target_roi"))
            for r in rows
        ):
            raise ValueError(
                "Only explicit, quality-gated V2 targets may enter this UI; V1 is frozen"
            )
        self.mode = mode
        self.simplified = simplified
        self.on_complete = on_complete
        self.last_completion_version = None
        purpose = "30-sample UI acceptance only"
        if mode == "formal-seed":
            docs = Path(__file__).resolve().parents[2] / "docs/product-fix-p3b"
            plan = read(docs / "formal-seed-v2-summary.json")
            audit = read(docs / "v2-acceptance-audit.json")
            if (
                audit["V2_UI_ACCEPTANCE"] != "PASS"
                or plan["acceptance_state_sha256"] != audit["state_sha256"]
                or sha(docs / "labels/v2-ui-acceptance.json") != audit["state_sha256"]
                or sha(docs / "split-manifest.json") != plan["split_manifest_sha256"]
                or sha(manifest) != plan["manifest_sha256"]
                or len(rows) != plan["proposed_first_batch_size"]
                or plan["training_authorized"]
                or Path(labels).resolve() != Path(plan["labels_path"]).resolve()
            ):
                raise ValueError(
                    "Formal seed must match the prepared queue and current V2 PASS"
                )
            purpose = "formal human seed labeling; no training authorized"
        elif mode == "suspect-review":
            docs = Path(__file__).resolve().parents[2] / "docs/product-fix-p3b"
            plan = read(docs / "suspect-review-v2-001-plan.json")
            if (
                len(rows) != 13
                or sha(manifest) != plan["manifest_sha256"]
                or [r["original_rank"] for r in rows] != plan["original_rank_order"]
                or Path(labels).resolve() != Path(plan["labels_path"]).resolve()
                or sha(docs / "labels/formal-seed-v2-001.json")
                != plan["original_state_sha256"]
                or sha(docs / "formal-seed-v2-001.jsonl")
                != plan["original_manifest_sha256"]
                or sha(docs / "suspect-review-v2-001-original-evidence.json")
                != plan["original_evidence_sha256"]
            ):
                raise ValueError(
                    "Suspect review must match its 13 frozen recommendations and separate label state"
                )
            purpose = "13-sample independent suspect re-review; no training authorized"
        elif mode == "validation-suspect":
            from validation_suspects import PURPOSE, verify

            verify(manifest, labels, patch_root)
            purpose = PURPOSE
        elif mode == "validation":
            # Import at invocation time: preparation imports diverse_order above.
            from validation_review import verify_batch, PURPOSE

            verify_batch(manifest, labels, patch_root)
            purpose = PURPOSE
        elif mode != "acceptance" or len(rows) > 30:
            raise ValueError("Acceptance review is limited to 30 samples")
        self.rows = (
            rows
            if mode in ("suspect-review", "validation-suspect")
            else diverse_order(rows)
        )
        self.base = patch_root or Path(manifest).parent
        self.store = LabelStore(labels, manifest, annotator, purpose)
        self.window = window
        cursor = self.store.state.get("cursor_sample_id")
        self.index = next(
            (i for i, r in enumerate(self.rows) if r["sample_id"] == cursor), 0
        )
        self.context_open = False
        self.images = []
        self.popup_windows = []
        window.title(f"Image to CAD — {len(rows)}-target {mode}: stage 0 then stage 1")
        if simplified:
            window.title(f"Image to CAD — {len(rows)}-sample independent validation")
        if mode == "validation-suspect":
            window.title("Image to CAD — 8-sample validation suspect re-review")
        available_height = min(920, window.winfo_screenheight() - 80)
        self.display_scale = 2 if available_height >= 860 else 1
        window.geometry(
            f"{min(1160, window.winfo_screenwidth() - 40)}x{available_height}"
        )
        self.status, self.stage, self.note = (
            tk.StringVar(),
            tk.StringVar(),
            tk.StringVar(),
        )
        tk.Label(window, textvariable=self.status, font=("Segoe UI", 12)).pack(pady=5)
        tk.Label(
            window,
            text=(
                "Identify the exact target: A = RED; B = BLUE; dots = endpoints.\n"
                "1–4 confirms that target and saves its class. X = bad nomination; U = unclear target display."
                if simplified
                else "Identify the exact nominated target first. A = RED; B = BLUE. Dots mark endpoints.\n"
                "No matching source object: X. Cannot identify target: U. Source class uncertainty AFTER V: 4."
            ),
            font=("Segoe UI", 10),
        ).pack()
        panes = tk.Frame(window)
        panes.pack(pady=5)
        self.left, self.right = tk.Label(panes), tk.Label(panes)
        self.left.pack(side="left", padx=5)
        self.right.pack(side="left", padx=5)
        tk.Label(window, textvariable=self.stage, font=("Segoe UI", 11)).pack()
        controls = tk.Frame(window)
        controls.pack(pady=4)
        for key, status, text in (
            ("v", "VALID_TARGET", "V — valid target"),
            ("x", "INVALID_NOMINATION", "X — invalid nomination"),
            ("u", "UNCLEAR_TARGET", "U — unclear target"),
        ):
            if simplified and key == "v":
                continue
            if simplified:
                text = (
                    "X — bad nomination" if key == "x" else "U — unclear target display"
                )
            tk.Button(
                controls, text=text, command=lambda s=status: self.nominate(s), padx=12
            ).pack(side="left", padx=4)
            window.bind(key, lambda event, s=status: self.nominate(s))
            window.bind(key.upper(), lambda event, s=status: self.nominate(s))
        classes = tk.Frame(window)
        classes.pack(pady=4)
        self.class_buttons = []
        class_names = (
            (
                "One physical line",
                "Two real structural lines",
                "Not a line-structure target",
                "Genuinely ambiguous",
            )
            if simplified
            else (
                "One physical stroke",
                "Two real structural lines",
                "Other",
                "Ambiguous source",
            )
        )
        for key, text in enumerate(class_names, 1):
            button = tk.Button(
                classes,
                text=f"{key} — {text}",
                command=lambda k=key: self.choose(k),
                padx=8,
                state="disabled",
            )
            button.pack(side="left", padx=4)
            self.class_buttons.append(button)
            window.bind(str(key), lambda event, k=key: self.choose(k))
        extras = tk.Frame(window)
        extras.pack(pady=5)
        for text, callback in (
            ("C — context", self.toggle_context),
            ("D — source support", self.diagnostic),
            ("4x pixel zoom", lambda: self.zoom(4)),
            ("8x pixel zoom", lambda: self.zoom(8)),
        ):
            tk.Button(extras, text=text, command=callback).pack(side="left", padx=4)
        tk.Label(window, textvariable=self.note, wraplength=1100).pack()
        tk.Label(
            window,
            text=(
                "BACKSPACE — undo. Complete 1–4 or X/U; SPACE is disabled. Close to pause/resume."
                if mode == "validation-suspect"
                else "BACKSPACE — undo. Close to pause/resume. Complete V + 1–4 or X/U; SPACE is disabled in suspect review."
                if mode in ("suspect-review", "validation-suspect")
                else "SPACE — skip    BACKSPACE — undo    Each presentation, status, skip and label is saved. Close to pause."
            ),
        ).pack(pady=4)
        tk.Label(
            window,
            text=(
                "For target/UI acceptance only: V then SPACE continues without assigning a physical class."
                if mode == "acceptance"
                else "1–4 confirms source correspondence before saving the class. 3 includes text/digits/glyphs/symbols/graphics/fills."
                if simplified
                else "Formal seed: V then 1–4 labels the physical class. X/U reject the nomination; SPACE leaves it unlabeled."
            ),
        ).pack()
        window.bind("<space>", lambda event: self.skip())
        window.bind("<BackSpace>", lambda event: self.undo())
        window.bind("c", lambda event: self.toggle_context())
        window.bind("d", lambda event: self.diagnostic())
        window.bind("<F4>", lambda event: self.zoom(4))
        window.bind("<F8>", lambda event: self.zoom(8))
        self.advance()

    def completed(self, row):
        sid = row["sample_id"]
        status = self.store.state["nomination_statuses"].get(sid, {}).get("status")
        return (
            sid in self.store.state["labels"]
            or sid in self.store.state["skipped"]
            or status in ("INVALID_NOMINATION", "UNCLEAR_TARGET")
        )

    def advance(self):
        while self.index < len(self.rows) and self.completed(self.rows[self.index]):
            self.index += 1
        self.show()

    def show(self):
        for popup in self.popup_windows:
            if popup.winfo_exists():
                popup.destroy()
        self.popup_windows = []
        self.context_open = False
        if self.index >= len(self.rows):
            self.status.set(
                f"Review complete — {len(self.store.state['nomination_statuses'])} status reviews; "
                f"{len(self.store.state['labels'])} physical classes. No training authorized."
            )
            self.stage.set("Close to pause. BACKSPACE can undo.")
            for button in self.class_buttons:
                button.configure(state="disabled")
            if (
                self.on_complete
                and self.last_completion_version != self.store.state["label_version"]
            ):
                self.last_completion_version = self.store.state["label_version"]
                self.on_complete(self)
            return
        row = self.rows[self.index]
        folder = self.base / row["patch_dir"]
        with Image.open(folder / "gray.png") as image:
            self.gray = image.convert("L")
        self.images = [
            ImageTk.PhotoImage(
                self.gray.resize(
                    (256 * self.display_scale, 256 * self.display_scale),
                    Image.Resampling.NEAREST,
                )
            ),
            ImageTk.PhotoImage(target_overlay(self.gray, row, self.display_scale)),
        ]
        self.left.configure(image=self.images[0])
        self.right.configure(image=self.images[1])
        self.status.set(
            f"Sample {self.index + 1}/{len(self.rows)} — {row['target_kind']} — "
            f"{row['source_drawing_id']}, page {row['source_page']} — {len(self.store.state['labels'])} classes saved"
            + (
                f" — original rank {row['original_rank']}"
                if self.mode in ("suspect-review", "validation-suspect")
                else ""
            )
        )
        self.refresh_stage()
        self.store.present(row, self.index)

    def refresh_stage(self):
        row = self.rows[self.index]
        status = (
            self.store.state["nomination_statuses"]
            .get(row["sample_id"], {})
            .get("status")
        )
        valid = status == "VALID_TARGET"
        if self.mode in ("validation", "validation-suspect"):
            self.stage.set(
                "Choose 1–4 for a clear source-supported target; otherwise X or U"
            )
            for button in self.class_buttons:
                button.configure(state="normal")
            self.note.set(
                "1: one physical structural/rule line. 2: two independent structural boundaries. "
                "3: non-target (including glyph/symbol internal strokes). "
                "4: target is clear, but its physical class is uncertain; keep 4 when context cannot resolve it. "
                "U: target display unclear. Slight misalignment or unequal extents alone do not imply X."
            )
            return
        self.stage.set(
            "Stage 1 — physical class: target confirmed by you"
            if valid
            else "Stage 0 — nomination validity: V / X / U"
        )
        for button in self.class_buttons:
            button.configure(state="normal" if valid else "disabled")
        self.note.set(
            "Text, fills, hatching, graphics and artifacts are Other when validly nominated. "
            "Ambiguous means SOURCE class uncertainty."
            if valid
            else "V: explicit target with defensible source correspondence. X: wrong/unsupported candidate. U: insufficient target display."
        )

    def nominate(self, status):
        if self.index >= len(self.rows):
            return
        try:
            self.store.nominate(self.rows[self.index], status)
        except ValueError as error:
            self.note.set(str(error))
            return
        if status == "VALID_TARGET":
            self.refresh_stage()
        else:
            self.index += 1
            self.advance()

    def choose(self, key):
        if self.index >= len(self.rows):
            return
        try:
            if self.mode in ("validation", "validation-suspect"):
                row = self.rows[self.index]
                if row.get(
                    "explicit_ownership"
                ) == "SOURCE_NATIVE_TEXT_EXCLUSIVE_INK" and key in (1, 2):
                    raise ValueError(
                        "This target has explicit native glyph ownership. Glyph-internal strokes are 3; use X/U if the nominated target is wrong/unclear."
                    )
                status = (
                    self.store.state["nomination_statuses"]
                    .get(row["sample_id"], {})
                    .get("status")
                )
                if status != "VALID_TARGET":
                    self.store.nominate(row, "VALID_TARGET")
            self.store.assign(self.rows[self.index], LABELS[key - 1])
        except ValueError as error:
            self.note.set(str(error))
            return
        self.index += 1
        self.advance()

    def skip(self):
        if self.index >= len(self.rows):
            return
        if self.mode in ("suspect-review", "validation-suspect"):
            self.note.set(
                "Complete 1–4 or X/U (V then 1–4 in the train re-review). Close to pause/resume; no routine skip."
            )
            return
        self.store.skip(self.rows[self.index])
        self.index += 1
        self.advance()

    def undo(self):
        sid = self.store.undo()
        if sid:
            self.index = next(
                i for i, r in enumerate(self.rows) if r["sample_id"] == sid
            )
            self.show()

    def popup(self, title, image):
        top = tk.Toplevel(self.window)
        top.title(f"Sample {self.index + 1}: {title}")
        if self.window.state() == "withdrawn":
            top.withdraw()
        self.popup_windows.append(top)
        photo = ImageTk.PhotoImage(image)
        label = tk.Label(top, image=photo)
        label.image = photo
        label.pack()
        return top

    def toggle_context(self):
        if self.index >= len(self.rows):
            return
        if getattr(self, "context_window", None) and self.context_window.winfo_exists():
            self.context_window.destroy()
            self.context_open = False
            return
        with Image.open(
            self.base / self.rows[self.index]["patch_dir"] / "context.png"
        ) as image:
            context = image.convert("RGB")
        self.context_window = self.popup(
            "Source context — target remains highlighted in main window", context
        )
        self.context_open = True

    def diagnostic(self):
        if self.index >= len(self.rows):
            return
        row = self.rows[self.index]
        with Image.open(self.base / row["patch_dir"] / "support.png") as image:
            diagnostic = image.convert("RGB")
        top = self.popup(
            "Source support: green = nearest ink; distances in source pixels; no class inference",
            diagnostic,
        )
        metrics = row["quality"]["metrics"]
        text = " | ".join(
            f"{prefix}: support {metrics[prefix + '_SOURCE_SUPPORT_RATIO']:.0%}, "
            f"mean {metrics[prefix + '_MEAN_DISTANCE_TO_DARK_INK']:.2f}px, median {metrics[prefix + '_MEDIAN_DISTANCE_TO_DARK_INK']:.2f}px"
            for prefix in ("A", "B")
            if prefix + "_SOURCE_SUPPORT_RATIO" in metrics
        )
        tk.Label(
            top,
            text=text
            or "Explicit ROI contains ink; this does not establish physical class.",
        ).pack()

    def zoom(self, factor):
        if self.index >= len(self.rows):
            return
        row = self.rows[self.index]
        pair = Image.new("RGB", (1024, 512), "white")
        pair.paste(target_zoom(self.gray, row, factor), (0, 0))
        pair.paste(annotated_zoom(self.gray, row, factor), (512, 0))
        self.popup(f"{factor}x pixels — source and exact target overlay", pair)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Two-stage V2 review; V1 remains frozen"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--annotator", default="local-reviewer")
    parser.add_argument("--patch-root", type=Path)
    parser.add_argument(
        "--mode", choices=("acceptance", "formal-seed", "repair-trial"), default="acceptance"
    )
    args = parser.parse_args()
    root = tk.Tk()
    if args.mode=="repair-trial":
        # The limited trial uses separate decisions and no V2 hash/state workflow.
        from trial_labeling import RepairTrialApp
        app=RepairTrialApp(root,args.manifest,args.labels,args.annotator,args.patch_root)
    else:
        app = LabelApp(
            root, args.manifest, args.labels, args.annotator, args.patch_root, args.mode
        )
    root.mainloop()
