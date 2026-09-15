"""
Local MCP server bridging Claude Code to a running nanoCAD 26 instance via
its COM (ActiveX) automation interface, which closely mirrors AutoCAD's.

Requires: nanoCAD x64 26.0 already running with a document open.
"""
import os
import sys
import time

import httpx
import pythoncom
import win32com.client
from mcp.server.fastmcp import FastMCP

PROGID_CANDIDATES = [
    "nanoCADx64.Application.26.0",
    "nanoCADx64.Application",
]

mcp = FastMCP("nanocad-application-server")


def _get_app():
    pythoncom.CoInitialize()
    last_err = None
    for progid in PROGID_CANDIDATES:
        try:
            return win32com.client.GetActiveObject(progid)
        except Exception as e:
            last_err = e
    raise RuntimeError(
        "Could not attach to a running nanoCAD 26 instance (%s). "
        "Please make sure nanoCAD x64 26.0 is open." % last_err
    )


def _get_doc():
    app = _get_app()
    if app.Documents.Count == 0:
        raise RuntimeError("nanoCAD is running but has no open document.")
    return app.ActiveDocument


def _get_space(doc, blockName: str):
    if not blockName:
        return doc.ModelSpace
    return doc.Blocks.Item(blockName)


ESC = chr(3)  # SendCommand's escape/cancel sequence (not chr(27))


def _send(doc, command: str):
    """Sends a command, first cancelling any lingering open command so
    calls never bleed into each other's prompt state."""
    doc.SendCommand(ESC + ESC + command)
    time.sleep(0.2)


@mcp.tool()
def product_information() -> dict:
    """Returns nanoCAD product information (version, caption)."""
    app = _get_app()
    return {
        "Version": app.Version,
        "Caption": app.Caption,
        "Visible": bool(app.Visible),
        "DocumentsCount": app.Documents.Count,
    }


@mcp.tool()
def current_drawing_information() -> dict:
    """Returns current drawing information (name, full path, saved state)."""
    doc = _get_doc()
    try:
        full_name = doc.FullName
    except Exception:
        full_name = None
    return {
        "Name": doc.Name,
        "FullName": full_name,
        "Saved": bool(doc.Saved),
    }


@mcp.tool()
def run_command(command: str) -> dict:
    """Runs a CAD command line via SendCommand.

    IMPORTANT syntax note (native AutoCAD/nanoCAD SendCommand convention,
    NOT semicolon-delimited): each token (command name, option, point,
    value) is separated by a SPACE, and a trailing space represents
    pressing Enter to finish/confirm. Example:
      "CIRCLE 0,0 5 "      -> draws a circle at origin, radius 5
      "LINE 0,0 10,10 20,0  "  -> polyline-style multi-segment line, then
                                   an extra trailing space to end the command

    CAUTION - object-selection-by-point commands (DIMDIAMETER, DIMRADIUS,
    anything that picks an entity via a single coordinate) can pop a modal
    "Object selection" dialog when the point is ambiguous (e.g. it lies on
    two overlapping entities, such as a circle crossed by a centerline).
    That dialog blocks SendCommand entirely -  every subsequent call will
    silently no-op (before/after counts equal) until a human closes it.
    Prefer add_dim_diametric / add_dim_radial / add_dim_aligned below for
    dimensioning - they take explicit geometry, never pick by screen point,
    and cannot trigger this dialog.

    The returned before/after counts are read immediately after SendCommand
    returns, which for a long-running command (or a run_lisp script with
    many steps) can race ahead of nanoCAD actually finishing - treat them as
    a rough signal only; call discover_entities afterwards for the ground
    truth.
    """
    doc = _get_doc()
    before = doc.ModelSpace.Count
    _send(doc, command)
    after = doc.ModelSpace.Count
    return {"status": "success", "modelSpaceCountBefore": before, "modelSpaceCountAfter": after}


@mcp.tool()
def run_lisp(lispFilePath: str) -> dict:
    """Runs an AutoLISP (.lsp) file located at the given path inside nanoCAD.

    See the object-selection-dialog caution on run_command - it applies here
    too if the script contains point-picking commands. The returned counts
    are approximate for the same reason (SendCommand can return before a
    multi-step script has fully executed); re-check with discover_entities
    after a short pause for anything beyond a trivial script.
    """
    if not os.path.isfile(lispFilePath):
        raise FileNotFoundError(lispFilePath)
    doc = _get_doc()
    safe_path = lispFilePath.replace("\\", "/")
    before = doc.ModelSpace.Count
    _send(doc, '(load "%s") ' % safe_path)
    time.sleep(0.5)
    after = doc.ModelSpace.Count
    return {"status": "success", "modelSpaceCountBefore": before, "modelSpaceCountAfter": after}


