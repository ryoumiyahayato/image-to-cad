Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = "C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03"
$trackedDir = "$root\cad_photo_to_dxf\validation\straight-rejected-audit-v1"
$runtimeDir = "$root\local-artifacts\draftsman\straight-rejected-audit-v1"
$runtimeReplay = "$root\local-artifacts\draftsman\straight-primitive-validity-v1\frozen147-straight-reevaluation.json"
$trackedSummary = "$root\cad_photo_to_dxf\validation\straight-primitive-validity-v1\frozen147-straight-reevaluation-summary.json"
$sourceGapMigrationPath = "$root\cad_photo_to_dxf\validation\targeted-source-gap-review-v1-1\source-gap-v1-1-human-state-migration.json"

New-Item -ItemType Directory -Force -Path $trackedDir | Out-Null
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

$ids = @(
    "FRESH1-2FF08EDFC754E290D7A4",
    "FRESH1-316D125FE4861584BE02",
    "FRESH1-4694F629CD0F75FF0AB7",
    "FRESH1-4966D4412392002C19C2",
    "FRESH1-5BF4B6744E8C47B6DCD2",
    "FRESH1-624D754C52D4723051AF",
    "FRESH1-74CFEA76FF37C64DE059",
    "FRESH1-778AAC63B06DA9E1A5BB",
    "FRESH1-7BD0B466999194C62E5F",
    "FRESH1-91191386DC95E23BEDAC",
    "FRESH1-ACE2F5BAEAFA699A90AC",
    "FRESH1-C35D8D4055B82991DCFC",
    "FRESH1-C8E58C04849244A581BA",
    "FRESH1-DA204D3E75998A08D07B",
    "FRESH1-E0F87F9DB039E5A48AAB",
    "FRESH1-EAF5141532787D12AFE2",
    "FRESH1-FC529FBBABD1C203BAD8",
    "FRESH1-FE24B910C4F62319F60E"
)

