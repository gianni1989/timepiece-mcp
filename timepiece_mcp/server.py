#!/usr/bin/env python3
"""
MCP Server for OBSS Timepiece — Time in Status for Jira.

Exposes Timepiece REST API as MCP tools so Claude can query
how long Jira issues have spent in each workflow status.
"""

import json
import logging
import os
import sys
import time
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

load_dotenv()

# ── Logging (stderr only — stdout is reserved for JSON-RPC on stdio) ──────────
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
logger = logging.getLogger("timepiece_mcp")

# ── Constants ─────────────────────────────────────────────────────────────────
API_BASE_URL = "https://tis.obss.io/rest"

# Read from environment — users set these in their Claude config
TIMEPIECE_TOKEN: str = os.environ.get("TIMEPIECE_TOKEN", "")
DEFAULT_CALENDAR: Optional[str] = os.environ.get("TIMEPIECE_CALENDAR")
DEFAULT_DAY_LENGTH: str = os.environ.get("TIMEPIECE_DEFAULT_DAY_LENGTH", "businessDays")
DEFAULT_VIEW_FORMAT: str = os.environ.get("TIMEPIECE_DEFAULT_VIEW_FORMAT", "days")

# ── Calendar name cache (module-level, lives for the session) ─────────────────
_calendar_name_cache: dict[str, str] = {}

# ── Server ────────────────────────────────────────────────────────────────────
mcp = FastMCP(
    "timepiece_mcp",
    instructions=(
        "Tools for querying Timepiece Time in Status data from Jira. "
        "Use these tools to find out how long Jira issues have spent in each "
        "workflow status, identify bottlenecks, and analyse cycle times."
    ),
)


# ── Enums ─────────────────────────────────────────────────────────────────────
class DayLength(str, Enum):
    BUSINESS_DAYS = "businessDays"
    CALENDAR_DAYS = "calendarDays"


class ViewFormat(str, Enum):
    DAYS = "days"
    HOURS = "hours"
    MINUTES = "minutes"
    SECONDS = "seconds"


class ColumnsBy(str, Enum):
    STATUS_DURATION = "statusDuration"
    ASSIGNEE_DURATION = "assigneeDuration"
    STATUS_DURATION_BY_ASSIGNEE = "statusDurationByAssignee"
    ASSIGNEE_DURATION_BY_STATUS = "assigneeDurationByStatus"
    DURATION_BETWEEN_STATUSES = "durationBetweenStatuses"
    STATUS_COUNT = "statusCount"
    TRANSITION_COUNT = "transitionCount"


class AggregationType(str, Enum):
    AVERAGE = "average"
    SUM = "sum"
    MEDIAN = "median"
    STANDARD_DEVIATION = "standardDeviation"


class ExportOutputType(str, Enum):
    XLSX = "xlsx"
    CSV = "csv"


class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


# ── Shared helpers ────────────────────────────────────────────────────────────
def _build_params(**kwargs: Any) -> Dict[str, Any]:
    """Build query params dict, injecting the auth token and dropping None values."""
    if not TIMEPIECE_TOKEN:
        raise ValueError(
            "TIMEPIECE_TOKEN environment variable is not set. "
            "Add it to your Claude MCP config env block."
        )
    params: Dict[str, Any] = {"tisjwt": TIMEPIECE_TOKEN}
    for key, value in kwargs.items():
        if value is not None:
            params[key] = value
    return params


async def _get(endpoint: str, params: Dict[str, Any]) -> Any:
    """Execute a GET request against the Timepiece API."""
    url = f"{API_BASE_URL}/{endpoint}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()


async def _post(endpoint: str, data: Dict[str, Any]) -> Any:
    """Execute a POST request with form-encoded body against the Timepiece API.

    Auth token is included in the form body as 'tisjwt'.
    None values are omitted from the request.
    """
    if not TIMEPIECE_TOKEN:
        raise ValueError(
            "TIMEPIECE_TOKEN environment variable is not set. "
            "Add it to your Claude MCP config env block."
        )
    url = f"{API_BASE_URL}/{endpoint}"
    # Include auth token in form body
    form_data: Dict[str, str] = {"tisjwt": TIMEPIECE_TOKEN}
    for key, value in data.items():
        if value is not None:
            form_data[key] = str(value)
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, data=form_data)
        response.raise_for_status()
        return response.json()


async def _get_binary(endpoint: str, params: Dict[str, Any]) -> bytes:
    """Execute a GET request and return raw bytes (for file downloads)."""
    url = f"{API_BASE_URL}/{endpoint}"
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.content


async def _resolve_calendar(value: Optional[str]) -> Optional[str]:
    """Resolve a calendar name or ID to a numeric calendar ID string.

    - Returns None if value is None
    - Returns value as-is if it's already numeric
    - Calls calendar/search for named calendars, returning the first result's ID
    - Falls back to returning value as-is if the search fails
    - Results are cached in _calendar_name_cache for the session lifetime
    """
    if value is None:
        return None
    # Already numeric
    if value.strip().isdigit():
        return value
    # Check session-level cache first
    cache_key = value.lower()
    cached = _calendar_name_cache.get(cache_key)
    if cached is not None:
        return cached
    # Looks like a name — search for it
    try:
        params = _build_params(name=value, searchType="exact")
        results = await _get("calendar/search", params)
        resolved_id: Optional[str] = None
        if isinstance(results, list) and results:
            cal_id = results[0].get("id")
            if cal_id is not None:
                resolved_id = str(cal_id)
        elif isinstance(results, dict):
            items = results.get("elements") or results.get("calendars") or results.get("results") or []
            if items:
                cal_id = items[0].get("id")
                if cal_id is not None:
                    resolved_id = str(cal_id)
        if resolved_id is not None:
            _calendar_name_cache[cache_key] = resolved_id
            return resolved_id
    except Exception as e:
        logger.warning("Calendar search failed for %r: %s", value, e)
    return value


