# CLAUDE.md — Timepiece MCP Server

## What this project is
FastMCP server (Python, stdio transport) that wraps the OBSS Timepiece REST API (`https://tis.obss.io/rest`) as MCP tools, letting Claude query Jira time-in-status data.

## Project structure
```
timepiece_mcp/
  __init__.py
  server.py          # All tools, models, enums, helpers — single file, 1184 lines
test_tools.py        # Integration test suite (8 tests, hits live API)
qa_use_cases.py      # Use case QA (26 tests covering every MCP_OVERVIEW.md prompt)
MCP_OVERVIEW.md      # Human-facing cover page (use cases, prompts, tool docs)
README.md
CLAUDE.md            # This file
pyproject.toml       # Dependencies: mcp[cli]>=1.2.0, httpx>=0.27.0, python-dotenv>=1.0.0
uv.lock
dist/
```

No `docs/` directory exists. There is no separate API reference file.

## Commands that can run without asking

All of the following are safe to execute without prompting the user:

```
uv run python test_tools.py          # regression suite
uv run python qa_use_cases.py        # use case QA
uv run python -c "import ..."        # syntax checks
uv run python <any script>           # any Python execution via uv
uv sync / uv build                   # dependency install / package build
cat / grep / find / ls               # read-only file inspection
git status / git log / git diff      # read-only git
```

Before deleting files, overwriting significant work, committing, or pushing — stop and explain in plain language what will change and whether it can be undone. See `~/.claude/CLAUDE.md` for the full global rule.

---

## How to run tests
```bash
TIMEPIECE_TOKEN=<token> TIMEPIECE_CALENDAR=10776 uv run python test_tools.py
```
All 8 tests must pass. The test file sets `TIMEPIECE_CALENDAR=10776` as a default via `os.environ.setdefault` before importing the server module, so `DEFAULT_CALENDAR` is correct at import time.

## How to run use case QA
```bash
TIMEPIECE_TOKEN=<token> TIMEPIECE_CALENDAR=10776 uv run python qa_use_cases.py
```
26 use cases covering every example prompt from MCP_OVERVIEW.md. Run this after any formatter or tool change.

## How to syntax-check
```bash
cd /Users/gianni/Desktop/timepiece-mcp && uv run python -c "import timepiece_mcp.server; print('OK')"
```

## How to restart the MCP after code changes
The MCP config is in `~/.claude.json` under `mcpServers.timepiece`. Start a new Claude Code session — it relaunches all MCP servers on startup. Or use `/mcp` in Claude Code to check status.

The entry-point script registered in `pyproject.toml` is `timepiece-mcp` → `timepiece_mcp.server:main`.

