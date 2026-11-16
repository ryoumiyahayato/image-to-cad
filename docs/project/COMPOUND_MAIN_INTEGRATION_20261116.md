# Compound source protection integrated with verified main

Date: 2026-11-16. Status: **experimental branch; default disabled; no product or release acceptance**.

## Purpose and scope

The existing accuracy branch introduced an opt-in partial compound-stroke
pipeline and then corrected two export weaknesses: an unknown proof contract
could fall through to the legacy long-part path, and the earlier geometric
error and region-identity checks could still erase a one-pixel black feature or
fill a one-pixel white feature. This integration carries that explicit source
protection forward onto the compatibility fixes already merged in PRs #36 and
#37. It prepares a reviewable application branch without promoting the newer
private proposal experiments.

The application flag remains disabled by default. Rejected parents retain
their original representation. The new global-circle and global-LINE research
generators are **not** installed in this application branch.

## Code and source guarantees

- A registered version/hash is required before compound export. Unknown
  proposal identities do not inherit an older export permission.
- Each part's own actual pen must cover every source center attributed to its
  retirement. Retained source plus emitted pens must preserve all observed
  native black and white centers under round, butt and square caps.
- Complete registered tile dimensions, source ownership, protected and foreign
  content, retained interfaces, continuous ink/paper correspondence and native
  ink/paper correspondence remain mandatory. Corrected square-cap bounds and
  unnormalized endpoint-plane comparisons add no center-state tolerance.
- Actual partial members use ordinary LINE or open LWPOLYLINE, with exact
  residual native-cell HATCH and full hidden source backups. The record states
  that this is a partial representation, with no whole-object movement or
  electrical-connection claim.
- The normal wrapper validates the entire record before retiring source and
  checks contact against previously accepted parents.

The detailed source policy remains in
[compound_native_center_policy.md](../research/compound_native_center_policy.md).

## Integration and static preservation

Local merge `152ebd41886b094249a39a25a1050106a20de492` has the accuracy parent
`b3f557273ee1de7c0c16671ed4929bb552df8f46` and verified main
`5b2a76b716a568bd6dad0a1e1e2a5f80145f0395`. No application source had a textual
merge conflict. Three state documents did; both histories are retained with
the newer accuracy state first.

The inherited static gate identified 92 issues in four newly added compound
files. Ninety-one were same-line statement layout issues; all corresponding
ASTs are identical after expansion. The only remaining change converts the
nested zero-argument `unchanged` lambda into a same-named function returning
the identical tuple. Independent review normalized exactly that node and
confirmed the rest of the AST, literal values, closure references and call
sites remain unchanged. Forty-nine tracked baseline-related Git entries are
identical. No rule suppression, threshold or fixture change was used.

## Complete local validation

Tested local commit: `dd898bbca045e68c0e64e45bd2ab9672398ccaea`.
The published equivalent commit is
`19ec1288932436a15439767a710c130362ac16ac`; both have tree
`6a51eeea53e256cbf605e1a7ba58ac1db601b2a4`.

The full run used Python 3.11.18 / pytest 8.4.2 in an isolated checkout, with
network syscalls blocked before runtime imports and Qt offscreen. All 503
recorded Python/source/check files were unchanged before and after the run;
the inventory SHA-256 is
`21ad88105d5ccc40e01557179d4e2fa97cc2e8a860b64a8d6f32325f521e611b`.

| Gate | Actual result |
|---|---|
| Complete application unit suite | 1,787 passed; 26 skipped; 0 failed/errors |
| Independent drafting suite | 88 passed; 0 skipped/failed/errors |
| Representative behavior preservation | EXACT |
| Required application and drafting Ruff | Passed |
| Required incremental mypy | Passed |
| Application and drafting compile checks | Passed |
| Repository hygiene | 0 findings |

The skips are 18 absent TrueType fixture-font cases and eight unprepared P2C
candidate-resource cases. They do not include the Qt singleton regression.
The recorded run is a local Linux Python 3.11 result; branch-specific online
Windows, FreeCAD or other CI must be reported from their own actual runs.

## Accuracy and interaction boundary

The previously rejected A2 compound candidate stays rejected by the corrected
source policy. The source-protection commit's complete A2, ENV and HABS
saved-DXF comparisons preserved existing entities and editable text, with no
new compound adoption. Those results belong to that earlier exact source
inventory; this integration does not relabel them as new full-page runs.

New proposal research separately freezes its algorithms and checks all source
oracles before any application integration. Synthetic recovery, unchanged
source accounting, compatibility tests and parseable DXF are distinct from
real-page improvement, target-CAD interaction, DWG roundtrips and human repair
effort. Existing accepted r13 mouse checks do not need repetition merely
because this branch has been integrated.
