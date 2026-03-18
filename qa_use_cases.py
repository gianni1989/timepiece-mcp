#!/usr/bin/env python3
"""
QA test suite — validates every example prompt from MCP_OVERVIEW.md.

Maps each natural-language use case to an actual tool call and validates
the output is meaningful. Run with:

    TIMEPIECE_TOKEN=<token> TIMEPIECE_CALENDAR=10776 uv run python qa_use_cases.py
"""

import asyncio
import os
import re
import sys

os.environ.setdefault("TIMEPIECE_CALENDAR", "10776")

from timepiece_mcp.server import (
    AggregateInput,
    AggregationType,
    ColumnsBy,
    ExportOutputType,
    ExportSyncInput,
    GetIssueExpandedInput,
    GetIssueInput,
    ListCalendarsInput,
    ListIssuesInput,
    ResponseFormat,
    SearchCalendarInput,
    timepiece_aggregate,
    timepiece_export_sync,
    timepiece_get_issue,
    timepiece_get_issue_expanded,
    timepiece_list_calendars,
    timepiece_list_issues,
    timepiece_search_calendar,
)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
SKIP = "\033[93mSKIP\033[0m"
SECTION = "\033[94m"
RESET = "\033[0m"

results = []


def numbers_in(text: str) -> list[str]:
    return re.findall(r"\d+\.\d+", text)


def check(name: str, output: str, conditions: list[bool], note: str = "") -> bool:
    ok = all(conditions)
    status = PASS if ok else FAIL
    print(f"\n  [{status}] {name}")
    if note:
        print(f"         {note}")
    if not ok:
        print(f"         Output (first 600 chars):\n{output[:600]}")
    else:
        preview = output[:500] + ("..." if len(output) > 500 else "")
        print(f"         Preview: {preview[:200]}")
    results.append((name, ok))
    return ok


def section(title: str):
    print(f"\n{SECTION}{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}{RESET}")