def _handle_error(e: Exception) -> str:
    """Return a clear, actionable error message."""
    if isinstance(e, ValueError):
        return f"Configuration error: {e}"
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 401:
            return (
                "Error: Unauthorised — your TIMEPIECE_TOKEN is invalid or expired. "
                "Go to Jira → Timepiece → API Settings to check your token."
            )
        if status == 403:
            return "Error: Forbidden — your token does not have access to this data."
        if status == 404:
            return (
                "Error: Not found — the issue key or endpoint does not exist. "
                "Check the issue key format (e.g. PROJ-123)."
            )
        if status == 408:
            return (
                "Error: Request timed out (408) — the Timepiece API did not respond in time. "
                "Tip: the JQL matched too many issues. Narrow the query with a date range, "
                "e.g. AND resolved >= '2025-01-01'."
            )
        if status == 429:
            return "Error: Rate limit exceeded — please wait before retrying."
        if status == 400:
            body_text = e.response.text[:500]
            msg = f"Error: Timepiece API returned HTTP 400: {body_text}"
            if "JQL" in body_text or "function" in body_text.lower():
                msg += (
                    " Tip: startOfWeek(), startOfMonth(), startOfQuarter() and startOfYear() "
                    "are not supported — use explicit dates like '2025-01-01' instead."
                )
            return msg
        msg = f"Error: Timepiece API returned HTTP {status}: {e.response.text[:200]}"
        if "408" in str(status) or "timeout" in e.response.text.lower():
            msg += (
                " Tip: the JQL matched too many issues. Narrow the query with a date range, "
                "e.g. AND resolved >= '2025-01-01'."
            )
        return msg
    if isinstance(e, httpx.TimeoutException):
        return (
            "Error: Request timed out — the Timepiece API did not respond in time. "
            "Tip: the JQL matched too many issues. Narrow the query with a date range, "
            "e.g. AND resolved >= '2025-01-01'."
        )
    if isinstance(e, httpx.ConnectError):
        return "Error: Could not connect to tis.obss.io — check your network connection."
    # Check for asyncio timeout
    error_str = str(e)
    error_type = type(e).__name__
    if "TimeoutError" in error_type or "timeout" in error_str.lower():
        return (
            f"Error: {error_type}: {e} "
            "Tip: the JQL matched too many issues. Narrow the query with a date range, "
            "e.g. AND resolved >= '2025-01-01'."
        )
    return f"Error: {error_type}: {e}"


# ── Response parsers (handle Timepiece table structure) ───────────────────────
def _extract_table(data: Any) -> Optional[Dict[str, Any]]:
    """Extract the table dict from a Timepiece API response."""
    if isinstance(data, dict) and "table" in data:
        return data["table"]
    return None


def _get_col_map(table: Dict[str, Any]) -> Dict[str, str]:
    """Build a column ID → column name mapping from table header."""
    return {
        col["id"]: col.get("value", col["id"])
        for col in table.get("header", {}).get("valueColumns", [])
    }


def _get_ordered_col_ids(table: Dict[str, Any]) -> List[str]:
    """Return ordered list of column IDs from table header."""
    return [col["id"] for col in table.get("header", {}).get("valueColumns", [])]


def _get_row_key(row: Dict[str, Any]) -> tuple:
    """Extract (issue_key, summary) from a row's headerColumns."""
    header_cols = {c["id"]: c.get("value", "") for c in row.get("headerColumns", [])}
    issue_key = header_cols.get("issuekey", header_cols.get("issue_key", "-"))
    summary = header_cols.get("summary", "")
    return issue_key, summary


def _get_row_values(row: Dict[str, Any]) -> Dict[str, Any]:
    """Build col_id → value_cell mapping from row's valueColumns."""
    return {vc["id"]: vc for vc in row.get("valueColumns", [])}


# ── Markdown formatters ───────────────────────────────────────────────────────
def _round_value(v: str) -> str:
    """Round a numeric string to 2 decimal places; return as-is if not numeric."""
    try:
        return f"{float(v):.2f}"
    except (ValueError, TypeError):
        return v


def _format_issue_markdown(data: Any, issue_key: str, view_format: str) -> str:
    """Render a single-issue Timepiece response as a readable Markdown table."""
    lines = [f"## Time in Status — {issue_key}", ""]

    table = _extract_table(data)
    if table is None:
        # Fallback for unexpected shapes
        return f"## {issue_key}\n\n```json\n{json.dumps(data, indent=2)}\n```"

    col_map = _get_col_map(table)
    col_ids = _get_ordered_col_ids(table)
    rows = table.get("body", {}).get("rows", [])

    if not rows:
        lines.append("No time-in-status data found for this issue.")
        return "\n".join(lines)

    row = rows[0]
    val_map = _get_row_values(row)

    lines.append("| Status | Duration | Visits |")
    lines.append("|--------|----------|--------|")

    # Collect non-zero rows and sort by float value descending
    data_rows = []
    for col_id in col_ids:
        vc = val_map.get(col_id, {})
        raw_value = vc.get("value", "-")
        if raw_value == "-":
            continue
        status_name = col_map.get(col_id, col_id)
        count = vc.get("count", "-")
        try:
            sort_key = float(raw_value)
        except (ValueError, TypeError):
            sort_key = 0.0
        data_rows.append((sort_key, status_name, raw_value, count))

    data_rows.sort(key=lambda x: x[0], reverse=True)

    for _, status_name, raw_value, count in data_rows:
        rounded = _round_value(raw_value)
        lines.append(f"| {status_name} | {rounded} {view_format} | {count} |")

    return "\n".join(lines)


