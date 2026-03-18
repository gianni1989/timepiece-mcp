# Timepiece MCP Server

## Overview

The Timepiece MCP server connects Claude to OBSS Timepiece (Time in Status for Jira Cloud), giving delivery managers, engineering leads and PMs a conversational interface for querying how long issues spent in each workflow stage — individually or in bulk across projects, sprints and teams. Rather than clicking through Jira dashboards, you can ask natural language questions and receive structured breakdowns of status durations, transition timelines, rework counts and aggregate metrics. All durations use your configured business calendar (working hours, public holidays, timezone) and return in business days by default.

---

## When to use

Use this MCP when you want to:

- Understand the full lifecycle of a specific ticket — how long it spent in each status and how many times it cycled between stages
- Identify bottlenecks across a project or sprint — which status causes the most delay
- Measure team cycle time and lead time from idea to done
- Compare delivery speed across developers
- Analyse flow efficiency — active work time vs waiting time
- Detect rework — tickets bouncing back from QA or UAT into Development
- Track whether cycle times are improving sprint over sprint
- Export time-in-status data for sprint reviews, retrospectives, or stakeholder reporting

---

## Example prompts

- `How long did PROJ-123 spend in each status?`
- `Show me the full lifecycle of PROJ-456 including how many times it went back into Development`
- `What is the average cycle time for tickets closed in PROJ this sprint?`
- `Which status is causing the biggest delays in project PROJ?`
- `Compare average development time across the team for last sprint`
- `What is our flow efficiency for PROJ this quarter — how much time is active work vs waiting?`
- `How often do our tickets bounce back into Development from QA?`
- `Show me all tickets currently in Development for project PROJ with how long they've been there`
- `Has our average cycle time improved over the last four sprints?`
- `Export a CSV of time-in-status for all tickets resolved in PROJ this month`

---

## Tools

| Tool | Description |
|------|-------------|
| `timepiece_get_issue` | Retrieves total time spent in each workflow status for a single Jira issue, returned as a Status / Duration / Visits table. |
| `timepiece_get_issue_expanded` | Retrieves the full status history of a single issue including visit counts, min/max/average duration per status, and a chronological transition timeline. |
| `timepiece_list_issues` | Retrieves time-in-status for a set of issues defined by a JQL query, returning a matrix of issues × statuses. |
| `timepiece_aggregate` | Computes average, median, sum or standard deviation of time-in-status across any JQL-filtered set of issues; also supports lead time and cycle time via duration-between-statuses metrics. |
| `timepiece_list_calendars` | Lists all Timepiece calendars configured for the Jira instance, including IDs, timezones and working hours. |
| `timepiece_search_calendar` | Finds a calendar by name and returns its ID — used to resolve a calendar name such as "Default Calendar Settings" to a numeric ID. |
| `timepiece_export_sync` | Exports a time-in-status report as CSV or XLSX for any JQL-filtered set of issues, saving the file locally and returning the path. |

---

## Tool Details

### timepiece_get_issue

Returns the total time a single Jira issue spent in each workflow status, expressed as a simple Status / Duration / Visits table. Use this when investigating a specific ticket — retrospective discussions, a stakeholder asking "why did this take so long", or establishing a baseline before deeper analysis. It is the fastest way to get a per-status duration breakdown without the full transition timeline.

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `issue_key` | Yes | — | The Jira issue key, e.g. `BAU-308`. |
| `calendar` | No | `TIMEPIECE_CALENDAR` env var | Numeric calendar ID used for business-hour calculations. |
| `view_format` | No | `days` | Unit for durations: `days`, `hours`, `minutes`, or `seconds`. |
| `day_length` | No | `businessDays` | Whether to count `businessDays` or `calendarDays`. |

**Try asking:**
- `How long did PROJ-123 spend in each status?`
- `Show me the time-in-status breakdown for PROJ-456`
- `How many days was PROJ-789 in Development?`
- `Which status did PROJ-123 spend the most time in?`

---

### timepiece_get_issue_expanded