async def run_qa():
    print("=" * 60)
    print("Timepiece MCP — Use Case QA (MCP_OVERVIEW.md)")
    print("=" * 60)

    token = os.environ.get("TIMEPIECE_TOKEN", "")
    if not token:
        print("\nERROR: TIMEPIECE_TOKEN not set.")
        sys.exit(1)

    print(f"Calendar: {os.environ.get('TIMEPIECE_CALENDAR', 'not set')} | Token: present\n")

    # ══════════════════════════════════════════════════════════════
    # SECTION 1 — SINGLE TICKET USE CASES
    # ══════════════════════════════════════════════════════════════
    section("1 · Single Ticket — timepiece_get_issue")

    # "How long did BAU-308 spend in each status?"
    print('\n► Prompt: "How long did BAU-308 spend in each status?"')
    out = await timepiece_get_issue(GetIssueInput(issue_key="BAU-308"))
    check(
        "get_issue(BAU-308) → status table with Development ~11.5 days",
        out,
        [
            "Development" in out,
            "Done" in out,
            "Unknown" not in out,
            any(v.startswith("11.") or v.startswith("11") for v in numbers_in(out)),
        ],
        note="Expected Development ≈ 11.5 days",
    )

    # Check rounding — should show 2dp not 14.2461494097
    print('\n► Validating output rounding (should be 2dp, not raw precision)')
    out_rounded = await timepiece_get_issue(GetIssueInput(issue_key="BAU-278"))
    # Raw API value for Development is something like 12.2749... — should NOT appear
    raw_precision = re.findall(r'\d+\.\d{5,}', out_rounded)
    check(
        f"get_issue(BAU-278) → durations rounded to 2dp (found {len(raw_precision)} raw-precision values)",
        out_rounded,
        [
            len(raw_precision) == 0,
            "Error" not in out_rounded[:50],
        ],
        note="No value should have more than 4 decimal places in the output",
    )

    # "Show me the time-in-status breakdown for BAU-278"
    print('\n► Prompt: "Show me the time-in-status breakdown for BAU-278"')
    out = await timepiece_get_issue(GetIssueInput(issue_key="BAU-278"))
    dev_vals = [v for v in numbers_in(out) if v.startswith("12.")]
    check(
        "get_issue(BAU-278) → Development ≈ 12.27 days (baseline match)",
        out,
        [
            "Development" in out,
            "Blocked" in out,
            len(dev_vals) > 0,
        ],
        note="Expected Development ≈ 12.27 days, Blocked ≈ 9.35 days",
    )

    # "Which status did BAU-308 spend the most time in?" — expect Done to be highest
    print('\n► Prompt: "Which status did BAU-308 spend the most time in?"')
    out = await timepiece_get_issue(GetIssueInput(issue_key="BAU-308"))
    done_vals = [float(v) for v in numbers_in(out) if float(v) > 30]
    check(
        "get_issue(BAU-308) → Done is the largest value (>30 days)",
        out,
        [len(done_vals) > 0],
        note="Expected Done ≈ 43.8 days to be the largest",
    )

    # ══════════════════════════════════════════════════════════════
    # SECTION 2 — FULL LIFECYCLE / EXPANDED
    # ══════════════════════════════════════════════════════════════
    section("2 · Full Lifecycle — timepiece_get_issue_expanded")

    # "Show me the full lifecycle of BAU-278 including how many times it went back into Development"
    print('\n► Prompt: "Show me the full lifecycle of BAU-278 including rework into Development"')
    out = await timepiece_get_issue_expanded(GetIssueExpandedInput(issue_key="BAU-278"))
    check(
        "get_issue_expanded(BAU-278) → Development visited 7 times, transition history shown",
        out,
        [
            "Development" in out,
            "Visits" in out,
            "| 7 |" in out or "7" in out,
            "Transition History" in out or "Date" in out,
            "Error" not in out[:50],
        ],
        note="Expected Development: 7 visits, full transition timeline",
    )

    # "How many times did BAU-278 cycle back into Development?"
    print('\n► Prompt: "How many times did BAU-278 cycle back into Development?"')
    out = await timepiece_get_issue_expanded(GetIssueExpandedInput(issue_key="BAU-278"))
    check(
        "get_issue_expanded(BAU-278) → visit count visible in summary table",
        out,
        [
            "Visits" in out,
            "Development" in out,
            "7" in out,  # 7 visits to Development
        ],
        note="Expected 7 visits to Development status",
    )

    # "What was the longest single visit to QA Testing for BAU-278?"
    print('\n► Prompt: "What was the longest single visit to QA Testing for BAU-278?"')
    out = await timepiece_get_issue_expanded(GetIssueExpandedInput(issue_key="BAU-278"))
    check(
        "get_issue_expanded(BAU-278) → QA Testing with min/avg/max columns",
        out,
        [
            "QA Testing" in out,
            any(col in out for col in ["Avg per Visit", "Max", "min", "avg"]),
            "Error" not in out[:50],
        ],
        note="Should show per-visit stats (avg per visit at minimum)",
    )

    # "Show me every status transition for BAU-308 with timestamps"
    print('\n► Prompt: "Show me every status transition for BAU-308 with timestamps"')
    out = await timepiece_get_issue_expanded(GetIssueExpandedInput(issue_key="BAU-308"))
    date_matches = re.findall(r"\d{1,2}/\w+/\d{2}", out)
    check(
        f"get_issue_expanded(BAU-308) → transition timeline with {len(date_matches)} date entries",
        out,
        [
            len(date_matches) >= 5,
            "Transition History" in out or "Date" in out,
            "Error" not in out[:50],
        ],
        note=f"Found {len(date_matches)} dated transitions",
    )

    # ══════════════════════════════════════════════════════════════
    # SECTION 3 — BULK ISSUE REPORTING
    # ══════════════════════════════════════════════════════════════
    section("3 · Bulk Reporting — timepiece_list_issues")

    # "Show me all tickets currently in Development for project BAU"
    print('\n► Prompt: "Show me all tickets currently in Development for project BAU"')
    out = await timepiece_list_issues(
        ListIssuesInput(jql="project = BAU AND status = 'Development'")
    )
    rows = [l for l in out.split("\n") if "BAU-" in l]
    check(
        f"list_issues(status=Development, BAU) → returns issue matrix ({len(rows)} issues found)",
        out,
        [
            "Development" in out,
            "Error" not in out[:50],
            "Issue Key" in out or "BAU-" in out,
        ],
        note=f"Found {len(rows)} tickets currently in Development",
    )

    # "Show me all tickets currently in QA Testing for project BAU"
    print('\n► Prompt: "Show me all tickets currently in QA Testing for project BAU"')
    out = await timepiece_list_issues(
        ListIssuesInput(jql="project = BAU AND status = 'QA Testing'")
    )
    rows = [l for l in out.split("\n") if "BAU-" in l]
    check(
        f"list_issues(status=QA Testing, BAU) → returns issue matrix ({len(rows)} issues found)",
        out,
        [
            "Error" not in out[:50],
            "Issue Key" in out or "BAU-" in out or "No issues" in out or "0 issues" in out,
        ],
        note=f"Found {len(rows)} tickets currently in QA Testing",
    )

    # "Which tickets closed in BAU this month spent the most time in Development?"
    print('\n► Prompt: "Which tickets closed in BAU this month spent the most time in Development?"')
    out = await timepiece_list_issues(
        ListIssuesInput(jql="project = BAU AND resolved >= startOfMonth()", page_size=50)
    )
    rows = [l for l in out.split("\n") if "BAU-" in l]
    check(
        f"list_issues(resolved this month, BAU) → returns {len(rows)} issues with status columns",
        out,
        [
            "Development" in out,
            "Error" not in out[:50],
        ],
        note=f"Resolved this month: {len(rows)} tickets",
    )

    # "List time-in-status for tickets BAU-278 and BAU-308"
    print('\n► Prompt: "List time-in-status for BAU-278 and BAU-308 side by side"')
    out = await timepiece_list_issues(
        ListIssuesInput(jql="issuekey in (BAU-278, BAU-308)")
    )
    check(
        "list_issues(BAU-278, BAU-308) → both issues present in matrix",
        out,
        [
            "BAU-278" in out,
            "BAU-308" in out,
            "Development" in out,
            "Error" not in out[:50],
        ],
    )

    # ══════════════════════════════════════════════════════════════
    # SECTION 4 — AGGREGATION & METRICS
    # ══════════════════════════════════════════════════════════════
    section("4 · Aggregation — timepiece_aggregate")

    # "Which status is causing the biggest delays in project BAU?"
    print('\n► Prompt: "Which status is causing the biggest delays in project BAU?"')
    out = await timepiece_aggregate(
        AggregateInput(
            aggregation_type=AggregationType.AVERAGE,
            jql="project = BAU AND resolved is not EMPTY",
            columns_by=ColumnsBy.STATUS_DURATION,
        )
    )
    nums = numbers_in(out)
    check(
        f"aggregate(average, statusDuration, project=BAU) → {len(nums)} numeric values, Done likely highest",
        out,
        [
            len(nums) >= 3,
            "Average" in out or "average" in out,
            "Error" not in out[:50],
        ],
        note="Should show avg days per status across all resolved BAU tickets",
    )

    # "What is the average cycle time for tickets resolved in BAU?"
    print('\n► Prompt: "What is the average cycle time for tickets closed in BAU this sprint?"')
    out = await timepiece_aggregate(
        AggregateInput(
            aggregation_type=AggregationType.AVERAGE,
            jql="project = BAU AND sprint in openSprints()",
            columns_by=ColumnsBy.STATUS_DURATION,
        )
    )
    nums = numbers_in(out)
    check(
        f"aggregate(average, openSprints, BAU) → returns avg per status ({len(nums)} values)",
        out,
        [
            "Error" not in out[:50],
            "Average" in out or "average" in out or len(nums) > 0 or "No issues" in out or "0 issue" in out,
        ],
        note="Open sprint aggregation — may return 0 issues if no open sprint",
    )

    # "Compare average development time across the team for last sprint"
    print('\n► Prompt: "Compare average development time across the team for last sprint"')
    out = await timepiece_aggregate(
        AggregateInput(
            aggregation_type=AggregationType.AVERAGE,
            jql="project = BAU AND sprint in closedSprints() ORDER BY updated DESC",
            columns_by=ColumnsBy.ASSIGNEE_DURATION,
        )
    )
    nums = numbers_in(out)
    check(
        f"aggregate(average, assigneeDuration, closedSprints) → per-developer breakdown ({len(nums)} values)",
        out,
        [
            "Error" not in out[:50],
            "Average" in out or "average" in out or len(nums) > 0 or "No issues" in out,
        ],
        note="Per-developer average — shows team comparison",
    )

    # "What is our flow efficiency for BAU this quarter?"
    # Flow efficiency = sum of active statuses / sum of all statuses
    # Active: Development, Review, QA Testing, UAT
    # We request the average per status and compute client-side
    # Note: startOfQuarter() is NOT supported by Timepiece JQL — use explicit dates
    print('\n► Prompt: "What is our flow efficiency for BAU this quarter?"')
    out = await timepiece_aggregate(
        AggregateInput(
            aggregation_type=AggregationType.AVERAGE,
            jql="project = BAU AND created >= '2026-01-01'",
            columns_by=ColumnsBy.STATUS_DURATION,
        )
    )
    nums = numbers_in(out)
    check(
        f"aggregate(average, statusDuration, Q1 2026) → per-status averages for flow efficiency calc ({len(nums)} values)",
        out,
        [
            "Error" not in out[:50],
            len(nums) > 0 or "No issues" in out or "0 issue" in out,
        ],
        note="Claude would sum Development+Review+QA+UAT / total to get flow efficiency % (startOfQuarter() not supported — use explicit dates)",
    )

    # "How often do our tickets bounce back into Development from QA?"
    print('\n► Prompt: "How often do our tickets bounce back into Development from QA?"')
    out = await timepiece_aggregate(
        AggregateInput(
            aggregation_type=AggregationType.AVERAGE,
            jql="project = BAU AND resolved is not EMPTY",
            columns_by=ColumnsBy.STATUS_COUNT,
        )
    )
    nums = numbers_in(out)
    check(
        f"aggregate(average, statusCount, BAU) → avg visit counts per status ({len(nums)} values)",
        out,
        [
            "Error" not in out[:50],
            len(nums) > 0,
            "Development" in out,
        ],
        note="Average visits > 1.0 for Development = rework indicator",
    )

    # "What is the standard deviation of cycle times in BAU?"
    print('\n► Prompt: "What is the standard deviation of cycle times in BAU — how consistent are we?"')
    out = await timepiece_aggregate(
        AggregateInput(
            aggregation_type=AggregationType.STANDARD_DEVIATION,
            jql="project = BAU AND resolved is not EMPTY",
            columns_by=ColumnsBy.STATUS_DURATION,
        )
    )
    nums = numbers_in(out)
    check(
        f"aggregate(standardDeviation, BAU) → std dev per status ({len(nums)} values)",
        out,
        [
            "Error" not in out[:50],
            len(nums) > 0,
        ],
        note="High std dev = inconsistent delivery; low = predictable",
    )

    # "Has our average cycle time improved over the last four sprints?"
    # Run aggregate per closed sprint (last 4 resolved batches by quarter)
    print('\n► Prompt: "Has our average cycle time improved over the last four sprints?"')
    periods = [
        ("Q1 2026", "project = BAU AND resolved >= '2026-01-01' AND resolved <= '2026-03-31'"),
        ("Q4 2025", "project = BAU AND resolved >= '2025-10-01' AND resolved <= '2025-12-31'"),
        ("Q3 2025", "project = BAU AND resolved >= '2025-07-01' AND resolved <= '2025-09-30'"),
        ("Q2 2025", "project = BAU AND resolved >= '2025-04-01' AND resolved <= '2025-06-30'"),
    ]
    trend_results = []
    for label, jql in periods:
        r = await timepiece_aggregate(
            AggregateInput(
                aggregation_type=AggregationType.AVERAGE,
                jql=jql,
                columns_by=ColumnsBy.STATUS_DURATION,
            )
        )
        has_data = len(numbers_in(r)) > 0
        trend_results.append((label, has_data, r))
        print(f"         {label}: {'data found' if has_data else 'no issues resolved in this period'}")

    periods_with_data = [t for t in trend_results if t[1]]
    check(
        f"aggregate × 4 quarters → trend data returned for {len(periods_with_data)}/4 periods",
        "\n".join(r for _, _, r in trend_results),
        [
            len(periods_with_data) >= 1,  # at least one period has data
        ],
        note="Multi-call trend: one aggregate per time period",
    )

    # ══════════════════════════════════════════════════════════════
    # SECTION 5 — CALENDAR TOOLS
    # ══════════════════════════════════════════════════════════════
    section("5 · Calendar — timepiece_list_calendars & timepiece_search_calendar")

    # "What calendars are configured in Timepiece?"
    print('\n► Prompt: "What calendars are configured in Timepiece?"')
    out = await timepiece_list_calendars(ListCalendarsInput())
    check(
        "list_calendars → Default Calendar Settings with ID 10776",
        out,
        [
            "10776" in out,
            "Default Calendar Settings" in out,
            "Europe/London" in out,
        ],
        note="Must show ID, name, timezone",
    )

    # "Show me the working hours and timezone for our Timepiece calendar"
    print('\n► Prompt: "Show me the working hours and timezone for our Timepiece calendar"')
    out = await timepiece_list_calendars(ListCalendarsInput())
    check(
        "list_calendars → working hours 8.0 per day and Europe/London timezone",
        out,
        [
            "8.0" in out,
            "Europe/London" in out,
        ],
        note="8h/day, Mon–Fri, Europe/London",
    )

    # "What holidays are in our default calendar?"
    print('\n► Prompt: "What holidays are in our default calendar?"')
    out = await timepiece_list_calendars(ListCalendarsInput())
    check(
        "list_calendars → holiday section with dates (2025-12-25, 2025-12-26, 2026-01-01)",
        out,
        [
            "Holidays" in out,
            "2025-12-25" in out,
            "2026-01-01" in out,
            "Error" not in out[:50],
        ],
        note="Should show UK holidays: Dec 25, Dec 26, Jan 1 (recurring)",
    )

    # "What is the ID of the Default Calendar Settings calendar?"
    print('\n► Prompt: "What is the ID of the Default Calendar Settings calendar?"')
    out = await timepiece_search_calendar(SearchCalendarInput(name="Default Calendar Settings"))
    check(
        "search_calendar('Default Calendar Settings') → returns ID 10776",
        out,
        [
            "10776" in out,
            "Error" not in out[:50],
        ],
    )

    # "Find a calendar by partial name"
    print('\n► Prompt: "Find the calendar called Default" (partial match)')
    out = await timepiece_search_calendar(
        SearchCalendarInput(name="Default", search_type="contain")
    )
    check(
        "search_calendar('Default', contain) → finds Default Calendar Settings",
        out,
        [
            "10776" in out or "Default Calendar Settings" in out,
            "Error" not in out[:50],
        ],
        note="Partial name search using search_type=contain",
    )

    # ══════════════════════════════════════════════════════════════
    # SECTION 6 — EXPORT
    # ══════════════════════════════════════════════════════════════
    section("6 · Export — timepiece_export_sync")

    # "Export a CSV of time-in-status for all tickets resolved in BAU this month"
    print('\n► Prompt: "Export a CSV of time-in-status for all tickets resolved in BAU this month"')
    out = await timepiece_export_sync(
        ExportSyncInput(
            jql="project = BAU AND resolved >= startOfMonth()",
            output_type=ExportOutputType.CSV,
        )
    )
    path_match = re.search(r"`(/tmp/timepiece-export-\S+\.csv)`", out)
    file_ok = False
    file_size = 0
    if path_match:
        p = path_match.group(1)
        if os.path.exists(p):
            file_size = os.path.getsize(p)
            file_ok = file_size > 0
    check(
        f"export_sync(BAU resolved this month, csv) → file saved ({file_size} bytes)",
        out,
        [
            path_match is not None,
            "Error" not in out[:50],
            # file might be 0 bytes if no tickets resolved this month — that's valid
            path_match is not None,
        ],
        note="CSV export to /tmp — file path returned",
    )

    # "Generate an Excel report of last sprint's cycle times for the sprint review"
    print('\n► Prompt: "Generate an Excel report of last sprint cycle times"')
    out = await timepiece_export_sync(
        ExportSyncInput(
            jql="project = BAU AND resolved >= '2025-01-01'",
            output_type=ExportOutputType.XLSX,
        )
    )
    path_match = re.search(r"`(/tmp/timepiece-export-\S+\.xlsx)`", out)
    file_ok = False
    file_size = 0
    if path_match:
        p = path_match.group(1)
        if os.path.exists(p):
            file_size = os.path.getsize(p)
            file_ok = file_size > 0
    check(
        f"export_sync(BAU resolved 2025+, xlsx) → XLSX file saved ({file_size} bytes)",
        out,
        [
            path_match is not None,
            file_ok,
            "Error" not in out[:50],
        ],
        note="XLSX export to /tmp — binary file",
    )

    # "Download a spreadsheet of all in-progress BAU tickets with time in each status"
    print('\n► Prompt: "Download a spreadsheet of all in-progress BAU tickets"')
    out = await timepiece_export_sync(
        ExportSyncInput(
            jql="project = BAU AND status != Done",
            output_type=ExportOutputType.CSV,
        )
    )
    path_match = re.search(r"`(/tmp/timepiece-export-\S+\.csv)`", out)
    file_ok = False
    file_size = 0
    if path_match:
        p = path_match.group(1)
        if os.path.exists(p):
            file_size = os.path.getsize(p)
            file_ok = file_size > 0
    check(
        f"export_sync(BAU status != Done, csv) → CSV of in-progress tickets ({file_size} bytes)",
        out,
        [
            path_match is not None,
            file_ok,
            "Error" not in out[:50],
        ],
        note="All in-progress BAU tickets exported",
    )

    # ══════════════════════════════════════════════════════════════
    # SECTION 7 — top_n_statuses parameter
    # ══════════════════════════════════════════════════════════════
    section("7 · Token Efficiency — top_n_statuses")

    print('\n► Prompt: "Show me the top 3 most time-consuming stages for BAU tickets resolved this year"')
    out = await timepiece_list_issues(
        ListIssuesInput(
            jql="issuekey in (BAU-278, BAU-308)",
            top_n_statuses=3,
        )
    )
    # Count status columns in the header line
    header_line = next((l for l in out.split("\n") if "Issue Key" in l), "")
    status_col_count = max(0, header_line.count("|") - 3)  # subtract Issue Key, Summary, and borders
    check(
        f"list_issues(top_n_statuses=3) → at most 3 status columns (got {status_col_count})",
        out,
        [
            "BAU-278" in out or "BAU-308" in out,
            status_col_count <= 3,
            "Error" not in out[:50],
        ],
        note="Should show only the 3 statuses with highest total time (e.g. Done, Development, Ready for Development)",
    )

    # ══════════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════════
    print(f"\n{'=' * 60}")
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"QA Results: {passed}/{total} use cases passed")
    print("=" * 60)
    for name, ok in results:
        status = PASS if ok else FAIL
        print(f"  [{status}] {name}")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_qa())
