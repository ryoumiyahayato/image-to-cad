# LibreCAD manual UAT package not ready

Do not use this directory as an approved P1B manual acceptance package.

P1B-3 automated validation is blocked by the mandatory formal real-document regression gate. The committed expectations still encode the superseded `replacement_safe` downgrade policy, while current approved behavior emits eligible candidates as editable native DXF `TEXT`.

Until a separately authorized baseline/acceptance-contract reconciliation is completed and P1B-3 is rerun successfully:

- no before/after DXF pair is approved for user acceptance;
- no screenshot set is approved;
- no page checklist represents a passed automated prerequisite;
- project status must remain `P1B automated validation blocked`, not `Awaiting user LibreCAD UAT`.