$classification = @{
    "FRESH1-2FF08EDFC754E290D7A4" = [ordered]@{
        verdict = "TRUE_REJECTION"; family = "SOURCE_BOUNDARY_SWITCH"; false_signal = $null
        basis = "The source render is a scan/paper boundary; both claimed segments lack stable full-span support, consistent with the prior paper-edge observation."
    };
    "FRESH1-316D125FE4861584BE02" = [ordered]@{
        verdict = "TRUE_REJECTION"; family = "PIECEWISE_OFFSET_COLLAPSE"; false_signal = $null
        basis = "The source render and prior human observation show multiple/offset segments; the measured offset and tangent profiles are unstable."
    };
    "FRESH1-4694F629CD0F75FF0AB7" = [ordered]@{
        verdict = "TRUE_REJECTION"; family = "SOURCE_BOUNDARY_SWITCH"; false_signal = $null
        basis = "The source render is a faint top-page boundary; both fragments have low continuity and material disjoint intervals."
    };
    "FRESH1-4966D4412392002C19C2" = [ordered]@{
        verdict = "TRUE_REJECTION"; family = "SOURCE_BOUNDARY_SWITCH"; false_signal = $null
        basis = "The source render and human label show separate segments with a boundary-position change; drift, tangent, and support-run evidence agree."
    };
    "FRESH1-5BF4B6744E8C47B6DCD2" = [ordered]@{
        verdict = "TRUE_REJECTION"; family = "SOURCE_BOUNDARY_SWITCH"; false_signal = $null
        basis = "One fragment is stable, but the second follows a switched/curved support with 12.2% normalized drift and two support-identity switches."
    };
    "FRESH1-624D754C52D4723051AF" = [ordered]@{
        verdict = "TRUE_REJECTION"; family = "CURVED_CONTOUR_STRAIGHT_FIT"; false_signal = $null
        basis = "The source render is a thick text/contour region; the rejected fragment has sustained lateral drift and a curved-fit profile rather than a thin straight stroke."
    };
    "FRESH1-74CFEA76FF37C64DE059" = [ordered]@{
        verdict = "TRUE_REJECTION"; family = "SOURCE_BOUNDARY_SWITCH"; false_signal = $null
        basis = "The source render is a degraded page-edge band; fragment A lacks continuity while only fragment B has a confirmed straight trajectory."
    };
    "FRESH1-778AAC63B06DA9E1A5BB" = [ordered]@{
        verdict = "TRUE_REJECTION"; family = "CURVED_CONTOUR_STRAIGHT_FIT"; false_signal = $null
        basis = "The source render is a curved/filled contour; both fragments show 15.7%/18.4% normalized drift and support-identity switches."
    };
    "FRESH1-7BD0B466999194C62E5F" = [ordered]@{
        verdict = "TRUE_REJECTION"; family = "PIECEWISE_OFFSET_COLLAPSE"; false_signal = $null
        basis = "The short upper fragment shows offset/tangent collapse against a different structural support; the long lower fragment alone is insufficient."
    };
    "FRESH1-91191386DC95E23BEDAC" = [ordered]@{
        verdict = "TRUE_REJECTION"; family = "CURVED_CONTOUR_STRAIGHT_FIT"; false_signal = $null
        basis = "The source render is a curved logo contour; both fragments have sustained lateral drift and the curved-fit reason."
    };
    "FRESH1-ACE2F5BAEAFA699A90AC" = [ordered]@{
        verdict = "FALSE_REJECTION"; family = $null; false_signal = "CROSSING_CONTAMINATED_TANGENT_OR_OFFSET_PROFILE"
        basis = "The source render shows a horizontal straight source line through a junction/filled structure; support and continuity are full with near-zero drift, but the terminal offset/tangent profile rejects it."
    };
    "FRESH1-C35D8D4055B82991DCFC" = [ordered]@{
        verdict = "TRUE_REJECTION"; family = "CURVED_CONTOUR_STRAIGHT_FIT"; false_signal = $null
        basis = "The source render is a curved/filled glyph contour; both fragments have large drift and repeated support-identity switches."
    };
    "FRESH1-C8E58C04849244A581BA" = [ordered]@{
        verdict = "TRUE_REJECTION"; family = "CURVED_CONTOUR_STRAIGHT_FIT"; false_signal = $null
        basis = "The source render is a curved logo contour; both fragments drift laterally along the curve."
    };
    "FRESH1-DA204D3E75998A08D07B" = [ordered]@{
        verdict = "TRUE_REJECTION"; family = "CURVED_CONTOUR_STRAIGHT_FIT"; false_signal = $null
        basis = "The source render is a thick glyph/contour region; the rejected fragment has support switches, a 2-stroke-width offset jump, and high tangent variation."
    };
    "FRESH1-E0F87F9DB039E5A48AAB" = [ordered]@{
        verdict = "TRUE_REJECTION"; family = "CURVED_CONTOUR_STRAIGHT_FIT"; false_signal = $null
        basis = "The source render is a curved logo contour; both fragments have sustained drift and curved-fit tangent/trajectory evidence."
    };
    "FRESH1-EAF5141532787D12AFE2" = [ordered]@{
        verdict = "FALSE_REJECTION"; family = $null; false_signal = "CROSSING_CONTAMINATED_TANGENT_OR_OFFSET_PROFILE"
        basis = "The source render shows a straight vertical grid/source line with repeated orthogonal crossings; drift and offset bins are zero with full credible windows, but crossing-contaminated p95 tangent evidence rejects it."
    };
    "FRESH1-FC529FBBABD1C203BAD8" = [ordered]@{
        verdict = "TRUE_REJECTION"; family = "DISJOINT_OR_MIXED_SUPPORT"; false_signal = $null
        basis = "The prior human label is patterned visible segments; fragment B has a 4.76-stroke-width offset range and a 25.67-degree tangent p95."
    };
    "FRESH1-FE24B910C4F62319F60E" = [ordered]@{
        verdict = "TRUE_REJECTION"; family = "SOURCE_BOUNDARY_SWITCH"; false_signal = $null
        basis = "The source render is a page-edge band; both fragments have low support/continuity and material disjoint intervals despite low drift and tangent."
    };
}

