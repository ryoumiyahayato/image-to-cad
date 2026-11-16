# Compound source-center preservation — 2026-11-16

This is an additional conservative adoption policy for the opt-in compound
experiment. It is not a general requirement that all image-to-CAD geometry
duplicate continuous pixel-cell boundaries, and it is not product acceptance.

## Why the earlier geometry and topology proof was insufficient

Independent constructed examples exposed two distinct failures while the
earlier boundary-error, source-ledger and ink/paper region-correspondence tests
still passed:

- An observed one-native-pixel black side branch disappeared after a standard
  pen replaced its supporting source. Thinning had not proposed that branch.
- An observed one-native-pixel open white side notch became black. Ink and
  paper component counts, holes and even region overlap identities stayed the
  same, because this notch was connected to the same exterior paper region.

These are observed source features. Exact accounting of which pixels were
retired does not prove that the replacement still draws them. A tolerance of
one native pixel does not by itself preserve a feature that is one pixel wide.

## Shared exporter policy

The policy identifier is `compound-native-center-preservation-v1`. Every
registered compound contract, including the legacy short and explicit long
contracts, must satisfy it before any DXF mutation:

1. Provide the complete registered working and native tile dimensions. An
   inferred source bounding box is insufficient for checking observed paper.
2. For each part, evaluate the actual proposed pen at native pixel centers for
   round, butt and square terminal caps. Every retired source center must be
   covered by that part's own pen; another part cannot conceal a missing member.
3. Compose all pens with the exact retained source. On the complete native tile,
   both missing original black centers and newly covered white centers must be
   zero. The center-state comparison uses no raster expansion tolerance.
4. Still apply all previous continuous source-cell, foreign/protected contact,
   retained-interface, paper/ink region and source-ledger checks. Native-center
   equality alone does not prove continuous boundary or region preservation.

Validation returns the policy identity and per-part, per-cap retirement audit.
Unknown contract versions, hashes and unregistered proposal declarations are
rejected rather than falling through to the older long-path gate.

The native sampler also covers the complete rotated square-cap extent. Its
previous path bounds expanded by only the radius could omit eight centers in
a wide diagonal example (3,936 instead of 3,944). Endpoint-plane comparisons
now use the unnormalized dot product and squared segment length; this avoids
excluding twelve exactly-on-plane centers in a reverse-diagonal flat-cap
example (1,564 instead of 1,576). Twelve independent full-tile distance checks
cover all three caps, coarse diagonal pens and tile-edge cases. These fixes do
not add a geometric tolerance or relax the center-state policy.

The wrapper preflights the record before retiring the parent. A rejected record
therefore leaves the original page content in place. Its processing/cache
identity is now `registered-native-compound-parts-v2-center-preservation`.
Default processing still omits this experimental feature from its payload.

## Native-grid proposal research did not improve the real target cohort

The research compared a native-grid graph with two explicit ownership margins:
`sqrt(2) * scale` native pixels (the old physical margin), and `sqrt(2)` native
pixels (a distinct ownership contract). It then tested inward-only support-cut
refinement while retaining the original 2 mm interior, 12 original sections,
aspect-ratio, pen-width and boundary limits. The final research version added
the same observed native-center conditions described above.

The frozen 19 existing controls, 22 native-grid controls and 8 white-feature
controls were independently checked under both arms: 98 evaluations passed the
fixed safety and clear-positive requirements. These are synthetic/diagnostic
evaluations, not 98 independent real sources. Earlier failed versions and their
minimal black-branch and white-notch counterexamples are preserved.

On the entire preselected A2 cohort, both arms returned zero adopted parts:
24 motivating parents plus the prior positive parent, 50 completed evaluations.
All selected sources reached the method; protection or prior-claim filtering
did not account for the zero result. Source pixels and the original numerical
fit gates were unchanged. The native proposal is therefore not registered in
the production exporter and is not advertised as a coverage improvement.

The previous actual A2 compound DXF had 13 missing black centers and one added
black center under each cap. It remains a historical bounded-fit artifact but
does not qualify under the new policy. There is no historical-positive or
old-cache exception. This does not modify that artifact or rewrite its original
evaluation; it changes eligibility for future automatic source retirement.

## Verification scope

The related processing, CLI, compound export, wrapper, old open-stroke/frame
and source-filled-mark selection passes 210 tests with no failures or skips.
The known short and long contracts each have independent black-branch and
white-notch regression examples that must reject before document mutation.
The r13 complete isolated-stroke implementation remains unchanged.

Full-page reruns and their non-target comparisons are recorded in the current
private evidence delivery. Target-CAD behavior, DWG and human correction effort
require their own evidence. Failed research candidates are not a reason to ask
the user to repeat previously accepted LINE mouse operations.
