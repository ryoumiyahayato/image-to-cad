# Issue 60: numerical replay and independent common acceptance

This isolated branch starts at the frozen A result `2010e6da30b4aa9812ec4730d338edf76fca6b2d`.
The coordinated main baseline is `a2aec1596e82b3a92c7b76f89e9e46e068029e90`.
It is not an integration of issue 59 and must not be merged into main by this task.

## Three independent conclusions

| Layer | Inputs and decision | Cannot establish |
| --- | --- | --- |
| Identity and numerical replay | Verified original source, exact producer identities, complete v1/v2 plans; strictly enumerated source-derived diagnostic intervals | Complete source responsibility, actual saved geometry, or editing correctness |
| Actual saved geometry and edits | Original baseline, actual reopened DXF, independently bound source SHA/ROI/DPI; exact old object/table protection and whole-entity delete/move copies | Correct source interpretation, CAD GUI behavior, or a newly generated full drawing |
| Original-pixel responsibility | Reopened finite DXF geometry and each invocation's own original pixels; original ink, contacts, positive overlaps/gaps, width observations and endpoint residual groups | Unobserved pen history, complete ownership of ambiguous shared ink, unsupported text/curve area or an adoption authorization |

Read [the numerical contract](NUMERICAL_CONTRACT_FROZEN.md), its
[implementation amendment](NUMERICAL_CONTRACT_IMPLEMENTATION_AMENDMENT_1.md),
[the saved geometry contract](SAVED_GEOMETRY_CONTRACT.md) and
[the raw source contract](RAW_SOURCE_AUDIT_CONTRACT.md).
Historical strict FAIL remains FAIL. A separately named legacy diagnostic
compatibility result does not rewrite old evidence or relabel the old DXF.

## Independent common entry point

Set `PYTHONPATH` to this checkout's `cad_photo_to_dxf` directory and supply
verified private files locally. Set source ROI/DPI from the external task
contract, not from the candidate metadata. Set the raw evaluation window to
the selected original-pixel neighborhood; clipping and missing context remain
explicit limitations. Coordinates below are parameter placeholders.

```bash
python experiments/issue60_common_acceptance/run_common_acceptance.py \
  --source original.tiff --baseline prior.dxf \
  --dxf actual-saved.dxf --metadata actual-saved.objects.json \
  --source-roi X0 Y0 X1 Y1 --dpi DPI \
  --audit-roi AX0 AY0 AX1 AY1 \
  --edit-copies --out new-common-audit-directory
```

An optional `--numerical-replay-receipt replay.json` attaches separately
identified numerical evidence. The independent file/pixel subprocesses do
not consume its PASS flag and this wrapper does not claim to rerun that
numerical receipt. Every output directory must be new. The raw source model
reports evidence and unresolved responsibility; it never authorizes adoption
from a limited compatibility result alone. An empty produced target set is
reported as `NO_NEW_TARGET_GEOMETRY`, never as four accepted strokes.

`run_saved_audit.py` also runs independently with `--source`, `--baseline`,
`--dxf`, `--metadata`, externally supplied `--roi`/`--dpi`, `--output-dir`
and optional `--edit-copies`. Its edit writer exits before a separate process
cold-reads each actual file. `run_raw_source_audit.py` accepts `--source`,
`--geometry-json`, a local `--roi`, and a new `--out` file.

## Eight fresh-source probes

`run_eight_raw_probes.py` accepts the coordinator's verified private probe
directory (`FROZEN_VARIANTS.json` plus each individual source image), a
separate unchanged A `--producer-repo`, the exact `--saved-reader` and
`--raw-auditor` source files, and a new `--out` directory. It checks declared
producer file hashes, pins the two independent auditors, then starts fresh
producer and reader processes for every image. Every variant gets its own
graph, owner reconstruction, plan, saved local DXF and original-pixel audit.
It does not reuse a baseline graph.

The 400 by 280 source frame in this runner belongs to the already public
synthetic fixture. It is not a private drawing coordinate list or a producer
adoption rule. Private probe pixels and actual scan coordinates are not
committed. Baseline saved geometry on a variant is an explicitly marked
counterfactual sensitivity observation, never a variant-produced object.

## Evidence and scope

The private report retains original strict failures, all 87 raw numeric
differences, pre-evaluation freezes, every subsequent execution and its source
hashes, actual drawing/edit bytes, individual probe pixels and quantitative
source observations. Public results contain only methods, hashes, counts and
sanitized conclusions. No scan, OCR cache, dedicated font, private link or
experimental drawing belongs in this repository.

Ordinary combined full-region regeneration and CAD GUI/Windows acceptance
remain the coordinator's later common batch after the parallel source
responsibility repair is ready. These file-level audits are not GUI claims.