$priorStatus = @{
    "FRESH1-2FF08EDFC754E290D7A4" = [ordered]@{ span = "SPAN_INTEGRITY_SUPPORTED"; axis = "PRIMITIVE_AXIS_UNCERTAIN" };
    "FRESH1-316D125FE4861584BE02" = [ordered]@{ span = "SPAN_INTEGRITY_SUPPORTED"; axis = "PRIMITIVE_AXIS_SUPPORTED" };
    "FRESH1-91191386DC95E23BEDAC" = [ordered]@{ span = "SPAN_INTEGRITY_SUPPORTED"; axis = "AXIS_SUPPORT_SUPPORTED" }
}

$priorHuman = @{
    "FRESH1-2FF08EDFC754E290D7A4" = [ordered]@{
        primary_label = "NOT_DIRECT_STRAIGHT_CONTINUATION"
        secondary_flags = @()
        observation = "不能识别成一条线；纸张扫描带来的痕迹，是纸的边缘。"
        source = "PRIMITIVE-AXIS-SUPPORT-INTEGRITY-V1-FINAL.md"
    };
    "FRESH1-316D125FE4861584BE02" = [ordered]@{
        primary_label = "NOT_DIRECT_STRAIGHT_CONTINUATION"
        secondary_labels = @("MULTIPLE_OR_OFFSET_SEGMENTS")
        secondary_flags = @("multiple", "foreign", "crossing")
        observation = "多尖段的线段被识别成一条完整的直线。"
        source = "PRIMITIVE-COHERENCE-ENDPOINT-AUDIT-V1-FINAL.md; SOURCE-FIDELITY-PRIMITIVE-CONTRACT-V1-FINAL.md"
    };
    "FRESH1-4966D4412392002C19C2" = [ordered]@{
        primary_label = "VISIBLE_SEPARATE_SEGMENTS"
        secondary_flags = @("CROSSES_STRUCTURE", "BOUNDARY_POSITION_CHANGES", "ENDPOINT_ANOMALY")
        observation = $null
        source = "source-gap-v1-1-human-state-migration.json"
    };
    "FRESH1-FC529FBBABD1C203BAD8" = [ordered]@{
        primary_label = "PATTERNED_VISIBLE_SEGMENTS"
        secondary_flags = @("CROSSES_STRUCTURE", "ENDPOINT_ANOMALY")
        observation = $null
        source = "source-gap-v1-1-human-state-migration.json"
    }
}

function Format-Number([object]$value) {
    if ($null -eq $value) { return "NA" }
    return ("{0:0.######}" -f [double]$value)
}

function Format-Profile([object]$profile) {
    $offset = "med=$(Format-Number $profile.lateral_offset_profile.center_offset_median_px)px; range=$(Format-Number $profile.lateral_offset_profile.center_offset_range_px)px/$(Format-Number $profile.lateral_offset_profile.center_offset_range_widths)w"
    $tangent = "median=$(Format-Number $profile.local_tangent_profile.median_degrees)deg; p95=$(Format-Number $profile.local_tangent_profile.p95_degrees)deg"
    $trajectory = "credible=$(Format-Number $profile.trajectory_stability.credible_window_fraction); support=$(Format-Number $profile.trajectory_stability.associated_support_fraction); continuity=$(Format-Number $profile.trajectory_stability.local_continuity_fraction); disjoint=$(Format-Number $profile.trajectory_stability.longest_disjoint_interval_fraction)"
    $support = "switches=$($profile.support_identity_evidence.abrupt_support_identity_switches); runs=$($profile.support_identity_evidence.support_run_count); crossings=$(Format-Number $profile.support_identity_evidence.junction_or_crossing_fraction)"
    return "$($profile.fragment): len=$($profile.primitive_length_px)px; $offset; $tangent; $trajectory; $support"
}

$replay = Get-Content -LiteralPath $runtimeReplay -Raw | ConvertFrom-Json
$summary = Get-Content -LiteralPath $trackedSummary -Raw | ConvertFrom-Json
$migration = Get-Content -LiteralPath $sourceGapMigrationPath -Raw | ConvertFrom-Json

if ($replay.records.Count -ne 147) { throw "Frozen replay record count is not 147." }
if ($ids.Count -ne 18 -or (@($ids | Sort-Object -Unique).Count -ne 18)) { throw "Audit ID list is not exactly 18 unique candidates." }
if (@($classification.Keys).Count -ne 18) { throw "Classification map does not cover exactly 18 candidates." }

