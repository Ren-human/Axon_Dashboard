# Part B verification — 2026-11-02

## User-authorized live Gemini repair

- The existing key was loaded internally and never printed. Model-list access returned HTTP 200, but gemini-3.8-flash minimal and full structured requests timed out, as did a minimal Interactions request. This does not establish that the key is invalid or that all Gemini service endpoints are down.
- A comparison request to gemini-2.5-flash returned HTTP 404, explicitly unavailable to new users on this project. It was not selected as a fallback.
- gemini-3.5-flash-lite returned HTTP 200 for both minimal generation and the application's complete structured-output planner schema. The default and the local model configuration were changed to that verified model.
- Five live application paths passed using the candidate adapter and the existing authorized local report: navigation, 6-month coverage value, 6/12-month custom comparison, complete occupancy/follow-up report, and clarification of relapse proportion followed by a real query. The model received only fixed development prompts, approved catalog/schema metadata and clarification text. Report records and query results stayed local. One initial value request unnecessarily asked for clarification; the coverage instruction was tightened and all five paths then passed.
- Twelve offline tests passed: transient 503 recovery; non-retry of 400 and hard 429; short advised 429 recovery; timeout recovery; three-attempt cap; safe provider-status extraction; response-size rejection; bounded semantic-plan correction and failure withholding; metric-specific provider chart constraints; and missing-key behavior without fallback.
- An early clarification run generated an incompatible chart type and was rejected locally. The provider schema was tightened to each metric's own view/field/chart enums, and one corrective planning request is allowed for a locally invalid spec. All five live flows then passed; local query validation was not relaxed.
- Error handling now preserves safe HTTP status, provider enum, model and attempt count. Retries are bounded to three attempts and a planning budget; there is no automatic switch to rules or another model.
- Formal CSV, database and report pointers were not modified. The secrets file's existing key was preserved while its model setting was changed. Unit/UI suites outside the transport change were not rerun for this targeted repair.

## Gemini default rebuild (agent 2.1.0)

The user requested a Gemini-first rebuild and explicitly asked to skip all testing. No tests, parsing evaluations, database smoke checks or live model calls were run for this revision. The prior 60-test/40-question results below apply to the previous rule-default implementation only; they do not verify the new Gemini adapter. Older Chat Completions transport mocks also describe the superseded adapter and are not evidence for this revision.

Changed: Gemini native generateContent transport and structured JSON output, local key configuration, model-first clarification context, default mode/UI labels, setup examples and documentation. Read-only query execution and result-validation logic were retained. No real key or active secrets file was created.

## Historical rule-default baseline (agent 2.0.0)

Status: implemented narrow prototype; optional API adapter has not made a live model call.

## Evidence

- Full suite: **60 tests passed**, 41.525 s. Includes 32 agent query/safety tests, 4 Streamlit agent interaction tests and all 24 existing computation/publication/UI tests.
- Offline bilingual parser regression: **40/40 cases passed**. This measures supported demo expressions, not general natural-language accuracy.
- Read-only smoke against the configured active production aggregate report: direct 6-month coverage, custom 6/12-month comparison chart result, and occupancy/follow-up report all succeeded; report status complete; effective cutoff 2025-12-31. The report database fingerprint matched its manifest before and after.
- Unit/integration data is synthetic and written only to temporary test directories. No test residents were appended to formal CSV; no production initialization or report version publication was performed.
- API adapter tests mock HTTP responses and verify JSON validation. No credential was requested, read from a secrets manager, printed or sent during development. Rule mode is the default regardless of whether unrelated keys exist in the environment.

Commands in a compatible Python environment:

```powershell
python -X utf8 -B -m unittest discover -s tests -v
python -X utf8 -B evals/run_eval.py
```

Environment: Windows, Python 3.13.2, DuckDB 2.0.0, pandas 3.1.0, Streamlit 1.66.1; existing compatible dashboard virtual environment. JSON Schema validation uses jsonschema 4.x.

AppTest needed sandbox-external local socket permission. Initial sandbox runs stalled while creating an asyncio socketpair before any page executed; they were interrupted. Testing outside that restriction completed normally. AppTest verifies execution and interaction, not browser pixel layout.

The source project already used English resident-entry button labels while its existing tests expected Chinese. Tests now accept either locale; the resident-entry production code was not changed. Likewise, the historical-report notice assertion accepts the current English notice. Regression failures were resolved by aligning these stale selectors, without removing behavioral assertions.

## Scope and operational limits

Implemented: report-scoped navigation, values, supported custom chart styles, horizon comparison, clarification, filters through validated specs, bounded self-contained HTML/Markdown reports, evidence/provenance, local metadata-only audit, read-only isolated query process, unauthorized-path and cross-tenant negative tests.

Not established: live model/provider compatibility, production identity management, deployment PHI/residency review, OS-level worker memory isolation, durable chart libraries, cache layer for agent results, PDF/DOCX export, report-specific month slices or quarterly regrouping. See `PART_B_README.md` for exact controls and configuration.

The runtime schema is the implementation contract. The broader engineering plan remains a roadmap; axes are catalog-derived and reports currently select topic sections over one whole report. Unsupported scope must be rejected instead of silently approximated.
