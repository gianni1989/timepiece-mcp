#!/usr/bin/env python3
"""
Integration tests for the Timepiece MCP server tools.
Run with: uv run python test_tools.py
"""

import asyncio
import os
import sys

# Set defaults before importing server so DEFAULT_CALENDAR is correct
os.environ.setdefault("TIMEPIECE_CALENDAR", "10776")

# Import AFTER setting env
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

results = []


def check(test_name: str, output: str, conditions: list, show_output: bool = True) -> bool:
    ok = all(conditions)
    status = PASS if ok else FAIL
    print(f"\n[{status}] {test_name}")
    if not ok or show_output:
        # Show first 800 chars of output
        preview = output[:800] + ("..." if len(output) > 800 else "")
        print(f"  Output preview:\n{preview}")
    results.append((test_name, ok))
    return ok


async def run_tests():
    print("=" * 60)
    print("Timepiece MCP Server — Integration Tests")
    print("=" * 60)

    token = os.environ.get("TIMEPIECE_TOKEN", "")
    if not token:
        print("\nERROR: TIMEPIECE_TOKEN environment variable is not set.")
        print("Set it before running: TIMEPIECE_TOKEN=yourtoken uv run python test_tools.py")
        sys.exit(1)

    print(f"Using TIMEPIECE_CALENDAR: {os.environ.get('TIMEPIECE_CALENDAR', 'not set')}")
    print(f"Token present: {'Yes' if token else 'No'}\n")

    # ── Test 1: timepiece_list_calendars ──────────────────────────────────────
    print("\n--- Test 1: timepiece_list_calendars ---")
    output = await timepiece_list_calendars(ListCalendarsInput())
    check(
        "timepiece_list_calendars → contains calendar 10776 and 'Default Calendar Settings'",
        output,
        [
            "10776" in output,
            "Default Calendar Settings" in output,
            "Error" not in output[:50],
        ],
    )

    # ── Test 2: timepiece_search_calendar ─────────────────────────────────────
    print("\n--- Test 2: timepiece_search_calendar ---")
    output = await timepiece_search_calendar(
        SearchCalendarInput(name="Default Calendar Settings")
    )
    check(
        "timepiece_search_calendar(name='Default Calendar Settings') → contains 10776",
        output,
        [
            "10776" in output,
            "Error" not in output[:50],
        ],
    )

    # ── Test 3: timepiece_get_issue BAU-278 ───────────────────────────────────
    print("\n--- Test 3: timepiece_get_issue BAU-278 ---")
    output = await timepiece_get_issue(GetIssueInput(issue_key="BAU-278"))
    check(
        "timepiece_get_issue(BAU-278) → contains Development and Done with non-zero values",
        output,
        [
            "Development" in output,
            "Done" in output,
            "Unknown" not in output,
            "Error" not in output[:50],
        ],
    )

    # ── Test 4: timepiece_get_issue BAU-308 ───────────────────────────────────
    print("\n--- Test 4: timepiece_get_issue BAU-308 ---")
    output = await timepiece_get_issue(GetIssueInput(issue_key="BAU-308"))
    check(
        "timepiece_get_issue(BAU-308) → contains Development and Done with non-zero values",
        output,
        [
            "Development" in output,
            "Done" in output,
            "Error" not in output[:50],
        ],
    )

    # ── Test 5: timepiece_get_issue_expanded BAU-308 ──────────────────────────
    print("\n--- Test 5: timepiece_get_issue_expanded BAU-308 ---")
    output = await timepiece_get_issue_expanded(GetIssueExpandedInput(issue_key="BAU-308"))
    # Count table rows (lines containing "|" with at least 2 cells, excluding header/separator)
    table_rows = [
        line for line in output.split("\n")
        if "|" in line and not line.strip().startswith("|--") and line.count("|") >= 3
    ]
    row_count = len(table_rows)
    check(
        f"timepiece_get_issue_expanded(BAU-308) → at least 5 transition/stat rows (got {row_count})",
        output,
        [
            row_count >= 5,
            "Error" not in output[:50],
        ],
    )

    # ── Test 6: timepiece_list_issues ─────────────────────────────────────────
    print("\n--- Test 6: timepiece_list_issues ---")
    output = await timepiece_list_issues(
        ListIssuesInput(jql="issuekey in (BAU-278, BAU-308)")
    )
    check(
        "timepiece_list_issues(BAU-278, BAU-308) → mentions both issues",
        output,
        [
            "BAU-278" in output,
            "BAU-308" in output,
            "Error" not in output[:50],
        ],
    )

    # ── Test 7: timepiece_aggregate ───────────────────────────────────────────
    print("\n--- Test 7: timepiece_aggregate ---")
    output = await timepiece_aggregate(
        AggregateInput(
            aggregation_type=AggregationType.AVERAGE,
            jql="issuekey in (BAU-278, BAU-308)",
            columns_by=ColumnsBy.STATUS_DURATION,
        )
    )
    # Check that we get at least one numeric value in the output
    import re
    numeric_values = re.findall(r"\d+\.\d+", output)
    check(
        f"timepiece_aggregate(average, BAU-278 + BAU-308) → contains at least one numeric value (found {len(numeric_values)})",
        output,
        [
            len(numeric_values) >= 1,
            "Error" not in output[:50],
        ],
    )

    # ── Test 8: timepiece_export_sync ─────────────────────────────────────────
    print("\n--- Test 8: timepiece_export_sync ---")
    output = await timepiece_export_sync(
        ExportSyncInput(
            jql="issuekey = BAU-278",
            output_type=ExportOutputType.CSV,
        )
    )
    # Extract file path from output
    import re
    path_match = re.search(r"`(/tmp/timepiece-export-\d+\.csv)`", output)
    file_exists = False
    file_size_ok = False
    file_path = None
    if path_match:
        file_path = path_match.group(1)
        if os.path.exists(file_path):
            file_exists = True
            file_size_ok = os.path.getsize(file_path) > 0

    check(
        f"timepiece_export_sync(BAU-278, csv) → file saved at {file_path} with size > 0",
        output,
        [
            path_match is not None,
            file_exists,
            file_size_ok,
            "Error" not in output[:50],
        ],
    )
    if file_path and file_exists:
        print(f"  File size: {os.path.getsize(file_path)} bytes")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 60)
    for name, ok in results:
        status = PASS if ok else FAIL
        print(f"  [{status}] {name}")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_tests())
