# Agent operating protocol

The user's current task determines the working mode. A request to implement,
fix, validate, merge or clean up authorizes the necessary work within that scope.
Do not turn an execution request into a read-only audit or stop after a plan.
Existing authorization persists across steps. Ask only for an unresolved,
material decision or an action outside the authorized scope.

## Evidence and acceptance

Keep these evidence classes distinct:

- **Code fact:** observed source, parameter, entity, commit or branch state.
- **Automated-test fact:** actual test, cold read, render, CI or audit result.
- **Agent GUI fact:** actions the agent actually performed in the named CAD,
  with saved files, screenshots and reopen evidence.
- **Engineer UAT fact:** a real engineer's work, including missing-content
  repair, final checks and measured time. Agent samples do not replace it.
- **Hypothesis:** an explanation still requiring source or execution evidence.

The product contract is [native editable object reconstruction](NATIVE_OBJECT_PRODUCT_BASELINE_20261120.md).
Publishing code or merging maintenance does not change LOCAL_NO_GO to GO.
Private experiments, development branches and public main have separate scope.

## Execution

1. Read the current remote main, task branch, HEAD, open PRs and relevant source.
2. Preserve unknown work, original inputs, historical failures and recovery refs.
3. Work on isolated branches; split maintenance and feature changes into coherent
   commits. Use the PR explicitly designated by the user as the merge entry.
4. Continue ordinary path, empty-geometry and export fixes within the current
   task. Do not ask for permission again for already authorized work.
5. Bind each candidate, saved DXF and review to its source, configuration and
   code revision. A changed DXF cannot inherit the original file's approval.
6. Run affected tests and required repository gates. Preserve real failed runs;
   avoid unrelated refits, whole-page work and repeated recognition inputs.
7. Serialize expensive conversion tasks and monitor the worker and OCR children.
   Set a task-appropriate budget; do not apply an old local experiment limit to
   every full-region conversion. Save valid checkpoints without overwriting
   previous correct outputs.
8. Report actual pushes, remote CI, merge state and remaining blockers. A local
   commit or patch is not a successful push. Do not rewrite main or protected refs.
9. Update current status and tasks without rewriting dated historical conclusions.
   A preserved snapshot records what existed then; recovery checks ask whether
   that commit remains reachable now. Normal main advancement is not data loss.

Use the six-field task report when requested: task/status; actual changes;
actual artifacts; reverse check and observation; remaining issues; next task.

## Audit and suggestion requests

When the user asks only for an audit or proposal, stay within that read-only
scope. Identify facts, uncertainties, conflicting evidence and a concrete next
step. Do not apply that restriction to a separate explicit execution request.

## Source and CAD constraints

- No page, filename, coordinate, object-ID or expected-string answers in the
  recognizer. Do not lower confidence or source gates to inflate accepted counts.
- Preserve real short strokes, gaps, holes, text suffixes and neighboring objects.
  A connected source component may contain several independent editable paths.
- Keep editable text as TEXT/MTEXT, not outlines. BLOCK grouping alone does not
  prove complete or clean members.
- Check actual saved output both ways: output to source and source to output.
  Distinguish raster diagnostics from engineering completeness and editability.
- Inspect CAD compatibility by actual effect on content, units, transforms,
  rendering and edits. Record changed metadata separately without ignoring it.
- DPI establishes paper units only. Engineering dimensions need scale evidence.
- No real engineer: mark engineer testing NOT_RUN and prepare the usable trial.
  Do not equate a few scripted or GUI edits with repair time at equal final quality.

## Public repository and recovery

Never add private drawings, secrets, OCR caches, full experimental ZIPs, model
binaries or unlicensed fonts to the public repository. Publish reviewed code,
resource acquisition/checksum instructions and lawful minimal validation only.
External paid/model services or private-source transfer need authorization for
that data and destination. Existing local OCR can run within the task budget.

Before retiring a unique research branch, create and read back its remote
recovery reference. If that cannot be demonstrated, retain the branch and state
why. Use the historical ledger plus current reachability; do not mutate a frozen
record to disguise loss. No force-pushing main, history rewriting or formal
Release without the corresponding explicit authorization and acceptance.