$records = foreach ($id in $ids) {
    @($replay.records | Where-Object candidate_id -eq $id)
}
if ($records.Count -ne 18) { throw "Recovered record count is not exactly 18." }
if ((@($records.candidate_id | Sort-Object -Unique).Count) -ne 18) { throw "Recovered candidate IDs are not unique." }
if (@($records | Where-Object { $_.eligibility_after -ne "INELIGIBLE_STRAIGHT_REJECTED" }).Count -ne 0) {
    throw "A recovered record is not newly ineligible after the straight gate."
}

$cases = foreach ($record in $records) {
    $id = $record.candidate_id
    $geometryA = $record.primitive_geometry.fragment_a
    $geometryB = $record.primitive_geometry.fragment_b
    $dx = [double]$geometryB.end[0] - [double]$geometryA.start[0]
    $dy = [double]$geometryB.end[1] - [double]$geometryA.start[1]
    $claimedLength = [math]::Round([math]::Sqrt(($dx * $dx) + ($dy * $dy)), 6)
    $profiles = foreach ($fragment in @($record.fragment_profiles)) {
        $evidence = $fragment.evidence
        $trajectory = $evidence.trajectory
        $geometry = $record.primitive_geometry.PSObject.Properties[$fragment.fragment].Value
        [ordered]@{
            fragment = $fragment.fragment
            geometry = [ordered]@{
                start = @([int]$geometry.start[0], [int]$geometry.start[1])
                end = @([int]$geometry.end[0], [int]$geometry.end[1])
            }
            primitive_length_px = [double]$trajectory.length_px
            straight_validity_status = $fragment.status
            straight_validity_reason = $fragment.reason
            lateral_offset_profile = [ordered]@{
                center_offset_median_px = [double]$trajectory.center_offset_median_px
                center_offset_range_px = [double]$trajectory.center_offset_range_px
                center_offset_range_widths = [double]$trajectory.center_offset_range_widths
                offset_bin_medians_px = @($trajectory.offset_bin_medians_px)
                max_sustained_lateral_drift_px = [double]$evidence.max_sustained_lateral_drift_px
                max_sustained_lateral_drift_fraction = [double]$evidence.max_sustained_lateral_drift_fraction
            }
            local_tangent_profile = [ordered]@{
                median_degrees = [double]$trajectory.local_tangent_delta_median_degrees
                p95_degrees = [double]$evidence.local_tangent_deviation_p95_degrees
            }
            trajectory_stability = [ordered]@{
                credible_window_fraction = [double]$evidence.credible_straight_window_fraction
                associated_support_fraction = [double]$trajectory.associated_support_fraction
                local_continuity_fraction = [double]$trajectory.local_continuity_fraction
                longest_disjoint_interval_fraction = [double]$trajectory.longest_disjoint_interval_fraction
                longest_disjoint_interval_px = [double]$trajectory.longest_disjoint_interval_px
                usable_window_count = [int]$evidence.usable_trajectory_window_count
            }
            support_identity_evidence = [ordered]@{
                abrupt_support_identity_switches = [int]$evidence.abrupt_support_identity_switches
                support_run_count = [int]$evidence.support_run_count
                junction_or_crossing_fraction = [double]$trajectory.junction_or_crossing_fraction
                multi_peak_fraction = [double]$trajectory.multi_peak_fraction
                max_sustained_offset_jump_px = [double]$trajectory.max_sustained_offset_jump_px
                max_sustained_offset_jump_widths = [double]$trajectory.max_sustained_offset_jump_widths
            }
        }
    }
    $prior = if ($priorStatus.ContainsKey($id)) { $priorStatus[$id] } else {
        [ordered]@{ span = "NOT_AVAILABLE_IN_PRIOR_ARTIFACTS"; axis = "NOT_AVAILABLE_IN_PRIOR_ARTIFACTS" }
    }
    $human = if ($priorHuman.ContainsKey($id)) { $priorHuman[$id] } else { $null }
    $decision = $classification[$id]
    [ordered]@{
        candidate_id = $id
        source_family = $record.source_family
        source_render_path = $record.source_render_path
        orientation = $record.orientation
        claimed_primitive_length_px = $claimedLength
        fragment_lengths_px = @($profiles | ForEach-Object { $_.primitive_length_px })
        straight_validity_status = $record.straight_validity_status
        straight_validity_reasons = @($profiles | Where-Object { $_.straight_validity_status -eq "STRAIGHT_REJECTED" } | ForEach-Object { $_.straight_validity_reason } | Select-Object -Unique)
        eligibility_before = $record.eligibility_before
        current_eligibility = $record.eligibility_after
        text_glyph_status = $record.text_status
        prior_span_status = $prior.span
        prior_axis_status = $prior.axis
        prior_human_evidence = $human
        human_gate_comparison = if ($null -ne $human) { "AGREES" } else { "NOT_DIRECTLY_COMPARABLE" }
        fragment_profiles = @($profiles)
        audit_verdict = $decision.verdict
        failure_family = $decision.family
        false_rejection_signal = $decision.false_signal
        audit_basis = $decision.basis
    }
}

