# Part B: Gemini-powered dashboard analytics

AI Analyst now uses **Gemini by default**. Every accepted natural-language request and clarification reply goes through the actual Gemini planner. There is no automatic fallback to regex/rule answers. Missing credentials or provider errors produce an explicit error, and no data query executes for that request.

Gemini proposes a structured JSON plan; the existing local schema and semantic validator check it before fixed read-only SQL templates execute. Existing-chart matching, numerical answers, Plotly rendering and HTML/Markdown reports remain local and use executed query evidence. The model never receives database rows or query results and cannot execute SQL or plotting code.

## Configure the key locally

No real key is included or required while editing the code. At runtime choose either method.

Environment variables in the PowerShell session used to start Streamlit:

```powershell
$env:GEMINI_API_KEY = '<your-real-key>'
# Optional model override:
$env:GEMINI_MODEL = 'gemini-3.5-flash-lite'
python -m streamlit run app.py
```

`GOOGLE_API_KEY` is also accepted as an environment fallback. Environment variables override the project secrets file. The configurable default model is `gemini-3.5-flash-lite`, which was verified using the configured key. The former `gemini-3.8-flash` setting repeatedly timed out in live development requests; listing a model does not prove that generation will succeed for a particular project.

Alternatively, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in the key on your own machine:

```toml
GEMINI_API_KEY = "<your-real-key>"
GEMINI_MODEL = "gemini-3.5-flash-lite"
```

The loader resolves this file relative to the project, independently of the terminal's working directory. The example contains an empty key and is never loaded as a real credential. `.gitignore` excludes the active secrets file; do not paste credentials into chat, source files or Git. No new Python package is needed: the adapter uses Python 3.11+ standard-library HTTPS and TOML support, alongside the existing dashboard dependencies.