def _ms_to_view_format(raw_ms: int, view_format: str, daily_working_hours: float = 8.0) -> float:
    """Convert raw milliseconds to the requested view format unit."""
    if view_format == "days":
        divisor = daily_working_hours * 3_600_000
    elif view_format == "hours":
        divisor = 3_600_000
    elif view_format == "minutes":
        divisor = 60_000
    else:  # seconds
        divisor = 1_000
    return raw_ms / divisor if divisor else 0.0


def _format_issue_expanded_markdown(data: Any, issue_key: str, view_format: str) -> str:
    """Render expanded issue data with stats summary and transition history.

    The expanded endpoint response structure:
      table.body.rows[0].expanded.stats  — visitCounts, totalValues, averageValues, etc.
      table.body.rows[0].expanded.rows   — [{uniqueDate, statusId, transitionedBy, value (ms)}]
    """
    lines = [f"## Expanded Time in Status — {issue_key}", ""]

    table = _extract_table(data)
    if table is None:
        return f"## {issue_key}\n\n```json\n{json.dumps(data, indent=2)}\n```"

    col_map = _get_col_map(table)
    rows = table.get("body", {}).get("rows", [])

    if not rows:
        lines.append("No transition history data found for this issue.")
        return "\n".join(lines)

    # Get calendar's daily working hours for unit conversion
    daily_working_hours: float = 8.0
    if isinstance(data, dict) and "calendar" in data:
        daily_working_hours = data["calendar"].get("dailyWorkingHours", 8.0) or 8.0

    row = rows[0]
    expanded = row.get("expanded", {})

    if not expanded:
        lines.append("No expanded data found for this issue.")
        return "\n".join(lines)

    stats = expanded.get("stats", {})
    transition_rows_raw = expanded.get("rows", [])

    # Build stats lookup: statusId -> count/total/average
    visit_counts: Dict[str, int] = {
        str(e["statusId"]): e["value"] for e in stats.get("visitCounts", [])
    }
    total_values: Dict[str, int] = {
        str(e["statusId"]): e["value"] for e in stats.get("totalValues", [])
    }
    avg_values: Dict[str, int] = {
        str(e["statusId"]): e["value"] for e in stats.get("averageValues", [])
    }

    # Summary section — ordered by total time descending
    if total_values:
        lines.append("### Summary by Status")
        lines.append("")
        lines.append(f"| Status | Total {view_format} | Visits | Avg per Visit |")
        lines.append("|--------|--------------|--------|---------------|")

        sorted_statuses = sorted(
            total_values.keys(),
            key=lambda sid: total_values[sid],
            reverse=True,
        )
        for sid in sorted_statuses:
            status_name = col_map.get(sid, f"Status {sid}")
            total_ms = total_values[sid]
            visits = visit_counts.get(sid, 1)
            avg_ms = avg_values.get(sid, total_ms // visits if visits else total_ms)
            total_fmt = _ms_to_view_format(total_ms, view_format, daily_working_hours)
            avg_fmt = _ms_to_view_format(avg_ms, view_format, daily_working_hours)
            lines.append(
                f"| {status_name} | {total_fmt:.4f} | {visits} | {avg_fmt:.4f} |"
            )
        lines.append("")

    # Transition history section
    if transition_rows_raw:
        lines.append("### Transition History")
        lines.append("")
        lines.append("| Date / Time | Status | Duration | Transitioned By |")
        lines.append("|-------------|--------|----------|-----------------|")
        for tr in transition_rows_raw:
            date_val = tr.get("uniqueDate", "-")
            sid = str(tr.get("statusId", ""))
            status_name = col_map.get(sid, f"Status {sid}")
            raw_ms = tr.get("value", 0)
            duration = _ms_to_view_format(raw_ms, view_format, daily_working_hours)
            transitioned_by = tr.get("transitionedBy", "-")
            lines.append(
                f"| {date_val} | {status_name} | {duration:.4f} {view_format} | {transitioned_by} |"
            )

    if not total_values and not transition_rows_raw:
        lines.append("No transition data available for this issue.")

    return "\n".join(lines)


def _format_list_issues_markdown(
    data: Any,
    view_format: str,
    page_size: int,
    top_n_statuses: Optional[int] = None,
) -> str:
    """Render a list2 API response as a Markdown table."""
    lines = ["## Time in Status — Issue List", ""]

    table = _extract_table(data)
    if table is None:
        return f"## Issue List\n\n```json\n{json.dumps(data, indent=2)}\n```"

    col_map = _get_col_map(table)
    col_ids = _get_ordered_col_ids(table)

    rows = table.get("body", {}).get("rows", [])
    total_count = (
        data.get("totalCount") or data.get("total") or data.get("totalIssueCount") or len(rows)
        if isinstance(data, dict) else len(rows)
    )

    if not rows:
        lines.append("No issues found for this query.")
        return "\n".join(lines)

    # Compute total time per status column across all rows (for sorting and top_n)
    col_totals: Dict[str, float] = {}
    for col_id in col_ids:
        total = 0.0
        for row in rows:
            val_map = _get_row_values(row)
            vc = val_map.get(col_id, {})
            val = vc.get("value", "-")
            try:
                total += float(val)
            except (ValueError, TypeError):
                pass
        col_totals[col_id] = total

    # Sort columns by total time descending
    sorted_col_ids = sorted(col_ids, key=lambda cid: col_totals.get(cid, 0.0), reverse=True)

    # Apply top_n_statuses filter if requested
    if top_n_statuses is not None:
        sorted_col_ids = sorted_col_ids[:top_n_statuses]

    col_names = [col_map.get(cid, cid) for cid in sorted_col_ids]

    # Build header row
    status_header = " | ".join(col_names)
    status_sep = " | ".join(["-" * max(len(n), 3) for n in col_names])
    lines.append(f"| Issue Key | Summary | {status_header} |")
    lines.append(f"|-----------|---------|{status_sep}|")

    for row in rows:
        issue_key, summary = _get_row_key(row)
        # Truncate long summaries
        if len(summary) > 60:
            summary = summary[:57] + "..."

        val_map = _get_row_values(row)
        row_values = []
        for col_id in sorted_col_ids:
            vc = val_map.get(col_id, {})
            val = vc.get("value", "-")
            if val != "-" and val:
                row_values.append(f"{_round_value(val)} {view_format}")
            else:
                row_values.append("-")

        lines.append(f"| {issue_key} | {summary} | " + " | ".join(row_values) + " |")

    lines.append("")
    if total_count and total_count > len(rows):
        lines.append(
            f"*Showing {len(rows)} of {total_count} issues. "
            f"Increase `page_size` (currently {page_size}) to see more.*"
        )

    return "\n".join(lines)


def _format_aggregate_markdown(data: Any, aggregation_type: str, jql: str, view_format: str) -> str:
    """Render aggregation API response as a Markdown table.

    The aggregation endpoint returns a table where:
    - body.rows is typically a single aggregate row (or one row per group)
    - Each row has issueCount at the row level
    - valueColumns contains one entry per status with the aggregated duration
    - headerColumns is empty for the overall-aggregate case
    - The status label for each value comes from header.valueColumns[i].value
    """
    lines = [
        f"## Aggregation — {aggregation_type.title()}",
        f"*Filter: `{jql}`*",
        "",
    ]

    table = _extract_table(data)
    if table is None:
        return "\n".join(lines) + f"\n```json\n{json.dumps(data, indent=2)}\n```"

    col_map = _get_col_map(table)
    col_ids = _get_ordered_col_ids(table)
    rows = table.get("body", {}).get("rows", [])

    if not rows:
        lines.append("No data returned for this query.")
        return "\n".join(lines)

    # Aggregate: each row can represent either an overall aggregate (headerColumns empty)
    # or a group (e.g. per-assignee). Columns are statuses with their aggregated values.
    for row in rows:
        # Row-level label (group name, or "Overall" for ungrouped aggregate)
        h_cols = {c["id"]: c.get("value", "") for c in row.get("headerColumns", [])}
        row_label = (
            h_cols.get("assignee")
            or h_cols.get("issuekey")
            or next((v for v in h_cols.values() if v), None)
            or "Overall"
        )
        issue_count = row.get("issueCount", "-")

        val_map = _get_row_values(row)

        # Print section header if there are multiple rows or a meaningful label
        if len(rows) > 1 or row_label != "Overall":
            lines.append(f"### {row_label} (n={issue_count})")
            lines.append("")

        lines.append(f"| Status | {aggregation_type.title()} ({view_format}) | Issues |")
        lines.append("|--------|-----------------------|--------|")

        has_data = False
        # Collect non-zero rows and sort by float value descending
        agg_rows = []
        for col_id in col_ids:
            vc = val_map.get(col_id, {})
            v = vc.get("value", "-")
            if v == "-" or not v:
                continue
            status_name = col_map.get(col_id, col_id)
            col_count = vc.get("count", str(issue_count))
            try:
                sort_key = float(v)
            except (ValueError, TypeError):
                sort_key = 0.0
            agg_rows.append((sort_key, status_name, v, col_count))
        agg_rows.sort(key=lambda x: x[0], reverse=True)
        for _, status_name, v, col_count in agg_rows:
            lines.append(f"| {status_name} | {_round_value(v)} | {col_count} |")
            has_data = True

        if not has_data:
            lines.append("| (no data) | - | - |")

        lines.append("")

    if issue_count != "-":
        lines.append(f"*{issue_count} issue(s) included in aggregation.*")

    return "\n".join(lines)


def _format_calendars_markdown(data: Any) -> str:
    """Render a list of calendars as a Markdown table, with holidays per calendar."""
    lines = ["## Timepiece Calendars", ""]
    lines.append("| ID | Name | Timezone | Working Hours/Day | Default |")
    lines.append("|----|------|----------|-------------------|---------|")

    items: List[Any] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("calendars") or data.get("results") or data.get("data") or []

    calendars_with_holidays: List[Any] = []
    for cal in items:
        cal_id = cal.get("id", "-")
        name = cal.get("name", "-")
        tz = cal.get("timeZone") or cal.get("timezone") or "-"
        wh = cal.get("dailyWorkingHours") or cal.get("workingHours") or "-"
        is_default = "Yes" if cal.get("isDefault") or cal.get("default") else "No"
        lines.append(f"| {cal_id} | {name} | {tz} | {wh} | {is_default} |")
        holidays = cal.get("holidays") or []
        if holidays:
            calendars_with_holidays.append((name, holidays))

    for cal_name, holidays in calendars_with_holidays:
        lines.append("")
        lines.append(f"### Holidays — {cal_name}")
        lines.append("")
        lines.append("| Date | Recurring |")
        lines.append("|------|-----------|")
        for h in holidays:
            date = h.get("date", "-")
            label = h.get("name") or date
            recurring = "Yes" if h.get("recurring") else "No"
            lines.append(f"| {label} | {recurring} |")

    return "\n".join(lines)


# ── Input models ──────────────────────────────────────────────────────────────
class GetIssueInput(BaseModel):
    """Input for querying a single Jira issue's time-in-status."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    issue_key: str = Field(
        ...,
        description="Jira issue key, e.g. 'PROJ-123'",
        min_length=2,
        max_length=50,
        pattern=r"^[A-Z][A-Z0-9_]+-\d+$",
    )
    columns_by: ColumnsBy = Field(
        default=ColumnsBy.STATUS_DURATION,
        description="Group results by 'statusDuration' (default) or 'assigneeDuration'",
    )
    calendar: Optional[str] = Field(
        default=None,
        description=(
            "Timepiece calendar ID or name. "
            "Defaults to TIMEPIECE_CALENDAR env var if set. "
            "Find calendar IDs in Jira → Timepiece → Settings → Calendars."
        ),
    )
    day_length: DayLength = Field(
        default=DayLength.BUSINESS_DAYS,
        description="How to count time: 'businessDays' (default) or 'calendarDays'",
    )
    view_format: ViewFormat = Field(
        default=ViewFormat.DAYS,
        description="Unit for durations: 'days' (default), 'hours', 'minutes', or 'seconds'",
    )
    statuses: Optional[str] = Field(
        default=None,
        description=(
            "Comma-separated Timepiece status IDs to include, e.g. '10001,10002'. "
            "Omit to include all statuses."
        ),
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="'markdown' for human-readable output (default), 'json' for raw data",
    )

    @field_validator("issue_key")
    @classmethod
    def upper_issue_key(cls, v: str) -> str:
        return v.upper()


class GetIssueExpandedInput(BaseModel):
    """Input for querying a single Jira issue's expanded time-in-status with transitions."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    issue_key: str = Field(
        ...,
        description="Jira issue key, e.g. 'PROJ-123'",
        min_length=2,
        max_length=50,
        pattern=r"^[A-Z][A-Z0-9_]+-\d+$",
    )
    calendar: Optional[str] = Field(
        default=None,
        description="Timepiece calendar ID or name. Defaults to TIMEPIECE_CALENDAR env var.",
    )
    day_length: DayLength = Field(
        default=DayLength.BUSINESS_DAYS,
        description="How to count time: 'businessDays' (default) or 'calendarDays'",
    )
    view_format: ViewFormat = Field(
        default=ViewFormat.DAYS,
        description="Unit for durations: 'days' (default), 'hours', 'minutes', or 'seconds'",
    )
    trim_history_start_date: Optional[str] = Field(
        default=None,
        description="Only include transitions on or after this date (yyyy-MM-dd)",
    )
    trim_history_end_date: Optional[str] = Field(
        default=None,
        description="Only include transitions on or before this date (yyyy-MM-dd)",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="'markdown' for human-readable output (default), 'json' for raw data",
    )

    @field_validator("issue_key")
    @classmethod
    def upper_issue_key(cls, v: str) -> str:
        return v.upper()