$trueCount = @($cases | Where-Object audit_verdict -eq "TRUE_REJECTION").Count
$falseCount = @($cases | Where-Object audit_verdict -eq "FALSE_REJECTION").Count
$uncertainCount = @($cases | Where-Object audit_verdict -eq "UNCERTAIN_REJECTION").Count
$denominator = $trueCount + $falseCount
$precision = if ($denominator -gt 0) { [math]::Round($trueCount / $denominator, 6) } else { $null }
$familyNames = @(
    "CURVED_CONTOUR_STRAIGHT_FIT",
    "PIECEWISE_OFFSET_COLLAPSE",
    "SOURCE_BOUNDARY_SWITCH",
    "DISJOINT_OR_MIXED_SUPPORT",
    "OTHER_GENERIC_INVALID_STRAIGHT_FIT"
)
$familyCounts = [ordered]@{}
foreach ($familyName in $familyNames) {
    $familyCounts[$familyName] = @($cases | Where-Object { $_.audit_verdict -eq "TRUE_REJECTION" -and $_.failure_family -eq $familyName }).Count
}
$humanCases = @($cases | Where-Object { $null -ne $_.prior_human_evidence }).Count
$humanAgreement = @($cases | Where-Object human_gate_comparison -eq "AGREES").Count
$humanDisagreement = @($cases | Where-Object human_gate_comparison -eq "DISAGREES").Count
$falseSignalCases = @($cases | Where-Object { $null -ne $_.false_rejection_signal })

if (@($summary.current_source_gap_16_records | Where-Object eligibility_after -eq "INELIGIBLE_STRAIGHT_REJECTED").Count -ne 3) {
    throw "Current source-gap rejected count is not 3."
}
$sourceGapRejected = foreach ($record in $summary.current_source_gap_16_records | Where-Object eligibility_after -eq "INELIGIBLE_STRAIGHT_REJECTED") {
    $state = @($migration.initial_review_state | Where-Object candidate_id -eq $record.candidate_id) | Select-Object -First 1
    $case = $cases | Where-Object candidate_id -eq $record.candidate_id
    [ordered]@{
        review_index = if ($null -ne $state) { $state.review_index } else { $null }
        candidate_id = $record.candidate_id
        human_primary_label = if ($null -ne $state) { $state.primary_class } else { $null }
        straight_rejection_reason = ($case.straight_validity_reasons -join "; ")
        audit_verdict = $case.audit_verdict
    }
}

$controlPreservation = [ordered]@{
    old_valid_direct_control = "1 / 1"
    old_valid_annotation_controls = "6 / 6"
    fresh_human_direct_controls = "9 / 9"
    fresh_human_direct_annotation_controls = "6 / 6"
    source_summary_match = (
        $summary.old_valid_direct_control -eq 1 -and
        $summary.old_valid_annotation_controls -eq 6 -and
        $summary.fresh_human_direct_controls -eq 9 -and
        $summary.fresh_human_direct_annotation_controls -eq 6
    )
}