def _variant_point(x: float, y: float, z: float = 0.0):
    return win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8, (float(x), float(y), float(z))
    )


@mcp.tool()
def set_current_layer(layerName: str) -> dict:
    """Sets the current/active layer via COM (doc.ActiveLayer), which is
    more reliable than driving the -LAYER command line for this purpose."""
    doc = _get_doc()
    doc.ActiveLayer = doc.Layers.Item(layerName)
    return {"status": "success", "activeLayer": doc.ActiveLayer.Name}


@mcp.tool()
def add_dim_aligned(x1: float, y1: float, x2: float, y2: float,
                     textX: float, textY: float, textOverride: str = "") -> dict:
    """Creates an aligned linear dimension directly via COM
    (ModelSpace.AddDimAligned) between (x1,y1) and (x2,y2), with the
    dimension line/text placed at (textX,textY). Use this instead of the
    DIMLINEAR command when you want a guaranteed, non-interactive result.
    Pass textOverride to replace the auto-measured text (e.g. to add
    tolerances, e.g. "44-0.34")."""
    doc = _get_doc()
    d = doc.ModelSpace.AddDimAligned(
        _variant_point(x1, y1), _variant_point(x2, y2), _variant_point(textX, textY)
    )
    if textOverride:
        d.TextOverride = textOverride
    return {"status": "success", "handle": d.Handle, "measurement": d.Measurement}


@mcp.tool()
def add_dim_diametric(centerX: float, centerY: float, edgeX: float, edgeY: float,
                       leaderLength: float, textOverride: str = "") -> dict:
    """Creates a diametric dimension directly via COM
    (ModelSpace.AddDimDiametric) for a circle centered at (centerX,centerY),
    using (edgeX,edgeY) - a point on the circle's circumference - to define
    which side the leader points to. Avoids DIMDIAMETER's point-pick, which
    can pop a blocking "Object selection" dialog if ambiguous. Pass
    textOverride to show the source drawing's exact text (e.g. "%%c54")."""
    doc = _get_doc()
    d = doc.ModelSpace.AddDimDiametric(
        _variant_point(centerX, centerY), _variant_point(edgeX, edgeY), float(leaderLength)
    )
    if textOverride:
        d.TextOverride = textOverride
    return {"status": "success", "handle": d.Handle, "measurement": d.Measurement}


@mcp.tool()
def add_dim_radial(centerX: float, centerY: float, edgeX: float, edgeY: float,
                    leaderLength: float, textOverride: str = "") -> dict:
    """Creates a radial dimension directly via COM (ModelSpace.AddDimRadial)
    for an arc/circle centered at (centerX,centerY), using (edgeX,edgeY) - a
    point on the circumference - to define the leader direction. Avoids
    DIMRADIUS's point-pick dialog risk, same as add_dim_diametric."""
    doc = _get_doc()
    d = doc.ModelSpace.AddDimRadial(
        _variant_point(centerX, centerY), _variant_point(edgeX, edgeY), float(leaderLength)
    )
    if textOverride:
        d.TextOverride = textOverride
    return {"status": "success", "handle": d.Handle, "measurement": d.Measurement}


@mcp.tool()
def set_entity_property(handle: str, propertyName: str, value: str, blockName: str = "") -> dict:
    """Sets a single string-valued property (e.g. Layer, TextOverride,
    TextString, Color) on the entity with the given handle, found in model
    space or a named block. More reliable than CHPROP for one-off fixes."""
    doc = _get_doc()
    space = _get_space(doc, blockName)
    for ent in space:
        if ent.Handle == handle:
            setattr(ent, propertyName, value)
            return {"status": "success", "handle": handle, propertyName: getattr(ent, propertyName)}
    raise ValueError("No entity with handle %s found" % handle)


def _entity_summary(ent) -> dict:
    name = ent.EntityName
    out = {"Handle": ent.Handle, "EntityName": name}
    try:
        out["Layer"] = ent.Layer
    except Exception:
        pass
    try:
        if name in ("AcDbCircle",):
            out["Center"] = tuple(ent.Center)
            out["Radius"] = ent.Radius
        elif name in ("AcDbArc",):
            out["Center"] = tuple(ent.Center)
            out["Radius"] = ent.Radius
            out["StartAngle"] = ent.StartAngle
            out["EndAngle"] = ent.EndAngle
        elif name in ("AcDbLine",):
            out["StartPoint"] = tuple(ent.StartPoint)
            out["EndPoint"] = tuple(ent.EndPoint)
        elif name in ("AcDbText", "AcDbMText"):
            out["TextString"] = ent.TextString
            out["InsertionPoint"] = tuple(ent.InsertionPoint)
            out["Height"] = ent.Height
        elif name in ("AcDbPolyline", "AcDb2dPolyline"):
            try:
                out["Coordinates"] = list(ent.Coordinates)
            except Exception:
                pass
            try:
                out["Closed"] = bool(ent.Closed)
            except Exception:
                pass
        elif "Dimension" in name:
            try:
                out["Measurement"] = ent.Measurement
            except Exception:
                pass
            try:
                out["TextOverride"] = ent.TextOverride
            except Exception:
                pass
        elif name == "AcDbHatch":
            try:
                out["PatternName"] = ent.PatternName
            except Exception:
                pass
            try:
                out["Area"] = ent.Area
            except Exception:
                pass
    except Exception as e:
        out["_propError"] = str(e)
    return out


