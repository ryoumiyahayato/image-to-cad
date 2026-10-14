# Agent operating protocol

## Evidence taxonomy

Every report must label statements as one of:

- **Code fact:** directly observed function, parameter, entity type, file, commit, or branch state.
- **Automated-test fact:** test, audit, count, CI, or validation artifact result.
- **User UAT fact:** direct LibreCAD observation or operation reported by the user.
- **Hypothesis:** a possible explanation requiring verification.

A hypothesis must never be written as a confirmed root cause.

## Audit mode

Default behavior is read-only.

An audit must:

1. identify repository, branch, HEAD, PR, and exact scope;
2. preserve existing user changes and baselines;
3. separate all four evidence classes;
4. record evidence paths and commands;
5. compare automated evidence with user UAT;
6. list conflicts rather than resolving them by assertion;
7. avoid threshold, baseline, and production changes;
8. avoid claiming an untested issue is solved;
9. produce one prioritized next-task recommendation;
10. stop without executing that recommendation.

Fixed audit output:

1. confirmed facts;
2. unconfirmed issues;
3. user UAT evidence;
4. automated evidence;
5. evidence conflicts;
6. root-cause candidates;
7. contracts that may not change;
8. one recommended next task;
9. risks;
10. stop condition.

## Suggestion mode

A suggestion ranks work by user value, risk, prerequisites, and cost.

A suggestion must:

- recommend only one next task;
- state why it is the correct task now;
- state why other work is deferred;
- define exact modification boundaries;
- define acceptance evidence and user-validation needs;
- define regression risks;
- define an explicit stop condition;
- not execute the recommendation automatically.

Fixed suggestion output:

1. highest-value problem;
2. priority rationale;
3. prerequisites;
4. modification boundary;
5. acceptance method;
6. regression risk;
7. user validation requirement;
8. do/defer recommendation;
9. tasks that must not run concurrently.

## Execution mode

Execution requires an explicit user instruction.

Rules:

- one major issue per task;
- one isolated conventional commit per task;
- use a recoverable checkpoint, normally within 20–45 minutes;
- before modification, re-read remote branch/HEAD and verify scope;
- do not use a worktree containing unknown user changes;
- do not add large generated DXF/PDF/PNG/log/package artifacts unless the task explicitly requires a reviewed retention set;
- do not broaden scope when another issue is discovered; record it in the issue register;
- run only tests relevant to the authorized phase plus required regression gates;
- update [CURRENT_TASK.md](CURRENT_TASK.md), [NEXT_TASK.md](NEXT_TASK.md), and [CHECKPOINT.md](CHECKPOINT.md);
- stop at the declared stop condition.

## Conflict handling

When code or automated evidence conflicts with user UAT:

1. preserve both statements;
2. mark the automated contract and human contract separately;
3. identify what the current metric does and does not measure;
4. add or update an issue;
5. propose a focused reproducer or metric;
6. do not lower thresholds, change baselines, or declare success during audit;
7. use the user as final product acceptor.

## Prohibited shortcuts

- full-page line repair;
- page/filename/coordinate/text-content hard-coding;
- lowering OCR confidence to inflate text count;
- replacing editable text with outlines;
- using diagnostic color to alter semantics;
- treating average results as per-page acceptance;
- claiming another agent or automated report substitutes for user approval;
- beginning the next roadmap phase without explicit authorization.