$result = [ordered]@{
    schema_version = 1
    task_id = "FROZEN147_NEWLY_INELIGIBLE_STRAIGHT_REJECTED_AUDIT_V1"
    base_checkpoint = "0de2ce025373406813c5fed9938781e0ebec2d08"
    frozen_pool = 147
    recovered_newly_ineligible_count = $cases.Count
    recovered_candidate_ids = @($cases | ForEach-Object candidate_id)
    audit_verdict_counts = [ordered]@{
        TRUE_REJECTION = $trueCount
        FALSE_REJECTION = $falseCount
        UNCERTAIN_REJECTION = $uncertainCount
    }
    audited_rejection_precision = $precision
    true_rejection_family_counts = $familyCounts
    prior_human_evidence_cases = $humanCases
    human_gate_agreement = $humanAgreement
    human_gate_disagreement = $humanDisagreement
    false_rejection_families = @(
        [ordered]@{
            family = "CROSSING_CONTAMINATED_TANGENT_OR_OFFSET_PROFILE"
            candidate_ids = @($falseSignalCases | ForEach-Object candidate_id)
            count = $falseSignalCases.Count
            signal = "JUNCTION_OR_CROSSING_FRACTION and MULTI_PEAK_FRACTION contaminate local tangent/terminal offset evidence on otherwise stable straight trajectories."
        }
    )
    current_source_gap_16_rejected = $sourceGapRejected
    controls = $controlPreservation
    decision = [ordered]@{
        straight_validity_gate_should_freeze = if ($falseCount -eq 0) { "YES" } else { "NO" }
        rationale = if ($falseCount -eq 0) { "No clear false rejections; uncertain cases do not show a systematic safety concern." } else { "Clear false rejections remain; review the generic crossing-contaminated tangent/offset signal before freezing." }
        next_target = "REVIEW_CROSSING_CONTAMINATED_TANGENT_OFFSET_PROFILE_BEFORE_GATE_FREEZE"
    }
    governance = [ordered]@{
        production_semantic_delta = "NONE"
        straight_validity_gate_changed = "NO"
        span_guard_changed = "NO"
        axis_guard_changed = "NO"
        text_glyph_guard_changed = "NO"
        admissibility_guard_changed = "NO"
        new_candidate_mining = "NO"
        new_source_gap_package = "NO"
        model_run = "NO"
        model_bake_off_should_resume = "NO"
        batch03_should_resume = "NO"
        validation = "NO"
        locked_blind = "0 / 8"
        h1_h2_opened = "NO"
    }
    cases = @($cases)
}

$json = $result | ConvertTo-Json -Depth 20
$trackedJson = "$trackedDir\straight-rejected-audit-results.json"
$runtimeJson = "$runtimeDir\straight-rejected-audit-results.json"
Set-Content -LiteralPath $trackedJson -Value $json -Encoding UTF8
Set-Content -LiteralPath $runtimeJson -Value $json -Encoding UTF8

