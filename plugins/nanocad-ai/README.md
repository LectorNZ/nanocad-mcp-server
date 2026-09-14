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
- `set_current_layer` - sets the current layer via COM (`doc.ActiveLayer`),
  more reliable than driving `-LAYER` on the command line.
- `add_dim_aligned` / `add_dim_diametric` / `add_dim_radial` - create
  dimensions directly via COM (`ModelSpace.AddDim*`), bypassing command-line
  object-selection-by-point entirely. Prefer these over `DIMLINEAR`/
  `DIMDIAMETER`/`DIMRADIUS` in `run_command`/`run_lisp` (see caution below).
- `set_entity_property` - sets one property (Layer, TextOverride, ...) on an
  entity by handle; more reliable than `CHPROP` for one-off fixes.
- `discover_entities` - entity-type counts for model space or a named block.
- `discover_entities_by_type` - compact property dump (geometry, layer, text,
  etc.) for all entities of a given type.
- `save_drawing` - `SaveAs` to a given `.dwg` path. Works reliably first try
  (unlike driving `SAVEAS` through the command line, which is fussier).

## Notes / lessons learned building this

Validated end-to-end by porting a real multi-view mechanical drawing
digitization (originally built for an IntelliCAD MCP plugin) over to this
server against a live nanoCAD 26 session - 115 entities, byte-for-byte
matching entity-type counts with the IntelliCAD version once the fixes below
were applied.

- The COM ProgID for automation is `nanoCADx64.Application.26.0` (also
  `nanoCADx64.Application` unversioned). Confirmed via
  `HKLM:\SOFTWARE\Classes`.
- `SendCommand` requires careful terminator counting exactly like classic
  AutoCAD scripting: a command left "open" (e.g. `LINE` still prompting for
  the next point) will silently swallow the *next* `SendCommand` call's
  tokens instead of starting a new command. Always over-terminate, or rely on
  the built-in `\x03\x03` (ESC ESC) prefix this server adds automatically.
- **Object-selection-by-point commands can pop a blocking modal dialog.**
  `DIMDIAMETER`/`DIMRADIUS` (and anything else that picks an entity via a
  single coordinate) will show an "Object selection" dialog when the point
  is ambiguous - e.g. it lies on both a circle and a centerline crossing it.
  That dialog steals focus from the command line, so *every* subsequent
  `SendCommand` silently no-ops (before/after counts stay equal, no
  exception) until a human closes the dialog - there is no way to detect or
  dismiss it purely over COM. This is why `add_dim_diametric`/
  `add_dim_radial`/`add_dim_aligned` exist: they take explicit geometry via
  `ModelSpace.AddDim*` and can never trigger this dialog. Prefer them.
- `CMDACTIVE`/`CMDNAMES` are not reliable "is a command still open" signals
  in practice - they can report a stale command name (and `CMDACTIVE=1`)
  long after the command line is actually idle and accepting new input, and
  conversely stay unchanged through a real freeze. Don't gate logic on them;
  verify real state via `ModelSpace.Count` / `discover_entities` instead.
- `SendCommand` can return control to the caller before a long multi-step
  script (e.g. a `(load "big.lsp")`) has actually finished executing inside
  nanoCAD - the before/after counts returned by `run_command`/`run_lisp` can
  under-report. Treat them as approximate; re-check with `discover_entities`
  after a short pause for anything non-trivial.
- Setting entity properties directly via COM (`ent.Layer = "X"`,
  `ent.TextOverride = "Y"`) is fast and reliable - prefer it over `CHPROP`
  command-line calls for one-off fixes.
- Cyrillic / non-ASCII text passed through Python -> COM -> LISP `TEXT`
  round-trips correctly with no extra encoding handling needed.

## 3D solid modeling

Also validated live: 3D primitives via COM, and a full revolved solid via the
`REVOLVE` command (built a piston by revolving its 2D section profile 360°
around its axis - same profile, same result in both IntelliCAD and nanoCAD).

- `ModelSpace.AddBox`/`AddCylinder`/`AddCone` work out of the box and create
  real `AcDb3dSolid` entities. **Argument order for `AddCylinder`/`AddCone`
  is `(Center, Radius, Height)`**, not `(Center, Height, Radius)` as older
  AutoCAD-family docs might suggest - verify with `GetBoundingBox()` after
  creating one if in doubt (a swapped radius/height is easy to misread as
  correct at a glance).
- `ModelSpace.AddSphere(Center, Radius)` creates an entity (valid handle,
  `EntityName` `AcDb3dSolid`, increments `ModelSpace.Count`) but its
  `GetBoundingBox()` reliably returns a degenerate inverted box
  (`(1e20,1e20,1e20) / (-1e20,-1e20,-1e20)`) - reproduced twice, including
  after `REGEN` and after deleting/recreating it. Treat `AddSphere` as
  unreliable in this nanoCAD build until proven otherwise; box/cylinder/cone
  are solid.
- The `REVOLVE` command (and likely `EXTRUDE`/`LOFT`/`SWEEP`/boolean
  commands - not yet individually re-tested post-fix) **failed silently** as
  a plain `SendCommand`/LISP `(command "REVOLVE" ...)` call: no error, no
  entity created, no modal dialog - just nothing, while `ModelSpace.AddRegion`
  on the same profile worked fine via COM in the same session. This pointed
  at a licensing/edition gap (base nanoCAD x64 vs. a Mechanica/Pro-tier 3D
  modeling module) rather than a scripting bug. After the user licensed the
  3D module, the *exact same* LISP call succeeded immediately - no code
  change needed. If `REVOLVE`/`EXTRUDE` et al. silently no-op on a fresh
  setup, check the license/edition before debugging the script further.
  `AddRegion` succeeding is a useful probe: if it works but `REVOLVE`
  doesn't, that's a strong signal the gap is command-level licensing, not a
  COM/automation problem.
