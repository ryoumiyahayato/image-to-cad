# Project checkpoint

Recorded: 2026-07-31

- Branch: `fix/non-destructive-editable-text`
- P1B start: `5f7846e00b41913c003f178558a110e6475c0ee0`
- Phase-12 baseline tag remains untouched.
- Local user worktree was not opened; connector/Actions isolation used.

## P1B-1

Canonical `_line_placement_from_quad` now uses the finite positive raw width factor directly. The historical `0.72` value remains only as a deprecated audit reference. Rotation is normalized to `[0, 360)`. The narrow-box test now requires exact target-width fitting rather than deliberate overflow; cardinal and arbitrary rotation coverage is expanded.

## Next safe operation

Inspect CI and diff, then unify reachable legacy TEXT creators in P1B-2. Do not begin P2.