class ListIssuesInput(BaseModel):
    """Input for listing multiple Jira issues' time-in-status via JQL."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    jql: str = Field(
        ...,
        description=(
            "JQL query to select issues. Examples:\n"
            "  project = BAU AND sprint in openSprints()\n"
            "  project = BAU AND resolved >= '2025-01-01' AND resolved <= '2025-12-31'\n"
            "  project = BAU AND status = 'Development'\n"
            "  issuekey in (BAU-278, BAU-308)\n"
            "  project = BAU AND assignee = currentUser()\n"
            "IMPORTANT: startOfWeek(), startOfMonth(), startOfQuarter(), startOfYear() are NOT supported "
            "by the Timepiece API — use explicit dates like '2026-01-01' instead."
        ),
        min_length=1,
    )
    columns_by: ColumnsBy = Field(
        default=ColumnsBy.STATUS_DURATION,
        description="Group results by column type (default: statusDuration)",
    )
    calendar: Optional[str] = Field(
        default=None,
        description="Timepiece calendar ID or name. Defaults to TIMEPIECE_CALENDAR env var.",
    )
    day_length: DayLength = Field(
        default=DayLength.BUSINESS_DAYS,
        description="How to count time: 'businessDays' (default) or 'calendarDays'",
    )
    view_format: ViewFormat = Field(
        default=ViewFormat.DAYS,
        description="Unit for durations: 'days' (default), 'hours', 'minutes', or 'seconds'",
    )
    statuses: Optional[str] = Field(
        default=None,
        description="Comma-separated Timepiece status IDs to include. Omit for all statuses.",
    )
    page_size: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Number of issues to return per page (1-1000, default 100)",
    )
    top_n_statuses: Optional[int] = Field(
        default=None,
        description=(
            "If set, only show the N statuses with the highest total time across all returned issues. "
            "Useful for large result sets where most status columns are empty. E.g. top_n_statuses=5 "
            "shows only the 5 most time-consuming stages."
        ),
        ge=1,
        le=50,
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="'markdown' for human-readable output (default), 'json' for raw data",
    )


class AggregateInput(BaseModel):
    """Input for aggregating time-in-status across multiple issues."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    aggregation_type: AggregationType = Field(
        ...,
        description="Aggregation function: 'average', 'sum', 'median', or 'standardDeviation'",
    )
    jql: str = Field(
        ...,
        description=(
            "JQL query to select issues. Examples:\n"
            "  project = BAU AND sprint in openSprints()\n"
            "  project = BAU AND resolved >= '2025-01-01' AND resolved <= '2025-12-31'\n"
            "  project = BAU AND status = 'Development'\n"
            "  issuekey in (BAU-278, BAU-308)\n"
            "  project = BAU AND assignee = currentUser()\n"
            "IMPORTANT: startOfWeek(), startOfMonth(), startOfQuarter(), startOfYear() are NOT supported "
            "by the Timepiece API — use explicit dates like '2026-01-01' instead."
        ),
        min_length=1,
    )
    columns_by: ColumnsBy = Field(
        default=ColumnsBy.STATUS_DURATION,
        description="Column grouping: statusDuration, assigneeDuration, durationBetweenStatuses, statusCount, transitionCount",
    )
    calendar: Optional[str] = Field(
        default=None,
        description="Timepiece calendar ID or name. Defaults to TIMEPIECE_CALENDAR env var.",
    )
    day_length: DayLength = Field(
        default=DayLength.BUSINESS_DAYS,
        description="How to count time: 'businessDays' (default) or 'calendarDays'",
    )
    view_format: ViewFormat = Field(
        default=ViewFormat.DAYS,
        description="Unit for durations: 'days' (default), 'hours', 'minutes', or 'seconds'",
    )
    statuses: Optional[str] = Field(
        default=None,
        description="Comma-separated Timepiece status IDs to include. Omit for all statuses.",
    )
    dbs_metrics: Optional[str] = Field(
        default=None,
        description=(
            "JSON string defining duration-between-statuses metrics for lead time or cycle time calculations. "
            "Each metric defines a name, a start point, a stop point, and optional pause statuses.\n\n"
            "Example — Cycle Time (first entry into Development → Done):\n"
            "  [{\"name\": \"Cycle Time\", \"startAt\": {\"type\": \"status\", \"value\": \"Development\", \"visitType\": \"first\"}, \"stopAt\": {\"type\": \"status\", \"value\": \"Done\", \"visitType\": \"last\"}}]\n\n"
            "Example — Lead Time (issue creation → Done):\n"
            "  [{\"name\": \"Lead Time\", \"startAt\": {\"type\": \"issueCreation\"}, \"stopAt\": {\"type\": \"status\", \"value\": \"Done\", \"visitType\": \"last\"}}]\n\n"
            "Example — Active Cycle Time (pausing on Blocked and Waiting):\n"
            "  [{\"name\": \"Active Cycle Time\", \"startAt\": {\"type\": \"status\", \"value\": \"Development\", \"visitType\": \"first\"}, \"stopAt\": {\"type\": \"status\", \"value\": \"Done\", \"visitType\": \"last\"}, \"pausedOn\": [{\"type\": \"status\", \"value\": \"Blocked\"}, {\"type\": \"status\", \"value\": \"Waiting\"}]}]\n\n"
            "Only used when columns_by = 'durationBetweenStatuses'."
        ),
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="'markdown' for human-readable output (default), 'json' for raw data",
    )


