# Axon Health Task A — computed results

Fiscal year: 2025; reporting cutoff: 2025-12-31; snapshot assumption: 2026-01-15; follow-up anchor: discharge.
Input: 200 rows; included: 200 unique residents; identity exclusions: 0; capacity: 24.

## Observed milestones and ordered funnel

Observed dates by cutoff: {"referral_date": 141, "intake_date": 102, "admission_date": 76, "discharge_date": 56}.

| Ordered stage | N | Previous denominator | Conversion |
|---|---:|---:|---:|
| referral | 141 | 141 | 100.00% |
| intake | 101 | 141 | 71.63% |
| admission | 70 | 101 | 69.31% |
| discharge | 52 | 70 | 74.29% |

## Stage durations

| Stage | Valid N | Median days | P90 days |
|---|---:|---:|---:|
| referral_to_intake | 101 | 6.00 | 18.00 |
| intake_to_admission | 71 | 9.00 | 26.00 |
| referral_to_admission | 76 | 16.00 | 46.00 |
| admission_to_discharge | 56 | 75.50 | 149.50 |

Next milestone not recorded by cutoff (may include closed referrals, not necessarily active waitlists):

| Stage | Start observed | No next milestone | Median elapsed days | P90 elapsed days |
|---|---:|---:|---:|---:|
| referral_to_intake | 141 | 39 | 185.00 | 324.00 |
| intake_to_admission | 102 | 31 | 164.00 | 332.00 |
| referral_to_admission | 141 | 65 | 181.00 | 324.00 |
| admission_to_discharge | 76 | 20 | 74.00 | 158.30 |

## Length of stay

| Cohort | N | Median days | P90 days |
|---|---:|---:|---:|
| ended_stays | 80 | 95.00 | 188.60 |
| ongoing_elapsed_stays | 18 | 69.00 | 140.50 |
| program_completed_subset | 40 | 129.00 | 213.50 |

LOS exclusions: {"no_admission_by_cutoff": 91, "ended_before_fiscal_year": 8, "unknown_exit": 3}.

## Monthly occupancy

| Month | Days | Available bed-days | Known bed-days | Uncertain bed-days | Lower | Upper | End census range |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2025-01 | 31 | 744 | 628 | 31 | 84.41% | 88.58% | 22–23 |
| 2025-02 | 28 | 672 | 579 | 35 | 86.16% | 91.37% | 22–24 |
| 2025-03 | 31 | 744 | 688 | 62 | 92.47% | 100.81% | 22–24 |
| 2025-04 | 30 | 720 | 703 | 60 | 97.64% | 105.97% | 24–26 |
| 2025-05 | 31 | 744 | 730 | 62 | 98.12% | 106.45% | 24–26 |
| 2025-06 | 30 | 720 | 679 | 60 | 94.31% | 102.64% | 24–26 |
| 2025-07 | 31 | 744 | 666 | 67 | 89.52% | 98.52% | 23–26 |
| 2025-08 | 31 | 744 | 545 | 93 | 73.25% | 85.75% | 15–18 |
| 2025-09 | 30 | 720 | 587 | 90 | 81.53% | 94.03% | 24–27 |
| 2025-10 | 31 | 744 | 738 | 93 | 99.19% | 111.69% | 24–27 |
| 2025-11 | 30 | 720 | 640 | 90 | 88.89% | 101.39% | 21–24 |
| 2025-12 | 31 | 744 | 598 | 93 | 80.38% | 92.88% | 18–21 |

## Follow-up outcomes

Cohort: All historical exits by reporting cutoff, maturity assessed at cutoff; only mature follow-ups enter the due denominator.

| Months | Cohort | Eligibility unknown | Not due | Due denominator | Recovery | Relapse | LTFU | Other unresolved | Recovery lower (recovery/due) | Recovery upper ((recovery+unresolved)/due) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 6 | 91 | 3 | 43 | 45 | 21 | 6 | 13 | 5 | 46.67% | 86.67% |
| 12 | 91 | 3 | 80 | 8 | 1 | 2 | 5 | 0 | 12.50% | 75.00% |

## Data quality

29 flags across 26 resident IDs.

| Severity | Rule | Flags |
|---|---|---:|
| HIGH | MISSING_DISCHARGE_DATE | 3 |
| HIGH | NEGATIVE_REFERRAL_TO_INTAKE | 2 |
| MEDIUM | MISSING_DISCHARGE_REASON | 2 |
| MEDIUM | MISSING_INTAKE | 6 |
| REVIEW | FUTURE_ADMISSION_DATE | 1 |
| REVIEW | FUTURE_DISCHARGE_DATE | 4 |
| REVIEW | FUTURE_INTAKE_DATE | 1 |
| REVIEW | NOT_WAIVED_ZERO_FEE | 2 |
| REVIEW | OUTCOME_BEFORE_DUE_12M | 3 |
| REVIEW | OUTCOME_BEFORE_DUE_6M | 3 |
| REVIEW | WAIVED_WITH_POSITIVE_FEE | 2 |

## Interpretation

- Cutoff and follow-up anchor are explicit analytical assumptions; confirm against Task A.
- Sequential funnel requires present, ordered intermediate dates; observed milestones also shown.
- Occupancy uses [admission, discharge), excludes discharge day, and is bounded for unknown exits.
- Fiscal-year occupancy includes all calendar days from January 1; final month is partial for an incomplete year.
- Funnel and stage durations use referral-year cohorts. Later milestones after year end are censored.
- Missing next milestones are shown as unresolved; the file cannot distinguish active waiting from closed referrals at year end.
- Ended LOS includes exits in the selected fiscal year; ongoing LOS includes all known active stays at cutoff.
- Bounds apply to usable admission records; missing admissions and identity exclusions are outside them.
- Ongoing LOS is elapsed time at cutoff, not an estimate of eventual total LOS.
- Outcomes cover all exited residents, including non-completers, unless admission anchor selected.
- Unknown eligibility is separate from not due. LTFU, unknown, blank, and overdue not_yet_due remain in the due denominator.
- Recovery means recorded engaged_in_recovery. Follow-up assessment dates are absent; timing cannot be verified.
- Outcome bounds are worst/best case bounds for unresolved due outcomes, not confidence intervals.
- Rates are fractions in CSV/JSON; null/blank denotes undefined, never zero.
