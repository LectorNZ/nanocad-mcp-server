# nanocad-ai

Local, self-built MCP plugin bridging Claude Code to a running **nanoCAD x64 26.0**
instance via its COM (ActiveX) automation interface (`nanoCADx64.Application.26.0`),
which closely mirrors AutoCAD's ActiveX object model.

## Requirements
- nanoCAD x64 26.0 must already be running with a document open before any tool
  in this server is called (the server attaches to the live instance; it does not
  launch nanoCAD itself).
- Python 3.12 with `pywin32` and `mcp` installed (see `server/nanocad_server.py`).

## Tools
- `product_information` - version/caption of the running nanoCAD instance.
- `current_drawing_information` - active document name/path/saved state.
- `run_command` - sends a raw command-line string via `SendCommand`. Uses native
  AutoCAD/nanoCAD convention: **spaces terminate/confirm input, not semicolons**.
  Every call is automatically prefixed with a double-Escape so it never bleeds
  into a command left open by a previous call.
- `run_lisp` - loads and runs an AutoLISP `.lsp` file by path.
- `discover_entities` - entity-type counts for model space or a named block.
- `discover_entities_by_type` - compact property dump (geometry, layer, text,
  etc.) for all entities of a given type.
- `save_drawing` - `SaveAs` to a given `.dwg` path.

## Notes / lessons learned building this
- The COM ProgID for automation is `nanoCADx64.Application.26.0` (also
  `nanoCADx64.Application` unversioned). Confirmed via
  `HKLM:\SOFTWARE\Classes`.
- `SendCommand` requires careful terminator counting exactly like classic
  AutoCAD scripting: a command left "open" (e.g. `LINE` still prompting for
  the next point) will silently swallow the *next* `SendCommand` call's
  tokens instead of starting a new command. Always over-terminate, or rely on
  the built-in `\x03\x03` (ESC ESC) prefix this server adds automatically.
- Cyrillic / non-ASCII text passed through Python -> COM -> LISP `TEXT`
  round-trips correctly with no extra encoding handling needed.
