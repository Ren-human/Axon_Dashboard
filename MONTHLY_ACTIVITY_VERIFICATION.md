# Monthly DIY activity chart verification

Implemented the reported request: `generate a line graph of referrals, intakes, and admissions over the year`.

The original six-table report database stored only strict-funnel totals, so monthly event counts were genuinely absent from the agent's available aggregates. The change adds a verified local date aggregation and advertises that capability to Gemini; it does not bypass validation or manufacture a time series from annual totals.

- Twelve targeted synthetic tests cover independent event dates versus referral cohorts, missing/invalid dates, partial-year cutoffs, source-hash mismatch, duplicate IDs, source privacy, unchanged database hash, correct three-line Plotly traces, month/event filters, missing dimensions, unchanged existing aggregate queries and report inclusion.
- Live Gemini verification with the configured key and the user's exact wording returned `monthly_activity/event_counts`, a line chart with referral/intake/admission series and 12 months through the selected 2025-12-31 cutoff. The raw snapshot and database stayed local; only the fixed question and reviewed metadata were sent to the model.
- The follow-up `only in the year 2025` preserved the chart specification and successfully returned the same monthly metric constrained to 2025.
- No formal CSV, database, report configuration, enabled-version pointer or API key is changed by this feature. The query worker checks the source hash against the selected report and retains the six-table database contract.
- Monthly counts describe recorded events using their respective dates. They do not represent a strict referral cohort, verified complete operations, or a conversion rate. Missing/invalid date exclusions are disclosed in provenance; future months are withheld.