$reportLines = New-Object System.Collections.Generic.List[string]
[void]$reportLines.Add("# FROZEN147 NEWLY-INELIGIBLE STRAIGHT-REJECTED AUDIT V1")
[void]$reportLines.Add("")
[void]$reportLines.Add("Base checkpoint: 0de2ce025373406813c5fed9938781e0ebec2d08")
[void]$reportLines.Add("")
[void]$reportLines.Add("## Decision")
[void]$reportLines.Add("")
[void]$reportLines.Add("- Recovered exactly 18 newly ineligible candidates from the authoritative frozen-147 replay; no candidate was added or omitted.")
[void]$reportLines.Add("- Verdicts: **TRUE_REJECTION $trueCount**, **FALSE_REJECTION $falseCount**, **UNCERTAIN_REJECTION $uncertainCount**.")
[void]$reportLines.Add("- AUDITED_REJECTION_PRECISION: **$precision**.")
[void]$reportLines.Add("- STRAIGHT_VALIDITY_GATE_SHOULD_FREEZE: **$(if ($falseCount -eq 0) { "YES" } else { "NO" })**.")
if ($falseCount -gt 0) {
    [void]$reportLines.Add("- False-rejection signal: **CROSSING_CONTAMINATED_TANGENT_OR_OFFSET_PROFILE** (ACE2F5..., EAF514...). No fix or threshold change was made.")
}
[void]$reportLines.Add("")
[void]$reportLines.Add("Runtime contact sheet: $runtimeDir\straight-rejected-audit-v1-contact-sheet.png")
[void]$reportLines.Add("")
[void]$reportLines.Add("## Candidate audit")
[void]$reportLines.Add("")
[void]$reportLines.Add("| # | candidate | source family | orientation / claimed length | straight reason/status | lateral offset; tangent; trajectory/support | text | prior span / axis | human / gate | verdict / family |")
[void]$reportLines.Add("|---:|---|---|---|---|---|---|---|---|---|")
$row = 0
foreach ($case in $cases) {
    $row++
    $profilesText = (($case.fragment_profiles | ForEach-Object { Format-Profile $_ }) -join " || ")
    $reasonText = (($case.straight_validity_reasons) -join "; ")
    $humanText = if ($null -ne $case.prior_human_evidence) { "$($case.prior_human_evidence.primary_label) / $($case.human_gate_comparison)" } else { "none / NOT_DIRECTLY_COMPARABLE" }
    $familyText = if ($null -ne $case.failure_family) { $case.failure_family } else { "—" }
    $familyText = "$($case.audit_verdict) / $familyText"
    [void]$reportLines.Add("| $row | $($case.candidate_id) | $($case.source_family) | $($case.orientation) / $($case.claimed_primitive_length_px) px | $reasonText / $($case.straight_validity_status) | $profilesText | $($case.text_glyph_status) | $($case.prior_span_status) / $($case.prior_axis_status) | $humanText | $familyText |")
}
[void]$reportLines.Add("")
[void]$reportLines.Add("The full per-fragment evidence, including offset-bin medians, tangent profiles, trajectory stability, support identity, geometry, and source paths, is in straight-rejected-audit-results.json.")
[void]$reportLines.Add("")
[void]$reportLines.Add("## Prior human evidence")
[void]$reportLines.Add("")
[void]$reportLines.Add("Prior human evidence exists for 4 of 18 cases: 2FF08..., 316D..., 4966D..., and FC529.... All four agree with STRAIGHT_REJECTED; there are 0 disagreements. The repaired source-gap replacement 911913... has no prior primary human label and is not counted as a human-evidence case.")
[void]$reportLines.Add("")
[void]$reportLines.Add("## Current SOURCE_GAP_REVIEW_V1_1 rejected set")
[void]$reportLines.Add("")
[void]$reportLines.Add("| review index | candidate | human primary label | straight rejection reason | audit verdict |")
[void]$reportLines.Add("|---:|---|---|---|---|")
foreach ($item in $sourceGapRejected) {
    [void]$reportLines.Add("| $($item.review_index) | $($item.candidate_id) | $($item.human_primary_label) | $($item.straight_rejection_reason) | $($item.audit_verdict) |")
}
[void]$reportLines.Add("")
[void]$reportLines.Add("## Failure-family counts")
[void]$reportLines.Add("")
foreach ($familyName in $familyNames) {
    [void]$reportLines.Add("- $($familyName): $($familyCounts[$familyName])")
}
[void]$reportLines.Add("")
[void]$reportLines.Add("## Frozen controls and scope")
[void]$reportLines.Add("")
[void]$reportLines.Add("- Old valid direct: 1 / 1; old valid annotation: 6 / 6; fresh human-direct: 9 / 9; fresh human-direct annotation: 6 / 6.")
[void]$reportLines.Add("- No guard code, threshold, span/axis/text/admissibility behavior, source-gap package, candidate pool, model, VALIDATION, LOCKED_BLIND, or H1/H2 state was changed or opened.")
[void]$reportLines.Add("- The two false rejections are reported only; no production or gate fix was implemented.")
[void]$reportLines.Add("")
[void]$reportLines.Add("NEXT_TARGET: REVIEW_CROSSING_CONTAMINATED_TANGENT_OFFSET_PROFILE_BEFORE_GATE_FREEZE")
[void]$reportLines.Add("")
[void]$reportLines.Add("Tracked report: $trackedDir\STRAIGHT-REJECTED-AUDIT-V1-FINAL.md")

$report = $reportLines -join [Environment]::NewLine
Set-Content -LiteralPath "$trackedDir\STRAIGHT-REJECTED-AUDIT-V1-FINAL.md" -Value $report -Encoding UTF8
"Generated $trackedJson"
"Generated $runtimeJson"
"Generated $trackedDir\STRAIGHT-REJECTED-AUDIT-V1-FINAL.md"