The default provider is Gemini's native `generateContent` endpoint with an `x-goog-api-key` header and a structured JSON response schema. See [Google's API reference](https://ai.google.dev/api/generate-content) and [structured output documentation](https://ai.google.dev/gemini-api/docs/generate-content/structured-output). The request uses up to three attempts, a 20-second socket timeout per attempt and a 45-second planning budget checked before each attempt/backoff. The response limit is 1 MiB. Transient HTTP 408/500/502/503/504 and network failures receive bounded exponential backoff with jitter; 429 is retried only with a short explicit Retry-After. Invalid key/permissions/schema errors do not retry. There is no automatic model or rule fallback. Blocked/truncated responses and locally invalid plans are withheld. Safe errors include HTTP status, canonical provider status, model and attempt count, without exposing response prose or keys. Redirects are refused. See [Google's retry guidance](https://ai.google.dev/gemini-api/docs/troubleshooting).

`HARBOURVIEW_AGENT_MODE` defaults to `gemini`. The legacy value `api` also selects native Gemini. Only explicitly setting `HARBOURVIEW_AGENT_MODE=rules` uses the old rule demonstration, which the interface labels accordingly. Old `HARBOURVIEW_LLM_URL`, `HARBOURVIEW_LLM_MODEL`, `HARBOURVIEW_LLM_API_KEY` and `HARBOURVIEW_ALLOW_CLOUD` settings do not configure this native Gemini adapter. Unset a previously configured `HARBOURVIEW_AGENT_MODE=rules` to use the new default.

## Supported requests

Open Overview → AI Analyst. Examples:

- `Where can I see occupancy?`
- `Show the existing occupancy chart for 2025-03 through 2025-06.`
- `What is the current report's 6-month follow-up coverage?`
- `Compare 6-month and 12-month follow-up coverage in one bar chart.`
- `Only keep the 6-month series.` after that chart
- `What is the relapse rate?` → Gemini asks for horizon/denominator → `6 months, all residents due.`
- `Generate an occupancy and follow-up report for the selected report.`
- `Show median and P90 LOS for ended_stays.`
- `Generate a line graph of referrals, intakes, and admissions over the year 2025.`

Requests similar to existing charts are mapped to their real page/control capabilities and get an opening link plus adjustment instructions. Concrete value requests return their queried numbers directly. Supported comparisons, explicit new-chart requests or styles existing controls cannot produce generate custom charts. Full seven-category follow-up composition is available on Overview; the detail page has three main bars plus remaining-category notes.

The planner sees the reviewed catalog, semantic notes and output contract. It may request clarification or reject requests; it cannot invent fields. Metric IDs are `monthly_activity`, `funnel`, `occupancy`, `outcomes`, `los`, `quality`. `agent/spec.schema.json` and `agent/catalog.py` define the runtime contract. The advanced JSON editor can submit an already structured plan without calling a model; that is a manual tool, not a chatbot fallback.

### Monthly DIY activity charts

`monthly_activity/event_counts` supports line, bar, grouped-bar and table output for referrals, intakes and admissions by month. The backend derives the three series from referral_date, intake_date and admission_date in the raw snapshot corresponding to the selected report. It hashes that snapshot against run_metadata.input_sha256 before and after aggregation. Versioned reports use their own immutable raw.csv; legacy reports may use only a server-configured seed with an identical source hash. The system does not silently use the latest dataset for a historical report.

Counts use each event's own date. For example, a 2024 referral followed by a January 2025 intake contributes to the January 2025 intake series. This differs from the strict funnel, which follows a referral cohort. The graph explicitly labels that difference; its series are not a conversion denominator. Missing/invalid dates are excluded and their snapshot-level counts appear in provenance. Months through the selected report cutoff are filled with recorded-event zeros; future months after the cutoff are not fabricated. Zero does not prove complete capture of activity.

No database migration or report republishing is needed: six existing DuckDB tables remain unchanged, and the additional aggregate is generated in the isolated local worker. The LLM sees the new capability definition, not CSV records, dates from individual residents or notes. The source is read-only. If the matching snapshot is unavailable or its hash differs, this metric is withheld with a source explanation.

New charts are not rejected merely because they are absent from the dashboard. For this request, the planner uses monthly_activity rather than trying to turn the annual strict-funnel table into a monthly series. All three time series render as actual line traces when line output is requested. Unsupported source dimensions still require a clear data-gap explanation instead of invented fields.

Clarification context contains only the gated user questions and the model's clarification questions, bounded to four rounds. The previous validated plan can be supplied for chart revisions. Neither mechanism sends previous data answers, report HTML, manifests, filesystem paths or resident records. Changing the selected report clears pending clarification. Explicit years in the original request are retained for the local report-year check after clarification.

## Authorization and data boundaries

The app retains its local single-user demo identity. Default agent access covers only the configured active report, hash-pinned to its manifest, and the server-known legacy `database/harbourview.duckdb`. An arbitrary sidebar path does not grant agent access. Other analysis pages keep their existing behavior.

For authorized historical reports, create a trusted server configuration based on `agent_config.example.json` and set `HARBOURVIEW_AGENT_CONFIG` to its path. Use absolute report paths and hashes. `demo_tenant` is not production authentication; a deployed multi-tenant system must bind authorization to an authenticated identity.

Each request fixes a report fingerprint. Changes invalidate its results. Agent results have no separate cache in this version. Generating charts/reports does not change raw CSV, `current.json`, the business report version or its fixed cutoff. Numerical text, charts and reports use only query results and registered deterministic transformations; a clarification/rejection message is not a data answer.

The local question gate blocks known sensitive fields, obvious identifiers, paths and SQL. It is heuristic and cannot guarantee identification of all PHI. Gemini receives the accepted question text and reviewed metadata, so use operational questions without personal information. Configure only a deployment appropriate for the assignment's agreements and data-residency requirements; possession of a Gemini key alone does not establish those requirements. No compliance certification is implied.

## Read-only execution and reports

The existing worker accepts only catalog metric IDs and uses fixed aggregate SELECT templates. It rejects views/extra base tables, opens DuckDB read-only, disables external access and extension installation/loading, uses one thread and a 256 MB engine budget, disables temp spills, and limits each aggregate table to 500 rows and its serialized output to 1 MiB. Its disposable process has a six-second deadline. Truncated output is never described as complete. Engine memory settings are not an OS memory sandbox.

All report sections share one report snapshot. Reports use bounded topic requests and chart counts; any unavailable validated section is marked, with the report status partial. HTML downloads contain the trusted Plotly JS bundle for offline viewing, numerical tables, metric notes, specifications and evidence IDs. Text is escaped; the model cannot inject renderer code. Markdown includes tables and notes. Files are generated in memory with fixed filenames.

Audit remains local in `.agent_audit.jsonl`: request ID, time, hashed demo subject, report fingerprint, spec hash and status. It does not contain raw questions, result rows, keys, paths or exception stacks. Configure folder access and retention for deployment. Audit failure withholds the result.

## Revision status

The first Gemini rebuild was delivered without tests at the user's request. The subsequent user-authorized live diagnosis verified navigation, scalar answers, custom comparison charts, reports and multi-turn clarification with the existing key; twelve offline regressions cover retries, errors, safe diagnostics and one-shot semantic-plan correction. Provider JSON constraints now encode each metric's allowed views, fields and chart types. A locally invalid plan may receive one corrective model request; it is still withheld if correction fails. Each corrective request has its own bounded transport budget. See `PART_B_VERIFICATION.md` for exact evidence and limitations. No new key was created or exposed; only the model setting in the existing local secrets file was updated.

Supported customization remains bounded by existing aggregate fields and registered chart styles. Report-specific month slices, quarterly regrouping, arbitrary axes/formulas, resident-level analyses, cross-report comparisons, PDF/DOCX export, durable saved-chart libraries and production authentication remain outside this implementation. Use standalone month-filtered charts for monthly slices. The current browser session retains at most eight exchanges.
