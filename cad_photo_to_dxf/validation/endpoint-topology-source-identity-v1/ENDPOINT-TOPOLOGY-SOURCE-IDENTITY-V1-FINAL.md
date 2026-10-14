# Endpoint / Topology Source Identity Evidence V1

Status: `COMPLETE` (bounded DEV evidence contract; production semantics unchanged)

## Outcome

The new DEV-only contract separates endpoint topology from pair admission and returns exactly `SOURCE_IDENTITY_SUPPORTED`, `SOURCE_IDENTITY_REJECTED`, or `SOURCE_IDENTITY_AMBIGUOUS`. It consumes the existing `SourceStrokeInstance` and `CoincidentStrokeGroup` representation without changing multiplicity architecture. It does not mutate geometry, use semantic object labels, or infer that collinearity or a small gap proves one source identity.

Endpoint profiles measure axial support into and beyond an endpoint, both transverse directions, termination strength, corner/T-junction/crossing evidence, connected-component identity, local multiplicity, and competing preserved stroke IDs. A crossing requires the axial ridge to continue; a corner or T-junction requires it to stop. Weak plain endpoints remain ambiguous unless confirmed source identity or independent endpoint structure is available.

## Required questions

- A. Can endpoint topology distinguish crossing from termination? **YES** in deterministic endpoint-local synthetic evidence; **PARTIAL** in frozen real records whose old scalar features conflate them.
- B. Can independent endpoint sets provide negative source-identity evidence? **YES**, when the endpoint sets are preserved as confirmed distinct identities or carry strong termination topology.
- C. Can preserved multiplicity provide negative source-identity evidence? **YES**, through distinct confirmed member IDs, competing group membership, and local multiplicity change.
- D. Can valid dropout continuation still survive? **YES**. Shared confirmed identity is supported; detector-only weak damage stays ambiguous and continues under existing policy.
- E. Can nested coincident edges remain distinct? **YES**.
- F. Can pair identity be rejected without semantic object labels? **YES** for strong generic topology or confirmed distinct source instances.
- G. Are CASE15 and CASE16 rejected by generic evidence? **NO**. Both remain `AMBIGUOUS` because their frozen records lack endpoint-local crossing/termination profiles and confirmed pair-level source-instance membership. Human labels were not converted into code evidence.
- H. Is pair-level identity rejection safe enough to affect V2 eligibility? **NO**. The synthetic contract is precise, but the frozen real records do not expose the required evidence. No admission wiring or V2 artifact was created.

## Admission policy

- `SUPPORTED`: continue normal admission.
- `REJECTED`: the contract exposes `REJECT_IN_DEV_ADMISSION`, but no frozen-path wiring occurs in this task.
- `AMBIGUOUS`: continue the existing review/admission policy; absence of positive identity is not rejection.

This prevents a blanket `not SUPPORTED => reject` rule. The three known-valid pair controls remain unrejected (`3 / 3`, false pair rejections `0`).

## Bounded real-case audit

Twelve existing DEV cases were audited: CASE15/16, three known-valid continuation pairs, three known-rejected pair controls, two crossing-valid controls (one overlaps the valid-pair set), and three multiplicity/boundary controls. No source document was mined or acquired. The audit deliberately records `AMBIGUOUS` where the existing frozen artifact has only aggregate scalar evidence.

CASE15 has separate raw ancestor IDs but no frozen endpoint-local topology or independently confirmed physical source IDs. CASE16 additionally has the previously documented upstream alternative-axis loss. Neither is safely rejected by the new generic contract from the currently retained inputs.

## Synthetic topology matrix

All 12 cases A-L pass. Crossing continuity is separated from T/corner termination. Exact and 1-3 px coincident instances retain distinct IDs. A damaged detector-only line remains ambiguous rather than falsely rejected. A true thick stroke stays one source instance with two observations only after independent filled-band equivalence evidence.

## Eligibility and governance

No pair rejection was wired because real-case evidence coverage is insufficient. The frozen-147/V1 artifact is read and verified at 147 pool members and 122 eligible members; membership is unchanged, so no V2 files are created. SOURCE_GAP_REVIEW_V1_2 remains `PAUSED`. Production reconstruction, rendering, straight validity, span, axis, text/glyph guards, and multiplicity architecture are unchanged.

## Structured artifacts

- `endpoint-topology-profiles.json`: `4d126ce3ff2ec790fe83952ec7bd07869e28ca1adcb86d9a0965ca80c21cdcbf`
- `pair-source-identity-evidence.json`: `45d441679e8cad0b9d68154eec54a4dfa3478271fbb5ca4893b2579324ac3573`
- `synthetic-topology-results.json`: `39a02bc33062e11f61d1bb5de89da6310938607913283bbb082de5d64819d3cd`
- `bounded-real-case-audit.json`: `b7152db84a43e7a93d627e701d5e47b75fc7b9e56c6de18e24c61736ae65cfb0`

## Tests

Focused tests cover dropout continuation, crossing continuation, T-junction and corner termination, distinct endpoint pairs, nested exact coincidence, 1/2/3 px near-coincidence, damaged line ambiguity, thick-stroke identity, competing identity/multiplicity context, ambiguity policy, and absence of candidate/semantic exceptions. Existing multiplicity tests are replayed because the new layer consumes that API.

NEXT_TARGET: `CAPTURE_ENDPOINT_LOCAL_TOPOLOGY_AND_CONFIRMED_SOURCE_INSTANCE_MEMBERSHIP_FOR_FROZEN_PAIR_RECORDS_BEFORE_DEV_ADMISSION_WIRING`
