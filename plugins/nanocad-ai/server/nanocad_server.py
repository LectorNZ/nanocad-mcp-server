"""
Local MCP server bridging Claude Code to a running nanoCAD 26 instance via
its COM (ActiveX) automation interface, which closely mirrors AutoCAD's.

Requires: nanoCAD x64 26.0 already running with a document open.
"""
import os
import sys
import time

import pythoncom
import win32com.client
from mcp.server.mcpserver import MCPServer

PROGID_CANDIDATES = [
    "nanoCADx64.Application.26.0",
    "nanoCADx64.Application",
]

mcp = MCPServer("nanocad-application-server")


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
    """
    doc = _get_doc()
    before = doc.ModelSpace.Count
    _send(doc, command)
    after = doc.ModelSpace.Count
    return {"status": "success", "modelSpaceCountBefore": before, "modelSpaceCountAfter": after}


@mcp.tool()
def run_lisp(lispFilePath: str) -> dict:
    """Runs an AutoLISP (.lsp) file located at the given path inside nanoCAD."""
    if not os.path.isfile(lispFilePath):
        raise FileNotFoundError(lispFilePath)
    doc = _get_doc()
    safe_path = lispFilePath.replace("\\", "/")
    before = doc.ModelSpace.Count
    _send(doc, '(load "%s") ' % safe_path)
    after = doc.ModelSpace.Count
    return {"status": "success", "modelSpaceCountBefore": before, "modelSpaceCountAfter": after}


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


if __name__ == "__main__":
    mcp.run()