@mcp.tool()
def discover_entities(blockName: str = "") -> dict:
    """Returns entity-type counts for the current drawing (or a named block).

    Pass an empty string for blockName to use model space.
    """
    doc = _get_doc()
    space = _get_space(doc, blockName)
    counts = {}
    for ent in space:
        counts[ent.EntityName] = counts.get(ent.EntityName, 0) + 1
    return {"status": "success", "count": space.Count, "entityTypes": counts}


@mcp.tool()
def discover_entities_by_type(entityType: str, blockName: str = "") -> dict:
    """Returns compact property data for all entities of a given type
    (e.g. 'AcDbLine', 'AcDbCircle', 'AcDbArc', 'AcDbText', 'AcDbPolyline').
    Pass an empty string for blockName to use model space.
    """
    doc = _get_doc()
    space = _get_space(doc, blockName)
    results = []
    for ent in space:
        if not entityType or ent.EntityName == entityType:
            results.append(_entity_summary(ent))
    return {"status": "success", "count": len(results), "entities": results}


@mcp.tool()
def save_drawing(filePath: str) -> dict:
    """Saves the current drawing to the given .dwg path (SaveAs)."""
    doc = _get_doc()
    doc.SaveAs(filePath)
    return {"status": "success", "path": filePath}


# ── Parametric feature bridge (.NET CadEngine.Plugin, HTTP :5080) ──────
#
# COM/ActiveX (above) is the stable, battle-tested path for entity
# creation, discovery, dimensions and simple 3D primitives/booleans - use
# it whenever it covers the job. It does NOT give live-editable parametric
# features, and its REVOLVE-family operations (vla-AddRevolvedSolid,
# SendCommand REVOLVE, LISP (command "REVOLVE")) all fail on this install
# with no code-side fix available - confirmed by direct COM testing to be
# a licensing/edition gap (base nanoCAD x64 vs. Mechanica/Pro's 3D
# module), not a scripting bug. See README "3D solid modeling" section.
#
# The tools below talk to a separate .NET plugin (CadEngine.Plugin.dll,
# loaded into nanoCAD via nCad.ini [\NetModules], HTTP on localhost:5080)
# that exposes MultiCAD's native Mc3dSolid feature-tree API. Its EXTRUDE
# path is fully validated (exact volume/centroid, live edit_feature_parameter
# round-trips correctly) — use it when a feature genuinely needs to stay
# live-editable inside nanoCAD's own history tree, not as a general
# replacement for the COM tools above. Its REVOLVE path has the same
# licensing wall as COM/LISP, plus its own now-abandoned GSMarker
# complications on top - don't use create_revolve_feature; build bodies
# of revolution as a stack of extrude "washers" instead (see
# create_extrude_feature below), or fall back to COM's AddRevolvedSolid
# once the 3D module is licensed.

NET_ENGINE_BASE = os.environ.get("NANOCAD_NET_ENGINE_URL", "http://localhost:5080")


def _net(method: str, path: str, **json_body) -> dict:
    """POST/GET to the .NET CadEngine.Plugin HTTP API and return the
    decoded JSON body. Raises RuntimeError with the plugin's own error
    message on failure (mirrors the shape nanoCAD-MCP's http_bridge used)."""
    url = NET_ENGINE_BASE + path
    try:
        if method == "GET":
            resp = httpx.get(url, timeout=30)
        else:
            resp = httpx.post(url, json=json_body, timeout=30)
    except httpx.ConnectError as e:
        raise RuntimeError(
            "Could not reach the .NET CadEngine.Plugin at %s (%s). "
            "Is nanoCAD running with the plugin loaded? "
            "Check %%LOCALAPPDATA%%\\Temp\\ncad-mcp-engine-.log." % (url, e)
        )
    data = resp.json() if resp.content else {}
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError("CadEngine.Plugin error: %s" % data["error"])
    return data


