# Timepiece REST API Reference

Technical reference for the OBSS Timepiece REST API as used by this MCP server.
Audience: a Claude session debugging, fixing, or extending a tool.

- Official docs: https://documentation.obss.tech/timepiece-time-in-status-for-jira-cloud/latest/endpoints

---

## Base URL and Auth

**Base URL:** `https://tis.obss.io/rest`

**Auth token:** passed as the `tisjwt` parameter containing the JWT.

- **GET requests:** `tisjwt` is a query parameter — injected automatically by `_build_params()`.
- **POST requests:** `tisjwt` must go in the **form-encoded body**, NOT as a query param. This is the single most common integration mistake. The `_post()` helper handles this correctly.

If `TIMEPIECE_TOKEN` is empty, both helpers raise `ValueError` immediately before making any HTTP call.

### HTTP helpers (server.py)

| Helper | Method | Timeout | Auth location | Used for |
|--------|--------|---------|---------------|----------|
| `_get(endpoint, params)` | GET | 30s | `tisjwt` query param | Single issue, calendar endpoints |
| `_post(endpoint, data)` | POST form-encoded | 60s | `tisjwt` form body | list2, aggregation |
| `_get_binary(endpoint, params)` | GET | 90s | `tisjwt` query param | smallexport (binary download) |

All values in `_post` form data are cast to `str`. `None` values are omitted by both helpers.

---

## Endpoints used by this MCP

---

### GET /rest/issue

**Purpose:** Time-in-status totals for a single Jira issue.
**Used by:** `timepiece_get_issue`
**MCP param name → API param name:** `issue_key` → `issueKey`, `columns_by` → `columnsBy`, `day_length` → `dayLength`, `view_format` → `viewFormat`

**Parameters (all as query params):**

| Name | Required | Example | Notes |
|------|----------|---------|-------|
| `issueKey` | Yes | `BAU-278` | Validated uppercase by Pydantic model |
| `columnsBy` | Yes | `statusDuration` | Also accepts `assigneeDuration`, `statusDurationByAssignee`, `assigneeDurationByStatus`, `durationBetweenStatuses`, `statusCount`, `transitionCount` |
| `calendar` | Recommended | `10776` | Numeric ID. Omit → API uses `normalHours` (24h/day UTC). Wrong for any business-hours team. |
| `dayLength` | Yes | `businessDays` | Or `calendarDays` |
| `viewFormat` | Optional | `days` | `days`, `hours`, `minutes`, `seconds`. Affects `value` string only; `raw` is always ms. |
| `statuses` | Optional | `10001,10041` | Comma-separated status IDs. Omit to return all statuses. Do not hardcode — let the API decide. |
| `tisjwt` | Yes | `<jwt>` | Injected by `_build_params()` |

**Response shape:**

```json
{
  "dateFormat": "dd/MMM/yy",
  "timeZone": "Europe/London",
  "viewFormat": "days",
  "calendar": {
    "id": 10776,
    "name": "Default Calendar Settings",
    "dailyWorkingHours": 8.0,
    "timeZone": "Europe/London",
    "is7x24Calendar": false
  },
  "includedStatuses": [
    {"id": "10001", "name": "Done", "statusCategory": {"name": "Done"}}
  ],
  "excludedStatuses": [],
  "table": {
    "header": {
      "headerColumns": [
        {"id": "issuekey", "value": "Key"},
        {"id": "summary", "value": "Summary"}
      ],
      "valueColumns": [
        {"id": "10041", "value": "Blocked", "isConsolidated": false}
      ]
    },
    "body": {
      "rows": [{
        "headerColumns": [
          {"id": "issuekey", "value": "BAU-278"},
          {"id": "summary", "value": "FRA Risk Rating..."}
        ],
        "valueColumns": [
          {
            "id": "10041",
            "value": "9.3533398611",   // formatted duration string OR "-"
            "raw": "269376188",         // milliseconds as string
            "count": "1"               // visit count as string; ABSENT when value is "-"
          }
        ],
        "currentState": [
          {"id": "10001", "value": "19.0", "raw": "547200000"}
          // the status the issue is currently in and cumulative time there
        ]
      }]
    }
  }
}
```

**Gotchas:**

