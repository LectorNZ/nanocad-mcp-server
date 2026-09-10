# nanocad-mcp-server

A local MCP (Model Context Protocol) plugin that bridges an AI coding agent
(e.g. Claude Code) to a running **nanoCAD x64 26.0** instance on Windows, via
its COM (ActiveX) automation interface — which closely mirrors AutoCAD's
ActiveX object model.

Modeled after the official `intellicad-ai` Claude Code plugin, but hand-built
against nanoCAD's `nanoCADx64.Application.26.0` COM ProgID since no official
AI/MCP plugin exists for nanoCAD.

## Layout

```
.claude-plugin/marketplace.json         # plugin marketplace manifest
plugins/nanocad-ai/.claude-plugin/      # plugin manifest
plugins/nanocad-ai/.mcp.json            # MCP server launch config
plugins/nanocad-ai/server/nanocad_server.py       # the actual MCP server
plugins/nanocad-ai/nanocad/claude_bridge_commands.lsp  # CLAUDESTATUS / CLAUDEHELP commands
plugins/nanocad-ai/README.md            # tool reference + implementation notes
```

## Requirements

- Windows with nanoCAD x64 26.0 installed and running (a document open).
- Python 3.12+ with `pywin32` and `mcp` (`pip install pywin32 "mcp[cli]"`).

## Install into Claude Code

Claude Code plugins register via `~/.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "nanocad-ai": { "source": { "source": "directory", "path": "<path to this repo>" } }
  },
  "enabledPlugins": {
    "nanocad-ai@nanocad-ai": true
  }
}
```

Merge those keys into your existing `settings.json` (don't overwrite other
entries), then restart Claude Code so it picks up the new MCP server. Update
the `command`/`args` paths in `plugins/nanocad-ai/.mcp.json` to match your
local Python install.

See `plugins/nanocad-ai/README.md` for the full tool list and implementation
notes (including a SendCommand gotcha worth knowing about before extending
this).

## In-nanoCAD helper commands

`plugins/nanocad-ai/nanocad/claude_bridge_commands.lsp` adds two commands you
can run directly inside nanoCAD, independent of Claude:

- `CLAUDESTATUS` - prints nanoCAD version/document name and a bridge status
  reminder to the command line.
- `CLAUDEHELP` - shows the same info plus the daily workflow in a dialog.

Load once with `(load "...claude_bridge_commands.lsp")`, or add it to
nanoCAD's Startup Suite (`APPLOAD` command) to have it available every time
nanoCAD starts.

## Setup & usage guide

A full illustrated walkthrough (daily workflow, Startup Suite steps, and the
"Object selection" dialog gotcha) is published here:
https://claude.ai/code/artifact/1e63d35e-36ab-4f46-9441-3cd9fc8973ca
