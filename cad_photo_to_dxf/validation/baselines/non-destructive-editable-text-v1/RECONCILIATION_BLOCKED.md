# P1B-R reconciliation blocked before baseline creation

Recorded: 2026-07-31

Status: **P1B-R blocked — protected phase-12 tag ref is absent.**

## Repository facts

- Target branch: `fix/non-destructive-editable-text`
- Target/base HEAD: `80be85aba985e457bc7bff1e9ece49f50e7a46d2`
- Intended editable-text baseline source: `5f7846e00b41913c003f178558a110e6475c0ee0`
- Recorded historical phase-12 commit: `6f5f69329aabf0bd3a7eda84baf66eb1959bdcba`
- Required protected tag name: `baseline/phase12-final-acceptance-2026-07-30`

## Blocking precondition

A full-tag checkout with `fetch-tags: true` did not produce the required tag ref. Both `git rev-list -n 1 baseline/phase12-final-acceptance-2026-07-30` and the GitHub contents API using that ref failed because the ref does not exist remotely.

The historical commit itself exists. The legacy real-regression manifest at the recorded phase-12 commit and at the current target HEAD has the same Git blob SHA:

`533ae15afcef24dd4444f9acc3d504bbd94d9c87`

This proves the inspected manifest file was not changed between those two refs, but it does not prove preservation of a remote tag that is absent.

## Contract handling

The task explicitly prohibits creating, recreating, moving, deleting, or replacing the phase-12 tag. Creating the missing ref inside P1B-R would therefore violate the authorization boundary. The reconciliation workflow stopped before:

- A → B → C real-document replay;
- new contract baseline generation;
- partition-hash baseline recording;
- baseline-selection implementation;
- production or test changes;
- governance completion;
- P1B-3 rerun;
- P2 work.

Temporary payload files and the temporary workflow were removed by resetting this Draft PR branch to the authorized base before committing this blocker record.

## Required decision

A separate explicit authorization is required for exactly one of these actions:

1. restore/create the missing phase-12 tag at the recorded commit; or
2. revise the protection contract to pin the historical commit and manifest blob without requiring an existing tag ref.

Until that decision is made, PR #29 must remain Draft and unmerged. PR #28 remains the separate P1B-3 failure-evidence PR and must also remain Draft and unmerged.