- `value` of `"-"` means the issue never entered that status. The formatter skips these. `raw` and `count` are absent when `value` is `"-"`.
- `currentState` is a list (one entry) showing the issue's current status and total accumulated time.
- `header.valueColumns[].id` is the status ID **as a string** (e.g. `"10041"`). Match against this when building col maps.
- Without `calendar`, the API silently uses `normalHours` (24h/day, UTC). Results will be 3× larger than expected for an 8h/day calendar.
- The `_format_issue_markdown` formatter reads `table.body.rows[0]` — always a single-element list for this endpoint.

---

### GET /rest/issue/expanded

**Purpose:** Full per-visit statistics and chronological transition history for a single issue.
**Used by:** `timepiece_get_issue_expanded`

The MCP hardcodes `columnsBy=statusDurationExpanded` for this endpoint — this is not exposed as a user parameter.

**Parameters (all as query params):**

| Name | Required | Example | Notes |
|------|----------|---------|-------|
| `issueKey` | Yes | `BAU-308` | |
| `columnsBy` | Yes | `statusDurationExpanded` | Always this value; hardcoded in the tool |
| `calendar` | Recommended | `10776` | Same importance as /rest/issue |
| `dayLength` | Optional | `businessDays` | Default: `businessDays` |
| `viewFormat` | Optional | `days` | Affects nothing in the raw response — conversion is done client-side using `_ms_to_view_format()` |
| `trimHistoryStartDate` | Optional | `2025-01-01` | Format: `yyyy-MM-dd` or `yyyy-MM-dd hh:mm`. Trims the transition history rows. |
| `trimHistoryEndDate` | Optional | `2025-12-31` | Same format. |
| `tisjwt` | Yes | `<jwt>` | |

**Response shape:**

```json
{
  "calendar": {
    "dailyWorkingHours": 8.0,
    "timeZone": "Europe/London"
  },
  "includedStatuses": [{"id": "10001", "name": "Done", "statusCategory": {...}}],
  "excludedStatuses": [],
  "table": {
    "header": {
      "headerColumns": [{"id": "issuekey", "value": "Key"}],
      "valueColumns": [{"id": "10041", "value": "Blocked"}]
    },
    "body": {
      "rows": [{
        "headerColumns": [{"id": "issuekey", "value": "BAU-308"}],
        "expanded": {
          "stats": {
            "visitCounts":   [{"statusId": 3, "value": 5}],    // list, NOT dict
            "totalValues":   [{"statusId": 3, "value": 331288031}],
            "averageValues": [{"statusId": 3, "value": 66257606}],
            "minValues":     [{"statusId": 3, "value": 12345000}],
            "maxValues":     [{"statusId": 3, "value": 150000000}]
          },
          "rows": [
            {
              "uniqueDate": "16/Dec/25 12:20 PM",  // human-readable; no raw epoch
              "statusId": 10420,                    // integer (not string)
              "value": 10117655,                    // ms in PREVIOUS status before this transition
              "transitionedBy": "John Smith"        // may be absent; default to "-"
            }
          ]
        }
      }]
    }
  }
}
```

**Gotchas — this endpoint has the most traps:**

- `stats.*` fields are **lists** of `{"statusId": int, "value": int}` objects, NOT dicts keyed by statusId. The formatter builds lookup dicts:
  ```python
  visit_counts = {str(e["statusId"]): e["value"] for e in stats.get("visitCounts", [])}
  ```
- `statusId` in `expanded.rows[]` is an **integer** (e.g. `10420`), but in `header.valueColumns[].id` it is a **string** (e.g. `"10420"`). The formatter uses `str(tr.get("statusId", ""))` when looking up names in `col_map`.
- `expanded.rows[].value` is ms spent in the **previous** status before this transition — NOT the time in `statusId`. The history reads as: "at `uniqueDate`, the issue moved into `statusId`; it spent `value` ms in whatever status it was in before."
- `uniqueDate` is already a human-readable formatted string. There is no raw epoch timestamp in the expanded response.
- `transitionedBy` may be absent — use `.get("transitionedBy", "-")`.
- ms → business days conversion: `ms / (dailyWorkingHours * 3_600_000)`. Use `data["calendar"]["dailyWorkingHours"]` (typically `8.0`). The helper is `_ms_to_view_format(raw_ms, view_format, daily_working_hours)`.
- `col_map` built from `header.valueColumns` only contains **included** statuses. If a `statusId` from `expanded.rows` is not in `col_map`, the formatter falls back to `f"Status {sid}"`.

