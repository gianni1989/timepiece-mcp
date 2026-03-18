# timepiece-mcp

An MCP server that lets Claude query **OBSS Timepiece Time in Status** data for Jira issues.

Ask Claude things like:
- *"How long has PROJ-123 spent in each status?"*
- *"Show me time in status for PROJ-1, PROJ-2 and PROJ-3 in hours"*
- *"Compare cycle times across this sprint's tickets"*

---

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) — fast Python package manager
- A Jira instance with [Timepiece](https://marketplace.atlassian.com/apps/1211756/timepiece-time-in-status-for-jira) installed
- A personal Timepiece API token (see below)

## Get your Timepiece API token

1. In Jira, go to **Apps → Timepiece → API Settings**
2. Click **Create New Token**
3. Copy the Token ID (a UUID like `5263180f-3f08-43fd-9c77-dbda0d4a937f`)

> ⚠️ Keep this token secret — it grants access to your Jira data through Timepiece.

---

## Installation

### For Claude Desktop

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "timepiece": {
      "command": "uvx",
      "args": ["timepiece-mcp"],
      "env": {
        "TIMEPIECE_TOKEN": "your-token-uuid-here",
        "TIMEPIECE_CALENDAR": "10776"
      }
    }
  }
}
```

Restart Claude Desktop. You'll see a 🔌 icon confirming the server is connected.

### For Claude Code (CLI)

```bash
claude mcp add timepiece uvx timepiece-mcp \
  -e TIMEPIECE_TOKEN=your-token-uuid-here \
  -e TIMEPIECE_CALENDAR=10776
```

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TIMEPIECE_TOKEN` | ✅ Yes | — | Your personal Timepiece API token UUID |
| `TIMEPIECE_CALENDAR` | No | — | Default calendar ID for business-hours calculations |
| `TIMEPIECE_DEFAULT_DAY_LENGTH` | No | `businessDays` | `businessDays` or `calendarDays` |
| `TIMEPIECE_DEFAULT_VIEW_FORMAT` | No | `days` | `days`, `hours`, `minutes`, or `seconds` |

**Finding your calendar ID**: In Jira go to Apps → Timepiece → Settings → Calendars. The ID is shown next to each calendar (e.g. `10776`).

---

## Available tools

### `timepiece_get_issue`
Get time-in-status for a single Jira issue.

```
How long has PROJ-123 been in each status?
Show PROJ-456 time in status in hours using calendar days
```

### `timepiece_get_issues`
Get time-in-status for multiple Jira issues in one call.

```
Show time in status for PROJ-1, PROJ-2 and PROJ-3
Compare these tickets: ['SPRINT-10', 'SPRINT-11', 'SPRINT-12']
```

### `timepiece_export_report`
Export a time-in-status report for a set of issues as JSON.

```
Export time in status for PROJ-1 through PROJ-10
```

> **Note**: The Timepiece file export endpoint is not yet confirmed from the documentation.
> This tool currently returns structured JSON. Once the export API is verified,
> a future version will support downloading CSV/Excel files directly.

---

## Local development

```bash
git clone https://github.com/yourusername/timepiece-mcp
cd timepiece-mcp

# Copy and fill in your token
cp .env.example .env

# Install dependencies
uv sync

# Run the server (stdio mode — for testing with MCP Inspector)
uv run timepiece-mcp

# Test with MCP Inspector
npx @modelcontextprotocol/inspector uv run timepiece-mcp
```

---

## Publishing to PyPI

```bash
# Build
uv build

# Publish
uv publish
```

Once published, anyone can run it with:
```bash
uvx timepiece-mcp
```

---

## Sharing with your team

1. Publish the package to PyPI (or a private registry)
2. Each team member:
   - Gets their own Timepiece token from **Jira → Apps → Timepiece → API Settings**
   - Adds the config block above to their Claude Desktop/Code config
   - Uses their own token — tokens are personal and tied to their Jira identity

---

## Troubleshooting

**"TIMEPIECE_TOKEN environment variable is not set"**
→ Add `TIMEPIECE_TOKEN` to the `env` block in your Claude config and restart.

**"Unauthorised — your TIMEPIECE_TOKEN is invalid or expired"**
→ Check the token in Jira → Apps → Timepiece → API Settings. Tokens expire 31 Dec 2026 by default.

**"Not found — the issue key does not exist"**
→ Verify the issue key format: it must be `PROJECT-NUMBER` in uppercase, e.g. `PROJ-123`.

**Issue shows all zeros / missing statuses**
→ Try without the `statuses` filter first, then narrow down. Status IDs can be found in Timepiece settings.