class ListCalendarsInput(BaseModel):
    """Input for listing all Timepiece calendars."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="'markdown' for human-readable output (default), 'json' for raw data",
    )


class SearchCalendarInput(BaseModel):
    """Input for searching Timepiece calendars by name."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    name: str = Field(
        ...,
        description="Calendar name to search for",
        min_length=1,
    )
    search_type: str = Field(
        default="exact",
        description="Search type: 'exact' (default) or 'contain'",
        pattern=r"^(exact|contain)$",
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of results to return (default 10)",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="'markdown' for human-readable output (default), 'json' for raw data",
    )


class ExportSyncInput(BaseModel):
    """Input for exporting time-in-status data to a file."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    jql: str = Field(
        ...,
        description=(
            "JQL query to select issues. Examples:\n"
            "  project = BAU AND sprint in openSprints()\n"
            "  project = BAU AND resolved >= '2025-01-01' AND resolved <= '2025-12-31'\n"
            "  project = BAU AND status = 'Development'\n"
            "  issuekey in (BAU-278, BAU-308)\n"
            "  project = BAU AND assignee = currentUser()\n"
            "IMPORTANT: startOfWeek(), startOfMonth(), startOfQuarter(), startOfYear() are NOT supported "
            "by the Timepiece API — use explicit dates like '2026-01-01' instead."
        ),
        min_length=1,
    )
    output_type: ExportOutputType = Field(
        ...,
        description="Output file format: 'xlsx' or 'csv'",
    )
    columns_by: ColumnsBy = Field(
        default=ColumnsBy.STATUS_DURATION,
        description="Column grouping for the export (default: statusDuration)",
    )
    calendar: Optional[str] = Field(
        default=None,
        description="Timepiece calendar ID or name. Defaults to TIMEPIECE_CALENDAR env var.",
    )
    day_length: DayLength = Field(
        default=DayLength.BUSINESS_DAYS,
        description="How to count time: 'businessDays' (default) or 'calendarDays'",
    )
    view_format: ViewFormat = Field(
        default=ViewFormat.DAYS,
        description="Unit for durations: 'days' (default), 'hours', 'minutes', or 'seconds'",
    )
    statuses: Optional[str] = Field(
        default=None,
        description="Comma-separated Timepiece status IDs to include. Omit for all statuses.",
    )


# ── Tools ─────────────────────────────────────────────────────────────────────
@mcp.tool(
    name="timepiece_get_issue",
    annotations={
        "title": "Get Time in Status for a Single Jira Issue",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def timepiece_get_issue(params: GetIssueInput) -> str:
    """Get time-in-status data for a single Jira issue from Timepiece.

    Returns how long the issue has spent in each workflow status
    (e.g. To Do, In Progress, In Review, Done), using a configurable
    calendar and time unit.

    Args:
        params (GetIssueInput): Validated input containing:
            - issue_key (str): Jira issue key, e.g. 'PROJ-123'
            - columns_by (str): 'statusDuration' or 'assigneeDuration' (default: statusDuration)
            - calendar (Optional[str]): Timepiece calendar ID or name
            - day_length (str): 'businessDays' or 'calendarDays' (default: businessDays)
            - view_format (str): 'days', 'hours', 'minutes', 'seconds' (default: days)
            - statuses (Optional[str]): Comma-separated status IDs to filter
            - response_format (str): 'markdown' or 'json' (default: markdown)

    Returns:
        str: Time-in-status data as Markdown table (default) or JSON.

    Examples:
        - "How long has PROJ-123 been in each status?" → issue_key='PROJ-123'
        - "Show PROJ-456 time in status in hours" → issue_key='PROJ-456', view_format='hours'
        - "Get calendar days for PROJ-789" → day_length='calendarDays'
    """
    raw_calendar = params.calendar or DEFAULT_CALENDAR
    try:
        calendar = await _resolve_calendar(raw_calendar)
        day_length = params.day_length.value
        view_format = params.view_format.value

        query_params = _build_params(
            issueKey=params.issue_key,
            columnsBy=params.columns_by.value,
            dayLength=day_length,
            viewFormat=view_format,
            calendar=calendar,
            statuses=params.statuses,
        )
        data = await _get("issue", query_params)

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(data, indent=2)

        return _format_issue_markdown(data, params.issue_key, view_format)

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="timepiece_get_issue_expanded",
    annotations={
        "title": "Get Expanded Time in Status with Transition History",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def timepiece_get_issue_expanded(params: GetIssueExpandedInput) -> str:
    """Get expanded time-in-status data including full transition history for a single Jira issue.

    Returns per-status statistics (total days, visit count, average per visit) plus
    a chronological list of every status transition with its duration.

    Args:
        params (GetIssueExpandedInput): Validated input containing:
            - issue_key (str): Jira issue key, e.g. 'PROJ-123'
            - calendar (Optional[str]): Timepiece calendar ID or name
            - day_length (str): 'businessDays' or 'calendarDays' (default: businessDays)
            - view_format (str): 'days', 'hours', 'minutes', 'seconds' (default: days)
            - trim_history_start_date (Optional[str]): Earliest date to include (yyyy-MM-dd)
            - trim_history_end_date (Optional[str]): Latest date to include (yyyy-MM-dd)
            - response_format (str): 'markdown' or 'json' (default: markdown)

    Returns:
        str: Expanded time-in-status with summary stats and transition history table.
    """
    raw_calendar = params.calendar or DEFAULT_CALENDAR
    try:
        calendar = await _resolve_calendar(raw_calendar)
        day_length = params.day_length.value
        view_format = params.view_format.value

        query_params = _build_params(
            issueKey=params.issue_key,
            columnsBy="statusDurationExpanded",
            dayLength=day_length,
            viewFormat=view_format,
            calendar=calendar,
            trimHistoryStartDate=params.trim_history_start_date,
            trimHistoryEndDate=params.trim_history_end_date,
        )
        data = await _get("issue/expanded", query_params)

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(data, indent=2)

        return _format_issue_expanded_markdown(data, params.issue_key, view_format)

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="timepiece_list_issues",
    annotations={
        "title": "List Time in Status for Multiple Jira Issues via JQL",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def timepiece_list_issues(params: ListIssuesInput) -> str:
    """List time-in-status data for multiple Jira issues selected by JQL query.

    Uses the Timepiece list API to fetch time-in-status for all issues matching
    the JQL filter. Results are presented as a table with one row per issue.

    Args:
        params (ListIssuesInput): Validated input containing:
            - jql (str): JQL query to select issues
            - columns_by (str): Column grouping (default: statusDuration)
            - calendar (Optional[str]): Timepiece calendar ID or name
            - day_length (str): 'businessDays' or 'calendarDays' (default: businessDays)
            - view_format (str): 'days', 'hours', 'minutes', 'seconds' (default: days)
            - statuses (Optional[str]): Comma-separated status IDs to filter
            - page_size (int): Results per page (1-1000, default 100)
            - response_format (str): 'markdown' or 'json' (default: markdown)

    Returns:
        str: Table of issues with time-in-status per status column.
    """
    raw_calendar = params.calendar or DEFAULT_CALENDAR
    try:
        calendar = await _resolve_calendar(raw_calendar)
        day_length = params.day_length.value
        view_format = params.view_format.value

        form_data: Dict[str, Any] = {
            "filterType": "customjql",
            "customjql": params.jql,
            "columnsBy": params.columns_by.value,
            "dayLength": day_length,
            "viewFormat": view_format,
            "pageSize": str(params.page_size),
        }
        if calendar is not None:
            form_data["calendar"] = calendar
        if params.statuses is not None:
            form_data["statuses"] = params.statuses

        data = await _post("list2", form_data)

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(data, indent=2)

        return _format_list_issues_markdown(data, view_format, params.page_size, params.top_n_statuses)

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="timepiece_aggregate",
    annotations={
        "title": "Aggregate Time in Status Across Multiple Jira Issues",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def timepiece_aggregate(params: AggregateInput) -> str:
    """Aggregate time-in-status statistics across multiple Jira issues.

    Computes average, median, sum, or standard deviation of time spent
    in each status across all issues matching the JQL query.

    Args:
        params (AggregateInput): Validated input containing:
            - aggregation_type (str): 'average', 'sum', 'median', or 'standardDeviation'
            - jql (str): JQL query to select issues
            - columns_by (str): Column grouping (default: statusDuration)
            - calendar (Optional[str]): Timepiece calendar ID or name
            - day_length (str): 'businessDays' or 'calendarDays' (default: businessDays)
            - view_format (str): 'days', 'hours', 'minutes', 'seconds' (default: days)
            - statuses (Optional[str]): Comma-separated status IDs to filter
            - dbs_metrics (Optional[str]): JSON for duration-between-statuses metrics
            - response_format (str): 'markdown' or 'json' (default: markdown)

    Returns:
        str: Aggregated time-in-status statistics as a Markdown table or JSON.
    """
    raw_calendar = params.calendar or DEFAULT_CALENDAR
    try:
        calendar = await _resolve_calendar(raw_calendar)
        day_length = params.day_length.value
        view_format = params.view_format.value

        form_data: Dict[str, Any] = {
            "filterType": "customjql",
            "customjql": params.jql,
            "aggregationType": params.aggregation_type.value,
            "columnsBy": params.columns_by.value,
            "dayLength": day_length,
            "viewFormat": view_format,
        }
        if calendar is not None:
            form_data["calendar"] = calendar
        if params.statuses is not None:
            form_data["statuses"] = params.statuses
        if params.dbs_metrics is not None:
            form_data["dbsMetrics"] = params.dbs_metrics

        data = await _post("aggregation", form_data)

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(data, indent=2)

        return _format_aggregate_markdown(data, params.aggregation_type.value, params.jql, view_format)

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="timepiece_list_calendars",
    annotations={
        "title": "List All Timepiece Calendars",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def timepiece_list_calendars(params: ListCalendarsInput) -> str:
    """List all available Timepiece calendars.

    Returns all configured calendars in your Timepiece instance,
    including their IDs, names, timezones, and working hours settings.
    Use calendar IDs when querying time-in-status data.

    Args:
        params (ListCalendarsInput): Optional response format ('markdown' or 'json').

    Returns:
        str: Table of calendars with ID, name, timezone, working hours, and default flag.
    """
    try:
        query_params = _build_params()
        data = await _get("calendar", query_params)

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(data, indent=2)

        return _format_calendars_markdown(data)

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="timepiece_search_calendar",
    annotations={
        "title": "Search for a Timepiece Calendar by Name",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def timepiece_search_calendar(params: SearchCalendarInput) -> str:
    """Search for Timepiece calendars by name.

    Useful for finding a calendar's numeric ID when you only know its name,
    e.g. 'Default Calendar Settings'.

    Args:
        params (SearchCalendarInput): Validated input containing:
            - name (str): Calendar name to search for
            - search_type (str): 'exact' (default) or 'contain'
            - max_results (int): Maximum results to return (default 10)
            - response_format (str): 'markdown' or 'json' (default: markdown)

    Returns:
        str: Matching calendars with ID, name, timezone, working hours, and default flag.
    """
    try:
        query_params = _build_params(
            name=params.name,
            searchType=params.search_type,
            maxResults=params.max_results,
        )
        data = await _get("calendar/search", query_params)

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(data, indent=2)

        return _format_calendars_markdown(data)

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="timepiece_export_sync",
    annotations={
        "title": "Export Time in Status Data to File",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def timepiece_export_sync(params: ExportSyncInput) -> str:
    """Export time-in-status data for Jira issues to a downloadable file.

    Generates an XLSX or CSV export of time-in-status data for issues matching
    the JQL query and saves it to /tmp. Returns the file path and a summary.

    Args:
        params (ExportSyncInput): Validated input containing:
            - jql (str): JQL query to select issues
            - output_type (str): 'xlsx' or 'csv'
            - columns_by (str): Column grouping (default: statusDuration)
            - calendar (Optional[str]): Timepiece calendar ID or name
            - day_length (str): 'businessDays' or 'calendarDays' (default: businessDays)
            - view_format (str): 'days', 'hours', 'minutes', 'seconds' (default: days)
            - statuses (Optional[str]): Comma-separated status IDs to include

    Returns:
        str: File path of the exported file and a summary of the export.
    """
    raw_calendar = params.calendar or DEFAULT_CALENDAR
    try:
        calendar = await _resolve_calendar(raw_calendar)
        day_length = params.day_length.value
        view_format = params.view_format.value
        ext = params.output_type.value

        query_params = _build_params(
            filterType="customjql",
            customjql=params.jql,
            columnsBy=params.columns_by.value,
            dayLength=day_length,
            viewFormat=view_format,
            outputType=ext,
            calendar=calendar,
            statuses=params.statuses,
        )

        file_bytes = await _get_binary("smallexport", query_params)

        timestamp = int(time.time())
        file_path = f"/tmp/timepiece-export-{timestamp}.{ext}"
        with open(file_path, "wb") as f:
            f.write(file_bytes)

        size_kb = len(file_bytes) / 1024
        return (
            f"Export saved to: `{file_path}`\n\n"
            f"- Format: {ext.upper()}\n"
            f"- Size: {size_kb:.1f} KB\n"
            f"- Filter: `{params.jql}`\n"
            f"- Columns: {params.columns_by.value}\n"
            f"- Day length: {day_length}\n"
        )

    except Exception as e:
        return _handle_error(e)


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    if not TIMEPIECE_TOKEN:
        print(
            "Warning: TIMEPIECE_TOKEN is not set. "
            "Tools will return an error until you configure it.",
            file=sys.stderr,
        )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