---

### POST /rest/list2

**Purpose:** Time-in-status for multiple issues filtered by JQL.
**Used by:** `timepiece_list_issues`

**Key rule: POST with `application/x-www-form-urlencoded`. The `tisjwt` token goes in the form body, never in query params.**

**Form body parameters:**

| Name | Required | Example | Notes |
|------|----------|---------|-------|
| `tisjwt` | Yes | `<jwt>` | In body. Injected by `_post()`. |
| `filterType` | Yes | `customjql` | Always `customjql` — covers all use cases via JQL |
| `customjql` | Yes | `project = BAU AND sprint in openSprints()` | Full JQL string |
| `columnsBy` | Yes | `statusDuration` | Same enum as /rest/issue |
| `calendar` | Recommended | `10776` | Numeric ID as string |
| `dayLength` | Yes | `businessDays` | |
| `viewFormat` | Optional | `days` | |
| `statuses` | Optional | `10001,10041` | Comma-separated; omit for all |
| `pageSize` | Optional | `100` | 1–1000, default 100. Sent as string. |
| `nextPageToken` | Optional | `eyJ...` | Pagination token from previous response |

**Response shape:**

```json
{
  "pageSize": 100,
  "nextPageToken": "eyJ...",   // present when more pages exist; absent (not null) on last page
  "table": {
    "header": {
      "headerColumns": [
        {"id": "issuekey", "value": "Key"},
        {"id": "summary", "value": "Summary"}
      ],
      "valueColumns": [
        {"id": "3", "value": "Development"}
      ]
    },
    "body": {
      "rows": [
        {
          "headerColumns": [
            {"id": "issuekey", "value": "BAU-278"},
            {"id": "summary", "value": "..."}
          ],
          "valueColumns": [
            {"id": "3", "value": "12.27", "raw": "353518164", "count": "7"}
          ]
        }
      ]
    }
  }
}
```

**Gotchas:**

- `nextPageToken` is **absent** (not `null`) on the last page. Check with `data.get("nextPageToken")`.
- The current MCP does not implement pagination for this tool — it returns one page. If `nextPageToken` is present in a response, there are more results.
- No server-side duration filtering: cannot ask "show only issues where Development > 5 days". Must retrieve all results and filter client-side.
- `filterType=customjql` with JQL handles all cases: project, sprint by name, assignee, date range. No need to use other `filterType` values.
- Summary strings longer than 60 characters are truncated to 57 + `"..."` by `_format_list_issues_markdown`.

---

### POST /rest/aggregation

**Purpose:** Statistical aggregation (average, median, sum, standard deviation) across a filtered issue set.
**Used by:** `timepiece_aggregate`

**Key rule: POST with `application/x-www-form-urlencoded`. Same auth pattern as list2.**

**Form body parameters:**

| Name | Required | Example | Notes |
|------|----------|---------|-------|
| `tisjwt` | Yes | `<jwt>` | In body |
| `aggregationType` | Yes | `average` | `average`, `median`, `sum`, `standardDeviation` |
| `filterType` | Yes | `customjql` | Always `customjql` |
| `customjql` | Yes | `project = BAU AND created >= "2025-01-01"` | |
| `columnsBy` | Yes | `statusDuration` | `statusDuration`, `assigneeDuration`, `statusDurationByAssignee`, `assigneeDurationByStatus`, `durationBetweenStatuses`, `statusCount`, `transitionCount` |
| `calendar` | Recommended | `10776` | |
| `dayLength` | Yes | `businessDays` | |
| `viewFormat` | Optional | `days` | |
| `statuses` | Optional | `10001,10041` | |
| `dbsMetrics` | Optional | `[{"name":"Cycle Time","startAt":{"type":"status","ids":[3]},"stopAt":{"type":"status","ids":[10001]}}]` | JSON string for `durationBetweenStatuses` reports. Defines lead/cycle time metrics. |

**Response shape:**