Returns the complete status history of a single issue: visit counts, and minimum / maximum / average duration for each status, plus a chronological timeline of every transition with timestamps. Use this when you need to understand rework — did the ticket cycle back through a status, how many times, and for how long each time? Also useful for reconstructing the precise delivery timeline of a ticket for an incident review or post-mortem.

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `issue_key` | Yes | — | The Jira issue key, e.g. `BAU-278`. |
| `calendar` | No | `TIMEPIECE_CALENDAR` env var | Numeric calendar ID used for business-hour calculations. |
| `view_format` | No | `days` | Unit for durations: `days`, `hours`, `minutes`, or `seconds`. |
| `day_length` | No | `businessDays` | Whether to count `businessDays` or `calendarDays`. |
| `trim_history_start_date` | No | — | Only include transitions on or after this date (`yyyy-MM-dd`). |
| `trim_history_end_date` | No | — | Only include transitions on or before this date (`yyyy-MM-dd`). |

**Try asking:**
- `How many times did PROJ-456 cycle back into Development?`
- `Show me every status transition for PROJ-123 with timestamps`
- `What was the longest single visit to QA Testing for PROJ-456?`
- `Did PROJ-789 get sent back from UAT, and how many times?`

---

### timepiece_list_issues

Retrieves time-in-status for every issue matching a JQL query, returning a matrix of issues × statuses. Use this for sprint or project-level analysis — for example, seeing all tickets in a sprint alongside their per-status durations in a single view. Note: duration-based filtering (e.g. "tickets where Development > 5 days") is not supported server-side; retrieve the full result set and ask Claude to sort or filter the results after retrieval.

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `jql` | Yes | — | A valid JQL query defining the issue set, e.g. `project = BAU AND sprint in openSprints()`. |
| `calendar` | No | `TIMEPIECE_CALENDAR` env var | Numeric calendar ID used for business-hour calculations. |
| `view_format` | No | `days` | Unit for durations: `days`, `hours`, `minutes`, or `seconds`. |
| `day_length` | No | `businessDays` | Whether to count `businessDays` or `calendarDays`. |
| `columns_by` | No | `statusDuration` | Column grouping for the output matrix. |
| `page_size` | No | `100` | Number of issues per page (1–1000). |

**Try asking:**
- `Show me time-in-status for all tickets in the current sprint of project PROJ`
- `Which tickets closed in PROJ this month spent the most time in Development?`
- `Show me all tickets currently in QA Testing for project PROJ`
- `List time-in-status for all tickets assigned to me closed this sprint`

---

### timepiece_aggregate

Computes a summary statistic — average, median, sum, or standard deviation — of time-in-status across all issues matching a JQL query. Use this for team-level delivery metrics. The `columns_by` parameter controls the report type: use `statusDuration` for per-stage averages (e.g. average time in Development), `assigneeDuration` for per-developer breakdowns, or `durationBetweenStatuses` with the `dbs_metrics` parameter for end-to-end lead time and cycle time calculations.

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `aggregation_type` | Yes | — | The statistic to compute: `average`, `median`, `sum`, or `standardDeviation`. |
| `jql` | Yes | — | A valid JQL query defining the issue set. |
| `columns_by` | No | `statusDuration` | Report type: `statusDuration`, `assigneeDuration`, or `durationBetweenStatuses`. |
| `calendar` | No | `TIMEPIECE_CALENDAR` env var | Numeric calendar ID used for business-hour calculations. |
| `view_format` | No | `days` | Unit for durations: `days`, `hours`, `minutes`, or `seconds`. |
| `day_length` | No | `businessDays` | Whether to count `businessDays` or `calendarDays`. |
| `dbs_metrics` | No | — | JSON string defining lead/cycle time metrics when using `durationBetweenStatuses`. |

**Try asking:**
- `What is the average cycle time for tickets closed in PROJ this sprint?`
- `Which status has the highest average dwell time in project PROJ?`
- `Compare average development time per developer for last sprint`
- `What is the standard deviation of cycle times in PROJ — how consistent are we?`

---

### timepiece_list_calendars

