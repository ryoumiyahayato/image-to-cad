# Issue 63 — interrupted development checkpoint (2026-11-27)

**Status: ENVIRONMENT_BLOCKED / WIP. Issue 63 is not completed.**

This checkpoint preserves development work after the execution environment
reported `unavailable` and local tools failed with
`exec-server transport disconnected/closed`. It is not a validated method
release, a new source-stage result, or an accepted CAD output.

## 1. Provenance and boundaries

- Task: [Issue 63](https://github.com/ryoumiyahayato/image-to-cad/issues/63).
- Base result commit: `052a70641c9880ecf9a2aa7d969a2da0d0a444ca`.
- Base tree: `effbe515b250fb1cab7bf4d8534b0d0aad44dcae`.
- Main re-read before this checkpoint: `a2aec1596e82b3a92c7b76f89e9e46e068029e90`.
- No main merge, ordinary-flow replacement, GUI, Windows or release action.
- The still-active Issue 61 implementation was not modified or restarted.
- The original Issue 62 method and result files remain historical evidence.

The Git objects in this checkpoint were recovered through the GitHub connector.
The junction/audit/runner files were reconstructed from the successful local
write parameters (or the exact base file plus the successful deterministic
patches). Each recovered blob was read back. The local filesystem could not
be reread after the outage, so **the checkpoint is not asserted to be the
exact tree of a completed local execution**.

The bounded-width kernel is a separately identified **unexecuted draft**:
its local apply operation did not return a success receipt before the executor
became unavailable and was terminated. Its authored source was preserved as
a Git blob and read back, without claiming a local import or test.

## 2. Actual materials obtained and checked

The following already-existing private archives were obtained before the
outage. Archive byte sizes and SHA-256, ZIP CRCs, and individual payload
identities were checked. No source material or private access link is included
in this public checkpoint.

| Existing evidence archive | Bytes | SHA-256 |
| --- | ---: | --- |
| Coordinator Issue 62 review | 3,057,078 | `6110cd2f77fbdd450544806ea98b7f767c25a9f113e9b29412da93b12097ded8` |
| Complete Issue 62 evidence | 28,943,838 | `8e19e30926320a4280820c9f8a9acd23540af504b7f09111a4f8e8b48a88c26a` |

The coordinator archive has 54 ZIP members / 53 payload files. The previous
complete archive has 633 members / 632 payload files. The restored complete
circle source object is present and bound in the original coordinator receipt.
Original TIFF, valid baseline DXF, prior plan and the unchanged eight probe
inputs were available. This task is **not MATERIAL_BLOCKED**.

The following are findings from that checked coordinator material, not new
Issue 63 executions:

- The coordinator reproduced all 16 strict source fields and all 29 official
  saved-audit fields, with complete protection of the previous 436 formal
  objects and resources. Historical adoption remained zero.
- Its diagnostic shared-vertex construction achieved 3/3 exact saved contacts
  and zero finite-centerline white crossings while bypassing the old core
  permission gate. That remains diagnostic, not adoption.
- Two candidate contacts are in original black ink but outside the skeleton
  core's closed pixel cells. A source-supported domain is required.
- Fresh existing acyclic direction proof gives about 17.19 degrees, with
  approximately 72.81 / 53.80 degree competition margins under unchanged
  20 / 18 degree gates.
- The relevant small cyclic core has a fully black 4-by-4 raw patch. Keeping
  all original adjacency and proving the arms is still required.
- A remote prior failure must be retained, while any exclusion from the local
  proof needs an independently checked finite influence certificate.
- Two lower disputed cells need roughly 0.54–0.65 pixels more half-width than
  the old constant-body upper bound. This is not a floating-point microgap.
- The recovered circle's historical source verifier passed on 480 ring
  pixels, 458 samples and four contact ports. That is not a new exact
  finite-arc/coherent-union approval.

## 3. Code and contract checkpoint

| Path | Actual checkpoint status |
| --- | --- |
| `docs/native/ISSUE63_JUNCTION_CONTRACT.md` | Written before any new real adoption run; frozen development contract |
| `docs/native/ISSUE63_INDEPENDENT_SOURCE_CONTRACT.md` | Written contract; much of its intended interface remains unimplemented |
| `docs/native/ISSUE63_BOUNDED_SOURCE_CONTRACT_20261127.md` | Three equality rules and bounded-field family fixed before real runs |
| `cad_photo_to_dxf/app/native_objects/finite_source_junction.py` | New source-domain/shared-vertex/transform module; limited development checks only |
| `cad_photo_to_dxf/app/native_objects/finite_component_source_audit.py` | Adds two v2 helpers; original v1 entry is unchanged and helpers are not dispatched |
| `cad_photo_to_dxf/app/native_objects/bounded_stroke_field.py` | Unexecuted draft of rational field membership and parameter search |
| `experiments/issue63_bounded_source/run_source_stage.py` | Incomplete, unexecuted local stage adapter |
| `experiments/issue63_bounded_source/run_probes.py` | Incomplete, unexecuted eight-probe adapter |

New proposed interfaces are explicitly versioned:

- Plan: `source-attached-stroke-graph-plan-v4-bounded-source`.
- Component: `source-finite-component-responsibility-v2-bounded-field`.
- The actual graph planner in this checkpoint still has its old entry.
  **The new v4 flow is not integrated and must not be represented as runnable
  or final.**
- Intended component seam:
  `audit_bounded_bodies(source, graph, rows, owner=None, cores=None, prior_objects=None, circle_source_objects=None)`.
  Its module is not yet implemented.
- Every body's original constant-width receipt is to remain in `width`;
  new receipts go in `bounded_width_field`. They are separate identities.
- Shared construction changes only new candidate hosts. Old formal objects
  retain exact identities and geometry.

The bounded-field draft chooses a constant model where all independent
sections intersect. Otherwise, if every individual section is supported,
all section centers become knots of one continuous squared-width field with
one shared alpha parameter per body. It uses exact rational quadratic
membership, a predeclared 48-bit parameter search, and exact outer-envelope
counterexamples. A failed finite search is PENDING, not proof of scan
ambiguity. CIRCLE integration is not in that draft.

## 4. What was actually exercised

The junction module passed Ruff and limited development smoke checks before
the outage:

1. An existing three-body axial synthetic source produced two shared
   insertions under the new constructor.
2. A separately drawn oblique host with two guests produced two shared
   insertions outside the skeleton-core cells, with raw black/arm permission.
3. An in-memory exact calculation confirmed that ordinary coordinate
   transformation can make two implicit oblique contacts nonzero.

These checks did **not** save, close and independently reopen a DXF. They
are not a completed automated control suite and do not prove the real three
contacts. White-hole/fourth-arm source-graph observations were prepared, but
the full new API rejection tests were not completed.

| Required Issue 63 result | Status |
| --- | --- |
| Complete new positive/negative controls | NOT_RUN |
| Original eight probes under the final new version | NOT_RUN |
| Real new source-stage and per-stroke outcome | NOT_RUN |
| New actual saved diagnostic DXF / independent source audit | NOT_RUN |
| New actual saved exact contacts and white-gap protection | NOT_RUN |
| New-version 436 / 48 REVIEW / 55-block full protection | NOT_RUN |
| Actual new adoption count | NOT_ESTABLISHED |
| New real-object independent delete/move/save/cold read | NOT_RUN; no new adoption decision exists |
| Joint ordinary-flow integration with Issue 61 | NOT_RUN |
| GUI / Windows / EXE / engineer timing | NOT_RUN |

The historical zero-adoption result must not be renamed as a new Issue 63
zero-adoption result. No new diagnostic output or new valid main drawing is
delivered by this checkpoint.

## 5. Concrete incomplete work and review findings

The following are known before any resume; do not treat the contracts as
evidence that these implementations exist:

- Add the finite-prior-port module and fresh independent certificate replay.
  Bind full actual old geometry and historical source identity, enumerate
  finite entries/exits, and retain every actually read direction/width/
  continuation dependency. Never isolate a defect just because it failed.
- Add actual saved native-mm and CIRCLE center/radius fields to the reader.
  The attempted reader patch returned transport failure and is absent.
- Add exact finite-circle type/source/radial-width proofs and common-union
  queries. Do not substitute a chord or the historical sampled PASS.
- Finish the new bounded component, graph schema dispatch, source-object
  bindings, kernel hashes and replay of every plan field.
- Review `_direction_table_v2`: existing direction exploration uses a
  representative internal core route. If a dependency traverses a cyclic
  core, prove agreement over all relevant original routes or remain PENDING.
  Record every read edge/cell even on failed or truncated searches.
- Review junction host lookup: reject an explicitly supplied but unresolved
  host ID instead of silently using a valid numeric index. Normalize public
  receipts containing NumPy values before JSON serialization.
- Add the discriminating control suite, particularly oblique multi-guest
  saved contacts, one-ULP false points, actual white gaps, cyclic/white-hole
  cores, finite-port dependence and exact circle corruption.
- Complete probe pending-context sidecars, fresh-process replay of pending
  outputs, complete manifest and entry snapshots.
- Verify actual saved baseline entity tags before relying on the runner's
  pre-save TagCollector mapping. Preserve every original value; no epsilon
  or broad tag filtering may hide changed non-target objects.

## 6. Resume order

1. Restore an executable environment; inspect the preserved local worktree
   if it remains available. Compare it with this recovery checkpoint before
   applying edits. Do not overwrite unknown or parallel work.
2. Finish and review the missing modules and actual planner/reader seams.
   Resolve the explicit WIP findings above, then add the minimal meaningful
   controls. No new OCR or full-page recognition is needed.
3. Freeze an actual executable commit and tree. Run the new real local
   stage, preserve its actual failures, save the diagnostic DXF and run the
   independent cold audit. Run the unchanged eight source probes with fresh
   graph/owner/plan instances and the new controls.
4. If real objects are adopted, perform each independent delete/move/
   save/exit/cold-read test while protecting every non-target member. If the
   actual completed run adopts zero, report N/A editing and its concrete
   new-model counterexample rather than this environment outage.
5. Re-read Issue 61's final frozen interface before any joint run. Its newest
   comment, read again during checkpoint publication, reports method commit
   `9d102cfe6064cf8d68fc03099ea9ef457650fce6` (local execution `c22de675`,
   same tree `02a93e0637ab15b06bbf718aedba000ea7f4002d`). That task reports
   partial validated fixes, then exit 137 during new source-checkpoint
   construction and the unavailable environment. It has no new ordinary
   DXF or final joint acceptance. See its recovery result commit
   `f22b837df8a1465e09ff5cd51945c144e8af712a`; do not revert to its older
   in-progress interface as if it were the latest result.
6. Deliver the private new evidence, rerun commands, exact execution/public
   identities and per-stroke table; comment with the actual final result.

This checkpoint is a recoverable implementation interruption, not an
algorithmic failure verdict and not Issue 63 acceptance.