```json
{
  "table": {
    "header": {
      "headerColumns": [],   // ALWAYS EMPTY for aggregation — no issue key column
      "valueColumns": [{"id": "3", "value": "Development"}]
    },
    "body": {
      "rows": [{
        "headerColumns": [],   // empty for overall aggregate; has group label for per-group
        "issueCount": 42,      // at row level, not inside valueColumns
        "valueColumns": [
          {"id": "3", "value": "8.5", "raw": "244800000"}
        ]
      }]
    }
  }
}
```

**Gotchas:**

- `header.headerColumns` is **empty** — there is no issue key column. Do not try to call `_get_row_key()` on aggregation rows meaningfully.
- `issueCount` is at the **row level** (`row.get("issueCount")`), not inside `valueColumns`. Extract it directly from the row dict.
- `valueColumns` in aggregation rows may lack a `count` field. The formatter falls back to `str(issue_count)`.
- For per-group aggregation (e.g. `columnsBy=assigneeDuration`), there will be one row per group. Each row's `headerColumns` will contain the group label (e.g. assignee name). The formatter reads: `h_cols.get("assignee") or h_cols.get("issuekey") or next(...)`.
- **408 Timeout:** server-side hard limit of 60s. If hit, narrow the JQL date range.
- **429 Rate limit:** only one aggregation job per user at a time. If a previous request is still running, a new one returns 429.
- `dbsMetrics` full format for lead/cycle time:
  ```json
  [
    {
      "name": "Cycle Time",
      "startAt": {"type": "status", "ids": [3]},
      "stopAt": {"type": "status", "ids": [10001]},
      "pauseAt": {"type": "status", "ids": [10041]}
    }
  ]
  ```

---

### GET /rest/calendar

**Purpose:** List all configured calendars.
**Used by:** `timepiece_list_calendars`

**Parameters:** only `tisjwt` (query param).

**Response shape — a JSON array directly (not wrapped in an object):**

```json
[
  {
    "id": null,               // the built-in 24/7 normalHours calendar always has id=null
    "name": "normalHours",
    "timeZone": "UTC",
    "dailyWorkingHours": 24.0,
    "is7x24Calendar": true,
    "isDefault": false
  },
  {
    "id": 10776,
    "name": "Default Calendar Settings",
    "timeZone": "Europe/London",
    "dailyWorkingHours": 8.0,
    "is7x24Calendar": false,
    "isDefault": true,
    "workingTimes": [
      {
        "weekday": "MONDAY",
        "start": 33300000,    // milliseconds since midnight (33300000ms = 09:15)
        "end": 62100000       // milliseconds since midnight (62100000ms = 17:15)
      }
    ],
    "holidays": [
      {"name": "", "date": "25/Dec/25", "recurring": true}
    ]
  }
]
```

**Gotchas:**

- The response is a **raw list** — not wrapped in `{"elements": [...]}` or any object. This is different from `/rest/calendar/search`.
- `normalHours` calendar has `id: null`. The `_format_calendars_markdown` formatter renders this as `"-"` for the ID column.
- `workingTimes[].start` and `workingTimes[].end` are **milliseconds since midnight**. Example: `33300000 / 3600000 = 9.25h = 09:15`.

---

### GET /rest/calendar/search

**Purpose:** Find a calendar by name.
**Used by:** `timepiece_search_calendar` tool and `_resolve_calendar()` internal helper.

**Parameters:**

| Name | Required | Example | Notes |
|------|----------|---------|-------|
| `name` | Optional | `Default Calendar Settings` | Name to search |
| `searchType` | Optional | `exact` | `exact` or `contain` |
| `pageNumber` | Optional | `0` | Default 0 |
| `maxResults` | Optional | `10` | 1–100, default 10. MCP sends as `maxResults`. |
| `tisjwt` | Yes | `<jwt>` | Query param |

**Response shape — paginated object (different from /rest/calendar which returns a list):**

```json
{
  "elements": [
    {
      "id": 10776,
      "name": "Default Calendar Settings",
      "timeZone": "Europe/London",
      "dailyWorkingHours": 8.0,
      "isDefault": true
    }
  ],
  "pageNumber": 0,
  "pageSize": 1,
  "total": 1,
  "last": true
}
```

**Gotchas:**