## Environment variables
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TIMEPIECE_TOKEN` | Yes | `""` | JWT token from Jira → Timepiece → API Settings → Create Token |
| `TIMEPIECE_CALENDAR` | Recommended | `None` | Numeric calendar ID (e.g. `10776`). Without this, the API uses `normalHours` (24h/day, UTC) which gives wrong results for business-hours teams. |
| `TIMEPIECE_DEFAULT_DAY_LENGTH` | No | `"businessDays"` | Default for `day_length` param across all tools |
| `TIMEPIECE_DEFAULT_VIEW_FORMAT` | No | `"days"` | Default for `view_format` param across all tools |

All four are read at module import time into module-level constants. `TIMEPIECE_DEFAULT_DAY_LENGTH` and `TIMEPIECE_DEFAULT_VIEW_FORMAT` are read but not yet used by input models (models hardcode their own defaults). Both are set in `~/.claude.json` under `mcpServers.timepiece.env`.

## Authentication
Token is passed as `tisjwt` query parameter on every GET request, or in the form body on POST requests. The `_build_params()` helper injects it automatically for GET. The `_post()` helper injects it in the form data for POST.

If `TIMEPIECE_TOKEN` is empty, `_build_params()` and `_post()` both raise `ValueError` immediately with a helpful message. The server still starts (with a stderr warning) but every tool call will return a configuration error.

## Architecture decisions and WHY

### Single file (server.py)
All tools, models, enums, helpers, and formatters are in one file. FastMCP with stdio transport. No HTTP server, no database. Layout order: enums → shared helpers → response parsers → markdown formatters → input models → tools → entry point.

### Calendar resolution
The API requires a `calendar` param for correct duration calculation. Without it, the API falls back to `normalHours` (24h/day, UTC), producing wrong values for business-hours calendars.

- `DEFAULT_CALENDAR` is read from `TIMEPIECE_CALENDAR` env var (should be `"10776"`)
- `_resolve_calendar(value)` async helper:
  - `None` → returns `None` (no override, API uses its default)
  - Numeric string → returns as-is
  - Non-numeric string → calls `GET /rest/calendar/search?name=...&searchType=exact` to resolve to an ID
  - Falls back to returning the raw value if search fails
- All 5 data tools call `await _resolve_calendar(params.calendar or DEFAULT_CALENDAR)` before making their main API call
- `timepiece_list_calendars` and `timepiece_search_calendar` do not call `_resolve_calendar` (they ARE the calendar discovery tools)

### HTTP helpers
| Helper | Method | Timeout | Auth location | Use for |
|--------|--------|---------|---------------|---------|
| `_get(endpoint, params)` | GET | 30s | `tisjwt` query param | Single issue, calendar endpoints |
| `_post(endpoint, data)` | POST form-encoded | 60s | `tisjwt` form body | list2, aggregation |
| `_get_binary(endpoint, params)` | GET | 90s | `tisjwt` query param | smallexport (binary file download) |

### POST for list2 and aggregation
`/rest/list2` and `/rest/aggregation` use POST with `application/x-www-form-urlencoded` because:
1. JQL queries can be long and hit GET URL length limits
2. `tisjwt` token goes in the form body (not query string) for POST calls
Required form fields: `filterType=customjql`, `customjql=<JQL>`, plus the usual params.

### Export returns file path, not inline data
`/rest/smallexport` returns raw binary bytes (XLS/XLSX/CSV). The tool saves to `/tmp/timepiece-export-{timestamp}.{ext}` and returns the path + metadata string. Never call `.json()` on the response — use `.content` for binary. This endpoint uses GET (not POST), unlike list2/aggregation.

### Removed tools (history)
`timepiece_get_issues` (looped single-issue calls — slow, wrong) and an earlier `timepiece_export_report` stub were removed. They were replaced by `timepiece_list_issues` (POST `/rest/list2`) and `timepiece_export_sync` (GET `/rest/smallexport`).

## Tools reference

| Tool name | Endpoint | Method | Input model | Key params |
|-----------|----------|--------|-------------|------------|
| `timepiece_get_issue` | `/rest/issue` | GET | `GetIssueInput` | `issue_key`, `columns_by`, `calendar`, `day_length`, `view_format`, `statuses`, `response_format` |
| `timepiece_get_issue_expanded` | `/rest/issue/expanded` | GET | `GetIssueExpandedInput` | `issue_key`, `calendar`, `day_length`, `view_format`, `trim_history_start_date`, `trim_history_end_date`, `response_format` |
| `timepiece_list_issues` | `/rest/list2` | POST | `ListIssuesInput` | `jql`, `columns_by`, `calendar`, `day_length`, `view_format`, `statuses`, `page_size` (1-1000, default 100) |
| `timepiece_aggregate` | `/rest/aggregation` | POST | `AggregateInput` | `aggregation_type`, `jql`, `columns_by`, `calendar`, `day_length`, `view_format`, `statuses`, `dbs_metrics` |
| `timepiece_list_calendars` | `/rest/calendar` | GET | `ListCalendarsInput` | `response_format` |
| `timepiece_search_calendar` | `/rest/calendar/search` | GET | `SearchCalendarInput` | `name`, `search_type` (`exact`\|`contain`), `max_results` |
| `timepiece_export_sync` | `/rest/smallexport` | GET | `ExportSyncInput` | `jql`, `output_type` (`xlsx`\|`csv`), `columns_by`, `calendar`, `day_length`, `view_format`, `statuses` |

All tools return `str`. All data tools support `response_format` = `markdown` (default) or `json`.

### Enums
```python
DayLength:      BUSINESS_DAYS="businessDays", CALENDAR_DAYS="calendarDays"
ViewFormat:     DAYS="days", HOURS="hours", MINUTES="minutes", SECONDS="seconds"
ColumnsBy:      STATUS_DURATION="statusDuration", ASSIGNEE_DURATION="assigneeDuration",
                STATUS_DURATION_BY_ASSIGNEE="statusDurationByAssignee",
                ASSIGNEE_DURATION_BY_STATUS="assigneeDurationByStatus",
                DURATION_BETWEEN_STATUSES="durationBetweenStatuses",
                STATUS_COUNT="statusCount", TRANSITION_COUNT="transitionCount"
AggregationType: AVERAGE="average", SUM="sum", MEDIAN="median", STANDARD_DEVIATION="standardDeviation"
ExportOutputType: XLSX="xlsx", CSV="csv"
ResponseFormat:  MARKDOWN="markdown", JSON="json"
```

### Input model conventions
All input models use `ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")`. `issue_key` fields have a `@field_validator` that calls `.upper()`. Issue key pattern: `r"^[A-Z][A-Z0-9_]+-\d+$"`.