@mcp.tool()
def net_health_check() -> dict:
    """Checks the .NET CadEngine.Plugin HTTP bridge (parametric feature
    API), separately from the COM connection product_information checks."""
    return _net("GET", "/api/system/health")


@mcp.tool()
def new_document_parametric() -> dict:
    """Creates a new empty document via the .NET engine. Use this (not a
    COM NEW/QNEW command) before building parametric features, since the
    bootstrap Mc3dSolid tracking below is keyed to whichever document the
    .NET plugin currently sees as active."""
    return _net("POST", "/api/document/new")


@mcp.tool()
def create_sketch(solid_handle: str = "", plane_z: float = 0.0) -> dict:
    """Creates a planar sketch, horizontal at world Z=plane_z, on a
    parametric Mc3dSolid. Pass solid_handle="" the first time in a
    document to bootstrap a brand-new parametric body (there is no
    separate "create solid" call - the .NET Mc3dSolid API has no factory
    for an empty body, so this plugin fakes one: an unresolvable handle
    creates one and remembers it for subsequent "" calls in the same
    document). All geometry added to this sketch (add_sketch_line/
    add_sketch_circle) must share this same Z - PlanarSketch enforces
    planarity, and mismatched Z reliably crashes nanoCAD outright."""
    return _net("POST", "/api/feature/sketch", solid_handle=solid_handle, plane_z=plane_z)


@mcp.tool()
def add_sketch_line(sketch_handle: str, x1: float, y1: float, z1: float,
                     x2: float, y2: float, z2: float) -> dict:
    """Adds a line to a sketch. x/y/z are world coordinates; z1 and z2
    must both equal the sketch's plane_z (see create_sketch)."""
    return _net(
        "POST", "/api/feature/sketch/line",
        sketch_handle=sketch_handle, x1=x1, y1=y1, z1=z1, x2=x2, y2=y2, z2=z2,
    )


@mcp.tool()
def add_sketch_circle(sketch_handle: str, cx: float, cy: float, cz: float,
                       radius: float) -> dict:
    """Adds a circle to a sketch. cz must equal the sketch's plane_z. Two
    concentric circles in one sketch (outer + inner radius) profile into a
    true annulus once create_profile is called - validated: extruding one
    gives exactly pi*(r_out^2-r_in^2)*height."""
    return _net(
        "POST", "/api/feature/sketch/circle",
        sketch_handle=sketch_handle, cx=cx, cy=cy, cz=cz, radius=radius,
    )


@mcp.tool()
def create_profile(sketch_handle: str) -> dict:
    """Converts a sketch's curves into a closed profile ready to extrude.
    Call once after all add_sketch_line/add_sketch_circle calls for that
    sketch are done."""
    return _net("POST", "/api/feature/sketch/profile", sketch_handle=sketch_handle)


@mcp.tool()
def create_extrude_feature(profile_handle: str, height: float,
                            solid_handle: str = "", taper_angle: float = 0.0,
                            direction: bool = True) -> dict:
    """Extrudes a profile into a live parametric feature on solid_handle
    (""=the bootstrapped pending solid from create_sketch). Validated
    exact: a 10x10 square extruded 10 gives Volume=1000.0, and editing the
    feature's Distance parameter afterward (edit_feature_parameter)
    recomputes it correctly. To build a body of revolution, stack several
    of these as concentric-circle "washers" at increasing plane_z instead
    of using create_revolve_feature (see module docstring above)."""
    return _net(
        "POST", "/api/feature/extrude",
        solid_handle=solid_handle, profile_handle=profile_handle,
        height=height, taper_angle=taper_angle, direction=direction,
    )


@mcp.tool()
def edit_feature_parameter(feature_handle: str, param_name: str, value: float) -> dict:
    """Live-edits a numeric parameter on an existing parametric feature
    (e.g. param_name="Distance" on an extrude feature) and recomputes the
    solid. Validated exact: Distance 10->25 on a 10x10 extrude recomputes
    Volume from 1000 to 2500 with the correct new centroid."""
    return _net(
        "POST", "/api/feature/edit",
        feature_handle=feature_handle, param_name=param_name, value=value,
    )


@mcp.tool()
def get_feature_list(solid_handle: str) -> dict:
    """Lists the parametric feature tree (sketches, extrude features, ...)
    on a Mc3dSolid, with each feature's editable parameters."""
    return _net("GET", "/api/feature/list?solid_handle=%s" % solid_handle)


@mcp.tool()
def get_solid_properties(handle: str) -> dict:
    """Returns Volume, Area and centroid for a solid (parametric or plain
    ACIS) by handle - the fastest way to sanity-check a build against a
    hand-computed expectation."""
    return _net("GET", "/api/solid/%s/props" % handle)


if __name__ == "__main__":
    mcp.run()