- Different response shape from `GET /rest/calendar`. This one returns `{"elements": [...]}`. The other returns `[...]` directly.
- `_resolve_calendar()` handles both shapes defensively: checks `isinstance(results, list)` first, then `isinstance(results, dict)` and tries `results.get("calendars") or results.get("results")`. Note: this does NOT try `results.get("elements")` — if the API returns `{"elements": [...]}` to `_resolve_calendar`, the calendar will not be found and it falls back to the raw name string. This is a known limitation of the current code.
- `_format_calendars_markdown` handles both shapes: `isinstance(data, list)` → iterate directly; `isinstance(data, dict)` → tries `data.get("calendars") or data.get("results") or data.get("data")`. Does not check `"elements"` key — again a gap for the search endpoint.
- `timepiece_search_calendar` passes the raw response to `_format_calendars_markdown`. If the table renders empty, the response shape likely has `"elements"` and the formatter's dict fallback isn't finding it.

---

### GET /rest/smallexport

**Purpose:** Synchronous file export (CSV/XLSX) for a set of issues.
**Used by:** `timepiece_export_sync`

Note: This is a GET request (unlike list2/aggregation). `tisjwt` goes in the query params.

**Parameters (all as query params):**

| Name | Required | Example | Notes |
|------|----------|---------|-------|
| `filterType` | Yes | `customjql` | Always `customjql` |
| `customjql` | Yes | `project = BAU` | JQL |
| `columnsBy` | Yes | `statusDuration` | |
| `outputType` | Yes | `xlsx` | `xlsx`, `csv` (`xls` may work but not exposed in MCP) |
| `calendar` | Recommended | `10776` | |
| `dayLength` | Yes | `businessDays` | |
| `viewFormat` | Optional | `days` | |
| `statuses` | Optional | `10001,10041` | |
| `tisjwt` | Yes | `<jwt>` | Query param (GET request) |

**Response:** Raw binary bytes. Content-Type is `text/csv` or `application/vnd.ms-excel`.

The MCP uses `_get_binary()` (90s timeout) which returns `response.content` directly. The tool saves the bytes to `/tmp/timepiece-export-{timestamp}.{ext}` and returns the file path string — it does not return the file contents inline.

**Gotchas:**

- **Never call `.json()` on this response** — it is binary data. `httpx` will raise an error.
- **408 Timeout:** 60s server-side limit. For large exports, split the JQL by date range.
- The 90s `_get_binary` timeout is intentional — larger than the 60s `_post` timeout — because file generation can be slow before the response bytes start arriving.
- Export file path format: `/tmp/timepiece-export-<unix_timestamp>.<ext>` (e.g. `/tmp/timepiece-export-1742000000.xlsx`).

---

## Cross-cutting concerns

### Calendar resolution: `_resolve_calendar(value)`

All data tools call `await _resolve_calendar(params.calendar or DEFAULT_CALENDAR)` before their main API call. Behaviour:

| Input | Behaviour |
|-------|-----------|
| `None` | Returns `None`; the API uses its own default (normalHours) |
| Numeric string e.g. `"10776"` | Returns as-is |
| Named string e.g. `"Default Calendar Settings"` | Calls `GET /rest/calendar/search?name=...&searchType=exact`, returns first result's ID as string. Falls back to the raw string on any error. |

`DEFAULT_CALENDAR` is read from `TIMEPIECE_CALENDAR` env var **at module import time**. Tests must set `os.environ["TIMEPIECE_CALENDAR"]` before importing `timepiece_mcp.server`.

### Pagination

Only `timepiece_list_issues` has pagination support. It sends `pageSize` but does NOT automatically fetch subsequent pages. If a response contains `nextPageToken`, the caller must make a follow-up call (not currently wired into the MCP tool).

### Error handling: `_handle_error(e)`

All tool functions catch `Exception` and return `_handle_error(e)` as a string. HTTP errors are mapped:

| Status | Message |
|--------|---------|
| 401 | Token invalid or expired |
| 403 | Forbidden |
| 404 | Issue key or endpoint not found |
| 429 | Rate limit exceeded |
| Other | `HTTP {status}: {body[:200]}` |
| `TimeoutException` | Timed out |
| `ConnectError` | Cannot reach tis.obss.io |
| `ValueError` | Configuration error (missing token) |

---

