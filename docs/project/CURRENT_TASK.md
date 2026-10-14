# Current task

2026-10-14: close PR #34's Linux native-exit fault and compact-snapshot discrepancy, then synchronize the verified Image to CAD 0.3.0-dev product to GitHub main without rewriting history.

P10-B and new feature work are paused for this task. The source is the actual instrumented-e03 tree, including P1–P9 and completed P10-A work. Retain recovery points and the immutable historical snapshot; exclude raw libraries/caches/private files. Merge only after the final head passes all necessary CI and the bounded file-scope audit. Stop after synchronization; do not automatically start P10-B.

Current product facts are in PROJECT_STATUS.md. This record supersedes the old July P1B task queue; historical decisions and evidence remain unchanged.
