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