## Table parsing helpers

These functions in `server.py` operate on the `table` dict from any API response:

| Function | Input | Returns |
|----------|-------|---------|
| `_extract_table(data)` | Full API response dict | `data["table"]` or `None` |
| `_get_col_map(table)` | `table` dict | `{col_id_str: col_name_str}` from `header.valueColumns` |
| `_get_ordered_col_ids(table)` | `table` dict | `[col_id_str, ...]` in header order |
| `_get_row_key(row)` | A single row dict | `(issue_key_str, summary_str)` |
| `_get_row_values(row)` | A single row dict | `{col_id_str: value_cell_dict}` where each cell has `value`, `raw`, `count` keys |

`_ms_to_view_format(raw_ms, view_format, daily_working_hours=8.0)` converts an integer millisecond value to the requested unit. Divisors: days = `daily_working_hours * 3_600_000`, hours = `3_600_000`, minutes = `60_000`, seconds = `1_000`.

---

## Status IDs reference (BAU project)

Observed in actual API responses. For debugging only — do not hardcode as required params. Let the API return all statuses by default.

| ID | Name | Category |
|----|------|----------|
| 10420 | Backlog | To Do |
| 10717 | Triage | To Do |
| 10000 | Ready for Development | To Do |
| 3 | Development | In Progress |
| 10009 | Review | In Progress |
| 10652 | Ready for Test | In Progress |
| 10008 | QA Testing | In Progress |
| 10041 | Blocked | In Progress |
| 10023 | UAT | In Progress |
| 10653 | Ready for UAT | In Progress |
| 10948 | Waiting | In Progress |
| 10486 | Ready for Launch Prep | In Progress |
| 10655 | Ready to Deploy | In Progress |
| 10001 | Done | Done |

Status names are not available from a standalone lookup endpoint. They come from `header.valueColumns` in the API response. Build the name map from whichever response you have: `{col["id"]: col["value"] for col in table["header"]["valueColumns"]}`.

---

## QA baseline values

Verified against Jira UI. Calendar: ID `10776` = "Default Calendar Settings", Europe/London, Mon–Fri 09:15–17:15, 8h/day.

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

---

## Common failure modes

### "Unknown: 0 days" in output
Formatter hit the fallback branch. The `col_map` lookup returned nothing. Add `response_format="json"` to the tool call and inspect `table.header.valueColumns` — the status ID type may have changed (e.g. int vs string).

### All durations are too large (not business-day aligned)
`DEFAULT_CALENDAR` is `None`. The API silently used `normalHours` (24h/day, UTC). Set `TIMEPIECE_CALENDAR=10776` in the MCP env config. Verify with `timepiece_list_calendars`.

### 401 Unauthorized
Token expired. Jira → Apps → Timepiece → API Settings → generate new token → update `~/.claude.json` → restart Claude Code session.

### 408 Timeout on aggregation or export
JQL matches too many issues for the 60s server limit. Narrow with a date range: `AND created >= "2025-01-01"`.

### POST /rest/list2 or /rest/aggregation returns 400
Check: (1) `filterType=customjql` is in the form body, (2) `customjql` is non-empty, (3) `tisjwt` is in the form body (not query params). `_post()` handles all of this automatically — if you bypassed it, that's the problem.

### timepiece_get_issue_expanded shows wrong durations
`data["calendar"]["dailyWorkingHours"]` is missing or zero. Check the raw response with `response_format="json"`. The formatter defaults to `8.0` if the key is absent, so output will be approximately correct, but log the shape change.

### timepiece_search_calendar returns empty table
The API response likely has `{"elements": [...]}` but `_format_calendars_markdown` does not check the `"elements"` key. The formatter checks `"calendars"`, `"results"`, and `"data"` for dict responses. Use `response_format="json"` to confirm the shape, then check/patch the formatter's dict fallback keys.

### _resolve_calendar fails to resolve a calendar name
`_resolve_calendar` tries `results.get("calendars") or results.get("results")` on a dict response — it does not try `"elements"`. If the search returns `{"elements": [...]}`, the name lookup silently fails and the raw name string is used as the calendar param, which the API will reject or ignore. Use a numeric calendar ID in `TIMEPIECE_CALENDAR` to avoid this path entirely.