## API response shapes — critical knowledge

### GET /rest/issue and POST /rest/list2
```json
{
  "table": {
    "header": {
      "valueColumns": [{"id": "10041", "value": "Blocked"}, ...]
    },
    "body": {
      "rows": [{
        "headerColumns": [{"id": "issuekey", "value": "BAU-278"}, {"id": "summary", "value": "..."}],
        "valueColumns": [{"id": "10041", "value": "9.35", "raw": "269376188", "count": "1"}]
      }]
    }
  }
}
```
- `value` is the formatted duration string (e.g. `"9.35"`)
- `raw` is milliseconds as a string
- `count` is visit count as a string
- `value` of `"-"` means zero time in that status — the formatters skip these rows

### GET /rest/issue/expanded
The response has the same outer `table` structure, but each row has an `expanded` key:
```json
{
  "table": { "header": {...}, "body": { "rows": [{ ..., "expanded": {
    "stats": {
      "visitCounts":   [{"statusId": 10041, "value": 1}, ...],
      "totalValues":   [{"statusId": 10041, "value": 269376188}, ...],
      "averageValues": [{"statusId": 10041, "value": 269376188}, ...],
      "minValues":     [{"statusId": 10041, "value": 269376188}, ...],
      "maxValues":     [{"statusId": 10041, "value": 269376188}, ...]
    },
    "rows": [
      {"uniqueDate": "16/Dec/25 12:20 PM", "statusId": 10420, "value": 10117655, "transitionedBy": "..."}
    ]
  }}]}},
  "calendar": {"dailyWorkingHours": 8.0, ...},
  "includedStatuses": [...],
  "excludedStatuses": [...]
}
```
IMPORTANT: `stats.*` values are **lists of `{statusId, value}` objects**, NOT dicts keyed by statusId. The formatter builds lookup dicts via: `{str(e["statusId"]): e["value"] for e in stats.get("visitCounts", [])}`.

- `expanded.rows[].value` is milliseconds (integer, not ms-as-string)
- `expanded.rows[].transitionedBy` may be absent, defaulting to `"-"`
- Convert ms to days: `ms / (dailyWorkingHours * 3_600_000)` — `dailyWorkingHours` comes from `data["calendar"]["dailyWorkingHours"]` (typically 8.0)
- Status ID → name mapping: combine `data["includedStatuses"]` + `data["excludedStatuses"]`; the formatter uses `col_map` from `_get_col_map(table)` which reads `header.valueColumns`

