"""Read saved output once per case; child-process deadlines bound Qt rendering."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.quality.fidelity import Limits, inspect_case, write_json  # noqa: E402
from app.quality.fidelity_report import case_html, index_html  # noqa: E402


def peak_memory_bytes():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t)
                for n in [
                    "PeakWorkingSetSize",
                    "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage",
                    "PagefileUsage",
                    "PeakPagefileUsage",
                ]
            ]

        counter = Counters()
        counter.cb = ctypes.sizeof(counter)
        kernel = ctypes.WinDLL("kernel32")
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        if psapi.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counter), counter.cb
        ):
            return counter.PeakWorkingSetSize
        return None
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
        1 if sys.platform == "darwin" else 1024
    )


def resolve_case(case, base):
    value = json.loads(json.dumps(case))

    def full(path):
        p = Path(path)
        return str((base / p).resolve()) if not p.is_absolute() else str(p.resolve())

    for key in ["pdf", "dxf", "trace"]:
        if value.get(key):
            value[key] = full(value[key])
    if value.get("coordinate"):
        value["coordinate"]["reference"] = full(value["coordinate"]["reference"])
    for label in value.get("labels", []):
        label["evidence"] = full(label["evidence"])
        if label.get("before_dxf"):
            label["before_dxf"] = full(label["before_dxf"])
    if not re.fullmatch("[a-zA-Z0-9_-]{1,64}", value["id"]):
        raise ValueError("Case id must be a plain directory name")
    return value


def main():
    parser = argparse.ArgumentParser(description="只读整页质量检查；不运行OCR或修改CAD")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--dpi", type=int, default=240)
    parser.add_argument("--dxf", type=Path)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--coordinate-reference", type=Path)
    parser.add_argument("--size-px", type=int, nargs=2)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--total-seconds", type=float, default=300)
    parser.add_argument("--worker-case", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    started = perf_counter()
    limits = Limits(seconds=args.seconds)
    if args.worker_case:
        case = json.loads(args.worker_case.read_text(encoding="utf-8"))
        result = inspect_case(case, args.output, limits)
        result["peak_working_set_bytes"] = peak_memory_bytes()
        case_html(result, args.output)
        result["output_bytes"] = sum(
            p.stat().st_size for p in args.output.rglob("*") if p.is_file()
        )
        write_json(args.output / "report.json", result)
        return 0
    if args.manifest:
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
        if payload.get("format") != "cad-fidelity-manifest-v1":
            parser.error("Unsupported manifest format")
        cases = [
            resolve_case(c, args.manifest.resolve().parent) for c in payload["cases"]
        ]
    else:
        if not args.pdf or not args.dxf:
            parser.error("--pdf and --dxf required without --manifest")
        cases = [
            resolve_case(
                dict(
                    id="page",
                    pdf=str(args.pdf),
                    dxf=str(args.dxf),
                    page=args.page,
                    dpi=args.dpi,
                    trace=str(args.trace) if args.trace else None,
                    coordinate=dict(
                        scope="FULL_PAGE",
                        reference=str(args.coordinate_reference),
                        size_px=args.size_px,
                    )
                    if args.coordinate_reference
                    else None,
                ),
                Path.cwd(),
            )
        ]
    if not 1 <= len(cases) <= 3 or len({c["id"] for c in cases}) != len(cases):
        parser.error("Use 1..3 distinct saved physical pages")
    output = args.output.resolve()
    for case in cases:
        inputs = [case[k] for k in ("pdf", "dxf", "trace") if case.get(k)]
        inputs += [case["coordinate"]["reference"]] if case.get("coordinate") else []
        inputs += [
            label[k]
            for label in case.get("labels", [])
            for k in ("evidence", "before_dxf")
            if label.get(k)
        ]
        if any(Path(p).resolve().is_relative_to(output) for p in inputs):
            parser.error(
                "Output may not contain or overwrite any input or evidence file"
            )
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for case in cases:
        destination = output / case["id"]
        destination.mkdir(exist_ok=True)
        job = destination / "inspection-input.json"
        write_json(job, case)
        remaining = args.total_seconds - (perf_counter() - started)
        try:
            if remaining <= 0:
                raise TimeoutError("Overall deadline exhausted")
            command = [
                sys.executable,
                "-X",
                "utf8",
                str(Path(__file__).resolve()),
                "--worker-case",
                str(job),
                "--output",
                str(destination),
                "--seconds",
                str(args.seconds),
            ]
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=min(remaining, args.seconds),
            )
            (destination / "run.log").write_text(
                process.stdout + process.stderr, encoding="utf-8"
            )
            if process.returncode:
                raise RuntimeError(
                    process.stderr[-3000:] or f"Worker exit {process.returncode}"
                )
            result = json.loads(
                (destination / "report.json").read_text(encoding="utf-8")
            )
        except (subprocess.TimeoutExpired, TimeoutError, RuntimeError) as exc:
            result = dict(
                name=case["id"],
                status="FAILED_OR_BUDGET_EXCEEDED",
                reason=str(exc),
                production_CAD_change="NONE",
            )
            write_json(destination / "failure.json", result)
        results.append(result)
        print(case["id"], result["status"], flush=True)
    index_html(results, output)
    write_json(
        output / "inspection-summary.json",
        dict(
            format="cad-fidelity-summary-v1",
            results=results,
            total_seconds=perf_counter() - started,
            production_CAD_change="NONE",
        ),
    )
    return int(any(r["status"] != "COMPLETED" for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
