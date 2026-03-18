# timepiece-mcp

An MCP server that lets Claude query **OBSS Timepiece Time in Status** data for Jira issues.

Ask Claude things like:
- *"How long has PROJ-123 spent in each status?"*
- *"Show me the full lifecycle of PROJ-456 including how many times it went back into Development"*
- *"What is the average cycle time for tickets closed this sprint?"*
- *"Which status is causing the biggest delays in our project?"*
- *"Export a CSV of time-in-status for all tickets resolved this month"*

---

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) — fast Python package manager
- A Jira instance with [Timepiece](https://marketplace.atlassian.com/apps/1211756/timepiece-time-in-status-for-jira) installed
- A personal Timepiece API token (see below)

## Get your Timepiece API token

1. In Jira, go to **Apps → Timepiece → API Settings**
2. Click **Create New Token**
3. Copy the token

> ⚠️ Keep this token secret — it grants access to your Jira data through Timepiece.

---

## Installation

### Claude Desktop

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "timepiece": {
      "command": "uvx",
      "args": ["timepiece-mcp"],
      "env": {
        "TIMEPIECE_TOKEN": "your-token-here",
        "TIMEPIECE_CALENDAR": "your-calendar-id"
      }
    }
  }
}
```

Restart Claude Desktop. You'll see a 🔌 icon confirming the server is connected.

### Claude Code (CLI)

```bash
claude mcp add timepiece uvx timepiece-mcp \
  -e TIMEPIECE_TOKEN=your-token-here \
  -e TIMEPIECE_CALENDAR=your-calendar-id
```

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TIMEPIECE_TOKEN` | ✅ Yes | — | Your personal Timepiece API token |
| `TIMEPIECE_CALENDAR` | Recommended | — | Default calendar ID for business-hours calculations. Without this, durations use a 24h/day UTC clock and will be wrong for most teams. |
| `TIMEPIECE_DEFAULT_DAY_LENGTH` | No | `businessDays` | `businessDays` or `calendarDays` |
| `TIMEPIECE_DEFAULT_VIEW_FORMAT` | No | `days` | `days`, `hours`, `minutes`, or `seconds` |

**Finding your calendar ID**: In Jira go to **Apps → Timepiece → Settings → Calendars**. The numeric ID is shown next to each calendar. You can also ask Claude to run `timepiece_list_calendars` after setup to see all available calendars and their IDs.

---

## Available tools

| Tool | What it does |
|------|-------------|
| `timepiece_get_issue` | Time spent in each status for a single issue — returned as a Status / Duration / Visits table |
| `timepiece_get_issue_expanded` | Full status history for a single issue: visit counts, min/max/average per status, and a chronological transition timeline |
| `timepiece_list_issues` | Time-in-status for a set of issues defined by a JQL query, returned as an issues × statuses matrix |
| `timepiece_aggregate` | Average, median, sum or standard deviation of time-in-status across any JQL-filtered set of issues; also supports lead time and cycle time calculations |
| `timepiece_list_calendars` | Lists all Timepiece calendars configured for your Jira instance, including IDs, timezones and working hours |
| `timepiece_search_calendar` | Finds a calendar by name and returns its ID |
| `timepiece_export_sync` | Exports a time-in-status report as CSV or XLSX for any JQL-filtered set of issues, saving the file locally |

---

## Example prompts

```
How long did PROJ-123 spend in each status?
Show me the full lifecycle of PROJ-456 including how many times it went back into Development
What is the average cycle time for tickets closed in PROJ this sprint?
Which status is causing the biggest delays in project PROJ?
Compare average development time across the team for last sprint
Export a CSV of time-in-status for all PROJ tickets resolved this month
What calendars are configured in Timepiece?
```

---

## Sharing with your team

Each team member needs their own Timepiece token:

1. Get a token from **Jira → Apps → Timepiece → API Settings**
2. Add the config block above to their Claude Desktop or Claude Code config
3. Use their own token — tokens are personal and tied to each person's Jira identity

---

## Local development

```bash
git clone https://github.com/gianni1989/timepiece-mcp
cd timepiece-mcp
cp .env.example .env   # fill in your token and calendar ID
uv sync
uv run timepiece-mcp
```

Run the test suite:

```bash
TIMEPIECE_TOKEN=your-token TIMEPIECE_CALENDAR=your-calendar-id uv run python test_tools.py
```

---

## Troubleshooting

**"TIMEPIECE_TOKEN environment variable is not set"**
→ Add `TIMEPIECE_TOKEN` to the `env` block in your Claude config and restart.

**"Unauthorised — your TIMEPIECE_TOKEN is invalid or expired"**
→ Go to Jira → Apps → Timepiece → API Settings and generate a new token.

**"Not found — the issue key does not exist"**
→ Verify the issue key format: it must be `PROJECT-NUMBER` in uppercase, e.g. `PROJ-123`.

**Durations seem too large (e.g. 3× bigger than expected)**
→ Set `TIMEPIECE_CALENDAR` to your calendar's numeric ID. Without it, the API uses a 24h/day UTC clock instead of your business hours.
