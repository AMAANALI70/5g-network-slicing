# Decision Outcome Sankey — Analysis Report

## Data Source
- File: `results/datasets/dataset_agentic_medium.csv`
- Total decisions: 9,000
- Traffic level: medium

## Outcome Thresholds
- **Recovered**: RTT < 15ms within 3 cycles post-action
- **Improved**: RTT reduced > 10% (but still above SLA)
- **No Change**: |RTT delta| ≤ 5%
- **Worsened**: RTT increased > 5%

## Observation Distribution
- RTT Stable: 4235 (47.1%)
- RTT Breach (>15ms): 1887 (21.0%)
- RTT Falling: 1255 (13.9%)
- Throughput Drop: 1247 (13.9%)
- RTT Rising: 376 (4.2%)

## Root Cause Distribution
- nominal: 3652 (40.6%)
- recovery_phase: 2973 (33.0%)
- embb_congestion: 1227 (13.6%)
- urllc_degradation: 466 (5.2%)
- persistent_congestion: 356 (4.0%)
- transient_spike: 326 (3.6%)

## Action Distribution
- no_action: 6883 (76.5%)
- restore_embb: 850 (9.4%)
- hold_throttle: 784 (8.7%)
- throttle_embb: 447 (5.0%)
- throttle_preemptive: 36 (0.4%)

## Outcome Distribution
- No Change: 3707 (41.2%)
- Worsened: 2031 (22.6%)
- Recovered: 1843 (20.5%)
- Improved: 1419 (15.8%)

## Success Rate per Action
- **hold_throttle**: 736/784 effective (93.9%)
- **no_action**: 1349/6883 effective (19.6%)
- **restore_embb**: 718/850 effective (84.5%)
- **throttle_embb**: 424/447 effective (94.9%)
- **throttle_preemptive**: 35/36 effective (97.2%)

## Success Rate per Root Cause
- **embb_congestion**: 749/1227 positive outcomes (61.0%)
- **nominal**: 674/3652 positive outcomes (18.5%)
- **persistent_congestion**: 158/356 positive outcomes (44.4%)
- **recovery_phase**: 1193/2973 positive outcomes (40.1%)
- **transient_spike**: 213/326 positive outcomes (65.3%)
- **urllc_degradation**: 275/466 positive outcomes (59.0%)

## Top 5 Most Common Decision Paths
- `RTT Stable` → `nominal` → `no_action` → **No Change**: 1355
- `RTT Stable` → `recovery_phase` → `no_action` → **No Change**: 866
- `RTT Stable` → `nominal` → `no_action` → **Worsened**: 514
- `Throughput Drop` → `nominal` → `no_action` → **No Change**: 422
- `RTT Stable` → `recovery_phase` → `restore_embb` → **Recovered**: 323

## Most Successful Path
`RTT Stable` → `recovery_phase` → `restore_embb` → **Recovered** (323 occurrences)

## Least Successful Path
`RTT Stable` → `nominal` → `no_action` → **Worsened** (514 occurrences)