- Selecting a specific entity for an operation (e.g. the profile to revolve)
  by handle - `(handent "3A2")` -> `(ssadd e (ssadd))` -> pass that selection
  set to `command` - is far more reliable than `"L"` (Last) once other
  entities have been created in between, and avoids point-pick ambiguity
  entirely.

## Adding a real UI menu item (working solution)

Goal: a clickable menu entry for `CLAUDESTATUS`/`CLAUDEHELP` (see
`nanocad/claude_bridge_commands.lsp`), not just typed commands. Three
approaches were tried; only the last one actually works and survives a
restart.

**1. `(menuload "file.mnu")` - dead end, and a real footgun.** Classic MNU
text-menu format. Two failure modes found:
  - Loading a `.lsp` **file** that contains the bare symbol `menuload`
    anywhere in it (even inside `(fboundp 'menuload)`, never called) makes
    the *entire file load silently abort before the first line executes* -
    confirmed with a minimal repro that writes nothing to a log file when
    `menuload` is present, and writes fine with it removed. This is a
    parse/load-time failure, not a runtime error, and nothing (not even
    `vl-catch-all-apply`) catches it because the file never starts running.
  - Workaround: invoke `menuload` via `run_command` (raw `SendCommand` text,
    i.e. typed at the command line) instead of `run_lisp` (which wraps the
    call in a `(load "file")`). This works fine - no crash.
  - Even then, `(menuload "path.mnu")` returns `nil` cleanly (no exception).
    nanoCAD 26 does not support the legacy `.mnu` format - the function
    exists for API compatibility but rejects the file type silently.

**2. CUIX (ribbon) injection - loads without error, but never appears.**
  - `.cuix` files are plain ZIP archives (confirmed via 7-Zip) containing an
    XML file (e.g. `RibbonRoot.cui`) with `RibbonPanelSourceCollection` /
    `RibbonTabSourceCollection` elements. Real, minimal examples ship at
    `<nanoCAD install>\UserDataCache\config\mcsmenu.cuix` and
    `spdsmenu.cuix` - extract one to see the exact schema before
    hand-authoring your own (this is how a `RibbonCommandButton`'s
    `MenuMacroID` attribute mapping to a bare command name was confirmed).
  - `-CUILOAD "path.cuix" ` (space-terminated, run via `run_command`) returns
    success with no error, no dialog, no hang.
  - The new tab still never showed up in the ribbon, even after a full
    nanoCAD restart. `(getvar "WSCURRENT")` returns `nil` in this build, so
    the usual AutoCAD "workspace doesn't list the new tab" explanation
    doesn't even apply here - the mechanism this build actually uses for
    ribbon tab visibility was never identified. Treat ad-hoc `-CUILOAD` of a
    hand-built partial CUIX as unreliable on this platform.

**3. Native `.cfg` menu format - this is what actually works.** nanoCAD's
*classic* dropdown menu (File/Edit/View/...) is driven by a completely
separate, proprietary, plain-text INI-style format - not MNU, not CUIX.
Discovered by reading `<nanoCAD install>\mcsmenu.cfg` (referenced from
`...\config\nanoCAD.cfg` via `#include`), which defines the whole Mechanica
menu tree this way:
```
[\menu\Mechanical]              |name=sMechanical
[\menu\Mechanical\mcDesign\joint] |name=sThreaded fastening |intername=smcjoint
```
`nanoCAD.cfg` also has `#include "userdata.cfg"` and
`#include "user_ribbon.cfg"` near the end - two user-customization hook
files that are `#include`d unconditionally but **do not exist by default**
(confirmed: neither is present anywhere under the install dir or the
per-user `AppData\Roaming\Nanosoft AS\nanoCAD x64 26.0\config\` profile
folder), so nanoCAD clearly tolerates them being absent - creating one is
additive/safe.

Working fix: create
`%APPDATA%\Nanosoft AS\nanoCAD x64 26.0\config\userdata.cfg`:
```
[\menu\ClaudeAI] |name=sClaude AI

[\menu\ClaudeAI\status] |name=sConnection status |intername=sCLAUDESTATUS
[\menu\ClaudeAI\help] |name=sHelp |intername=sCLAUDEHELP
```
`[\menu\ClaudeAI]` at the top level (no parent segment) becomes a new
top-level menu, exactly like the built-in `[\menu\File]` / `[\menu\Edit]`
entries in the base config. `intername=s<COMMANDNAME>` just needs to match
an existing command name (here, the two LISP commands from
`claude_bridge_commands.lsp` - no separate `[\configman\commands\...]`
registration block turned out to be necessary for a plain LISP-defined
command, unlike the compiled/icon-bearing Mechanica commands which do
register one).

Confirmed live: after creating this file and restarting nanoCAD, "Claude AI"
appeared as a new top-level classic menu with both items, clickable and
running the underlying commands. Requires a restart - these `.cfg` files
are read at startup, not hot-reloaded. This has **not** been tried for the
ribbon UI (`user_ribbon.cfg` likely wants the `.cfg` include-directive
syntax pointing at a `.cuix`, similar to `#include ... "mcsmenu.cfg"` in the
base config plus its sibling `mcsmenu.cuix` - untested).