### POST /rest/aggregation
Same `table` shape as list2, but:
- `header.headerColumns` is empty (no issue key column — it's an aggregate)
- Each row's `valueColumns` has the aggregated value
- `row["issueCount"]` at the row level (integer or string) holds the count of issues
- For per-group aggregation, `row["headerColumns"]` will have the group label (e.g. assignee)

### GET /rest/calendar
Returns a list directly (not wrapped in an object):
```json
[{"id": null, "name": "normalHours", ...}, {"id": 10776, "name": "Default Calendar Settings", ...}]
```
Note: the 24/7 `normalHours` calendar has `id: null`.

### GET /rest/calendar/search
The actual API response observed in `_resolve_calendar`:
- May return a list directly (handled by `isinstance(results, list)`)
- May return a dict with `calendars`, `results`, or similar key (handled by `isinstance(results, dict)`)
- The tool `timepiece_search_calendar` passes the response to `_format_calendars_markdown`, which handles both `list` and `dict` shapes

### GET /rest/smallexport
Returns raw binary bytes. Content-Type is `text/csv` or `application/vnd.ms-excel`. Use `response.content`, NOT `response.json()`. Saved to `/tmp/timepiece-export-{timestamp}.{ext}`.

## Markdown formatters
All formatters live in `server.py` and return `str`:

| Formatter | Used by |
|-----------|---------|
| `_format_issue_markdown(data, issue_key, view_format)` | `timepiece_get_issue` |
| `_format_issue_expanded_markdown(data, issue_key, view_format)` | `timepiece_get_issue_expanded` |
| `_format_list_issues_markdown(data, view_format, page_size)` | `timepiece_list_issues` |
| `_format_aggregate_markdown(data, aggregation_type, jql, view_format)` | `timepiece_aggregate` |
| `_format_calendars_markdown(data)` | `timepiece_list_calendars`, `timepiece_search_calendar` |

`_ms_to_view_format(raw_ms, view_format, daily_working_hours=8.0)` is a pure helper used by the expanded formatter to convert milliseconds → days/hours/minutes/seconds.

Table parsing helpers: `_extract_table`, `_get_col_map`, `_get_ordered_col_ids`, `_get_row_key`, `_get_row_values`.

## QA baseline values (regression testing)
Use these to validate that tools return correct data. Verified against Jira UI values. Calendar: ID `10776` = "Default Calendar Settings", Europe/London, Mon–Fri 09:15–17:15, 8h/day.

**BAU-278** (FRA Risk Rating — Reduce Risk Rating on Completion of Actions):
| Status | Days | Visits |
|--------|------|--------|
| Development | ~12.27 | 7 |
| Done | ~18.77–19.0 | 1 |
| Blocked | ~9.35 | 1 |
| Triage | ~6.80 | 1 |
| Waiting | ~3.51 | 6 |
| Ready for Development | ~14.25 | 2 |

**BAU-308** (FRA - Display Hand-In vs Current Action Risk Rating):
| Status | Days | Visits |
|--------|------|--------|
| Development | ~11.50 | 5 |
| Done | ~43.75 | 1 |
| Review | ~1.47 | 1 |
| QA Testing | ~0.21 | 5 |

## Common failure modes and how to debug

### "Unknown: 0 days" in output
Caused by a formatter hitting the fallback branch. The formatter uses `data["table"]["body"]["rows"][0]["valueColumns"]`. If you see "Unknown", the API response shape has changed — add `response_format="json"` to the tool call to inspect raw output.

### All durations are too large / not business-day aligned
Calendar is not being passed. Check `DEFAULT_CALENDAR` is set (requires `TIMEPIECE_CALENDAR=10776` in env). The API silently falls back to `normalHours` (24h/day, UTC) if calendar is missing or null.

### 401 Unauthorized
Token expired or wrong. Go to Jira → Apps → Timepiece → API Settings to generate a new token. Update `~/.claude.json`.

### 408 Timeout on export or aggregation
The JQL matches too many issues for the server-side time limit (60s for aggregation, 90s timeout for export). Split into smaller date ranges or use a more specific JQL filter.

### POST /rest/list2 or /rest/aggregation returns 400
Check that `filterType=customjql` is in the form body and `customjql` contains the JQL. The `tisjwt` token must be in the form body (not query params) for POST calls — `_post()` handles this automatically.

### timepiece_get_issue_expanded shows wrong durations
The ms-to-days conversion uses `data["calendar"]["dailyWorkingHours"]` from the response (8.0 for Default Calendar). If this key is missing, the code falls back to the default `8.0`, so the output will still be reasonable, but log a warning and check the response shape.

### Tests fail to import
The test file does `os.environ.setdefault("TIMEPIECE_CALENDAR", "10776")` BEFORE importing from `timepiece_mcp.server`. This is required because `DEFAULT_CALENDAR` is set at import time. If you restructure the import order, this will break.

## Known API limitations
1. **No server-side duration filtering on /rest/list2**: Cannot ask "tickets where Development > 5 days" — must retrieve all and filter client-side.
2. **Status name lookup requires the response**: Status IDs are integers; names come from `header.valueColumns` in the API response — there is no standalone "get status name by ID" endpoint in Timepiece.
3. **Aggregation/export timeout (408)**: Server-side limit. For large projects, filter JQL by date range.
4. **Async export not implemented**: `/rest/asyncexport` (start/poll/download) is deferred to a future release. Only synchronous export via `/rest/smallexport` is implemented.
5. **Unsupported JQL functions**: `startOfWeek()`, `startOfMonth()`, `startOfQuarter()`, `startOfYear()` are NOT supported by the Timepiece API and return HTTP 400. Use explicit dates instead: `resolved >= '2026-01-01'`.

## How to add a new tool
1. Add a Pydantic input model class (follow existing pattern: `ConfigDict`, `Field`, `@field_validator` as needed)
2. Add the async tool function decorated with `@mcp.tool(name="...", annotations={...})`
3. Use `await _resolve_calendar(params.calendar or DEFAULT_CALENDAR)` to handle the calendar param
4. Use `_get()` for GET, `_post()` for POST (form-encoded), `_get_binary()` for file downloads
5. Wrap everything in `try/except Exception as e` and `return _handle_error(e)` on failure
6. Add a Markdown formatter function (`_format_*_markdown`) if the response shape is new
7. Add a test case to `test_tools.py` following the existing `check(name, output, [conditions])` pattern
8. Run tests: `TIMEPIECE_TOKEN=<token> TIMEPIECE_CALENDAR=10776 uv run python test_tools.py`
9. Add use case tests to `qa_use_cases.py` covering the natural-language prompts from MCP_OVERVIEW.md for your new tool.