Lists every Timepiece business calendar configured for the Jira instance, including each calendar's numeric ID, display name, timezone, and working-hours definition. Use this to discover which calendars are available before running a report, to confirm which calendar is being applied to your calculations, or to look up the IDs needed for the `calendar` parameter on other tools.

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| *(none)* | — | — | No parameters required. |

**Try asking:**
- `What calendars are configured in Timepiece?`
- `Show me the working hours and timezone for our Timepiece calendar`
- `What holidays are in our default calendar?`

---

### timepiece_search_calendar

Looks up a Timepiece calendar by name and returns its numeric ID. This tool is typically called automatically by Claude when you provide a calendar name in a prompt rather than a numeric ID — for example, if you say "use the Default Calendar Settings calendar", Claude will call this tool first to resolve the name to an ID before proceeding.

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `name` | Yes | — | The calendar name to search for, e.g. `Default Calendar Settings`. |
| `search_type` | No | `exact` | Match strategy: `exact` (full name match) or `contain` (partial match). |

**Try asking:**
- `What is the ID of the Default Calendar Settings calendar?`
- `Find the calendar called London Business Hours`

---

### timepiece_export_sync

Exports a time-in-status report as a CSV or XLSX file for all issues matching a JQL query, saves the file to the local filesystem, and returns the file path. Use this when results need to leave the chat — to attach to a sprint review presentation, send to a stakeholder, or load into a spreadsheet or BI tool. Limited to datasets that can be processed within 60 seconds, which is typically up to around 10,000 issues depending on status complexity.

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `jql` | Yes | — | A valid JQL query defining the issue set. |
| `output_type` | Yes | — | Output format: `xlsx` or `csv`. |
| `calendar` | No | `TIMEPIECE_CALENDAR` env var | Numeric calendar ID used for business-hour calculations. |
| `view_format` | No | `days` | Unit for durations: `days`, `hours`, `minutes`, or `seconds`. |
| `day_length` | No | `businessDays` | Whether to count `businessDays` or `calendarDays`. |
| `columns_by` | No | `statusDuration` | Column grouping for the exported matrix. |

**Try asking:**
- `Export a CSV of time-in-status for all PROJ tickets resolved this month`
- `Generate an Excel report of last sprint's cycle times for the sprint review`
- `Download a spreadsheet of all in-progress PROJ tickets with their time in each status`

---

## Known Limitations

- **No server-side duration filtering**: The `timepiece_list_issues` tool cannot filter "show me tickets that spent more than 5 days in Development" on the API side. Retrieve the full set and ask Claude to filter or sort the results after retrieval.
- **Export is synchronous only**: The export tool uses the synchronous endpoint, which has a 60-second processing limit. Very large datasets (tens of thousands of issues) may time out — async export support will be added in a future release.
- **Sprint IDs**: Use JQL with sprint names (e.g. `sprint = "Sprint 42"`) rather than numeric sprint IDs — Jira resolves sprint names in JQL automatically.

---

## Setup

### Required environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TIMEPIECE_TOKEN` | Yes | Your Timepiece API token. Find it in Jira → Apps → Timepiece → API Settings → Create Token. |
| `TIMEPIECE_CALENDAR` | Recommended | Your default calendar ID, e.g. `10776`. Find it via `timepiece_list_calendars` or in Jira → Timepiece → Settings → Calendars. |

### Claude Code configuration

Add the following entry to the `mcpServers` section of `~/.claude.json`:

```json
"timepiece": {
  "type": "stdio",
  "command": "uv",
  "args": ["--directory", "/path/to/timepiece-mcp", "run", "timepiece-mcp"],
  "env": {
    "TIMEPIECE_TOKEN": "your-token-here",
    "TIMEPIECE_CALENDAR": "10776"
  }
}
```

Replace `/path/to/timepiece-mcp` with the absolute path to your local clone of this repository, and `your-token-here` with your Timepiece API token. The `TIMEPIECE_CALENDAR` value should be the numeric ID of the calendar that matches your team's working hours — run `timepiece_list_calendars` after setup to verify.
