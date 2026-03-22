#!/usr/bin/env python3
"""
Tool Maker — Dynamically create new Hermes tools at runtime.

Supports two creation modes:
1. API Wrapper:  Give it a URL, method, and params → generates an httpx tool
2. Custom Code:  Provide raw Python handler code → wraps and registers it

Created tools are:
- Saved to tools/custom/<name>.py for persistence across restarts
- Registered with the registry immediately (hot-loaded)
- Added to the "custom" toolset
- Tracked in tools/custom/manifest.json for auto-reload on startup
"""

import json
import logging
import os
import re
import textwrap
from pathlib import Path

from tools.registry import registry

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CUSTOM_DIR = _PROJECT_ROOT / "tools" / "custom"
_MANIFEST_PATH = _CUSTOM_DIR / "manifest.json"


def _ensure_custom_dir():
    _CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    init_path = _CUSTOM_DIR / "__init__.py"
    if not init_path.exists():
        init_path.write_text("", encoding="utf-8")


def _load_manifest() -> dict:
    if _MANIFEST_PATH.exists():
        return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    return {"tools": {}}


def _save_manifest(manifest: dict):
    _ensure_custom_dir()
    _MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _safe_name(name: str) -> str:
    """Sanitize a tool name to a valid Python identifier."""
    name = re.sub(r"[^a-z0-9_]", "_", name.lower().strip())
    name = re.sub(r"_+", "_", name).strip("_")
    if not name or name[0].isdigit():
        name = "tool_" + name
    return name


# ---------------------------------------------------------------------------
# API Wrapper Generator
# ---------------------------------------------------------------------------
def _generate_api_wrapper(name: str, url: str, method: str,
                          headers: dict, body_params: list,
                          query_params: list, description: str,
                          timeout: int) -> str:
    """Generate Python source for an API wrapper tool."""

    properties = {}
    required = []
    for p in body_params + query_params:
        pname = p["name"]
        ptype = p.get("type", "string")
        pdesc = p.get("description", "")
        preq = p.get("required", False)
        properties[pname] = {"type": ptype, "description": pdesc}
        if preq:
            required.append(pname)

    body_param_names = [p["name"] for p in body_params]
    query_param_names = [p["name"] for p in query_params]
    headers_repr = repr(headers) if headers else "{}"
    props_json = json.dumps(properties, indent=4)
    req_json = json.dumps(required)

    lines = [
        f'#!/usr/bin/env python3',
        f'"""Auto-generated API wrapper tool: {name}"""',
        f'import json',
        f'import logging',
        f'from tools.registry import registry',
        f'',
        f'logger = logging.getLogger(__name__)',
        f'',
        f'',
        f'def {name}_handler(args, **kwargs):',
        f'    try:',
        f'        import httpx',
        f'        _headers = {headers_repr}',
        f'        _url = {repr(url)}',
        f'        _method = {repr(method.upper())}',
        f'        _timeout = {timeout}',
        f'        params = {{}}',
        f'        for k in {repr(query_param_names)}:',
        f'            v = args.get(k)',
        f'            if v is not None:',
        f'                params[k] = v',
        f'        body = {{}}',
        f'        for k in {repr(body_param_names)}:',
        f'            v = args.get(k)',
        f'            if v is not None:',
        f'                body[k] = v',
        f'        if _method == "GET":',
        f'            r = httpx.get(_url, params=params, headers=_headers, timeout=_timeout)',
        f'        elif _method == "POST":',
        f'            r = httpx.post(_url, json=body, params=params, headers=_headers, timeout=_timeout)',
        f'        elif _method == "PUT":',
        f'            r = httpx.put(_url, json=body, params=params, headers=_headers, timeout=_timeout)',
        f'        elif _method == "DELETE":',
        f'            r = httpx.delete(_url, params=params, headers=_headers, timeout=_timeout)',
        f'        elif _method == "PATCH":',
        f'            r = httpx.patch(_url, json=body, params=params, headers=_headers, timeout=_timeout)',
        f'        else:',
        f'            return json.dumps({{"error": "Unsupported method"}})',
        f'        if r.status_code >= 400:',
        f'            return json.dumps({{"error": f"HTTP {{r.status_code}}: {{r.text[:500]}}"}})',
        f'        try:',
        f'            return json.dumps(r.json(), ensure_ascii=False)',
        f'        except Exception:',
        f'            return json.dumps({{"response": r.text[:2000], "status": r.status_code}})',
        f'    except Exception as e:',
        f'        return json.dumps({{"error": f"{{type(e).__name__}}: {{e}}"}})',
        f'',
        f'',
        f'SCHEMA = {{',
        f'    "name": {repr(name)},',
        f'    "description": {repr(description)},',
        f'    "parameters": {{',
        f'        "type": "object",',
        f'        "properties": {props_json},',
        f'        "required": {req_json},',
        f'    }},',
        f'}}',
        f'',
        f'registry.register(',
        f'    name={repr(name)},',
        f'    toolset="custom",',
        f'    schema=SCHEMA,',
        f'    handler={name}_handler,',
        f')',
        f'',
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Custom Code Generator
# ---------------------------------------------------------------------------
def _generate_custom_tool(name: str, description: str,
                          parameters: dict, code: str) -> str:
    """Generate Python source for a custom-code tool."""
    params_json = json.dumps(parameters, indent=4)

    lines = [
        f'#!/usr/bin/env python3',
        f'"""Custom tool: {name}"""',
        f'import json',
        f'import logging',
        f'from tools.registry import registry',
        f'',
        f'logger = logging.getLogger(__name__)',
        f'',
        f'',
        f'def {name}_handler(args, **kwargs):',
        f'    try:',
    ]

    # Indent user code by 8 spaces (inside try block)
    for line in code.splitlines():
        lines.append("        " + line)

    lines.extend([
        f'    except Exception as e:',
        f'        return json.dumps({{"error": f"{{type(e).__name__}}: {{e}}"}})',
        f'',
        f'',
        f'SCHEMA = {{',
        f'    "name": {repr(name)},',
        f'    "description": {repr(description)},',
        f'    "parameters": {params_json},',
        f'}}',
        f'',
        f'registry.register(',
        f'    name={repr(name)},',
        f'    toolset="custom",',
        f'    schema=SCHEMA,',
        f'    handler={name}_handler,',
        f')',
        f'',
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Hot-load a generated tool
# ---------------------------------------------------------------------------
def _hot_load(name: str, file_path: Path):
    """Import and register a tool file at runtime."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        f"tools.custom.{name}", str(file_path),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    logger.info("Hot-loaded custom tool: %s", name)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def create_tool_handler(args: dict, **kwargs) -> str:
    """Create a new tool dynamically."""
    name = _safe_name(args.get("name", ""))
    if not name:
        return json.dumps({"error": "name is required"})

    if name in registry._tools:
        return json.dumps({"error": f"Tool '{name}' already exists. Use a different name or delete it first."})

    description = args.get("description", f"Custom tool: {name}")
    mode = args.get("mode", "api").lower()

    _ensure_custom_dir()

    if mode == "api":
        url = args.get("url", "").strip()
        if not url:
            return json.dumps({"error": "url is required for API wrapper tools"})

        method = args.get("method", "GET").upper()
        headers = args.get("headers") or {}
        body_params = args.get("body_params") or []
        query_params = args.get("query_params") or []
        timeout = int(args.get("timeout", 30))

        source = _generate_api_wrapper(
            name, url, method, headers,
            body_params, query_params,
            description, timeout,
        )

    elif mode == "code":
        code = args.get("code", "").strip()
        if not code:
            return json.dumps({"error": "code is required for custom code tools"})

        parameters = args.get("parameters") or {
            "type": "object", "properties": {},
        }

        source = _generate_custom_tool(name, description, parameters, code)

    else:
        return json.dumps({"error": f"Unknown mode '{mode}'. Use 'api' or 'code'."})

    # Write the tool file
    tool_path = _CUSTOM_DIR / f"{name}.py"
    tool_path.write_text(source, encoding="utf-8")

    # Hot-load it
    try:
        _hot_load(name, tool_path)
    except Exception as e:
        # Clean up on failure
        tool_path.unlink(missing_ok=True)
        return json.dumps({"error": f"Tool failed to load: {e}"})

    # Update manifest
    manifest = _load_manifest()
    manifest["tools"][name] = {
        "mode": mode,
        "file": f"{name}.py",
        "description": description,
    }
    if mode == "api":
        manifest["tools"][name]["url"] = args.get("url", "")
        manifest["tools"][name]["method"] = args.get("method", "GET")
    _save_manifest(manifest)

    return json.dumps({
        "created": True,
        "name": name,
        "mode": mode,
        "file": str(tool_path),
        "description": description,
    }, ensure_ascii=False)


def delete_tool_handler(args: dict, **kwargs) -> str:
    """Delete a custom tool."""
    name = _safe_name(args.get("name", ""))
    if not name:
        return json.dumps({"error": "name is required"})

    manifest = _load_manifest()
    if name not in manifest.get("tools", {}):
        return json.dumps({"error": f"Custom tool '{name}' not found"})

    # Remove file
    tool_path = _CUSTOM_DIR / f"{name}.py"
    tool_path.unlink(missing_ok=True)

    # Remove from registry
    registry._tools.pop(name, None)

    # Remove from manifest
    del manifest["tools"][name]
    _save_manifest(manifest)

    return json.dumps({"deleted": True, "name": name})


def list_custom_tools_handler(args: dict, **kwargs) -> str:
    """List all custom-created tools."""
    manifest = _load_manifest()
    tools = []
    for name, info in manifest.get("tools", {}).items():
        entry = registry._tools.get(name)
        tools.append({
            "name": name,
            "mode": info.get("mode"),
            "description": info.get("description", ""),
            "registered": entry is not None,
            "file": info.get("file"),
        })
    return json.dumps({"tools": tools, "count": len(tools)}, ensure_ascii=False)


def load_custom_tools():
    """Load all custom tools from manifest on startup."""
    manifest = _load_manifest()
    for name, info in manifest.get("tools", {}).items():
        tool_path = _CUSTOM_DIR / info.get("file", f"{name}.py")
        if tool_path.exists() and name not in registry._tools:
            try:
                _hot_load(name, tool_path)
            except Exception as e:
                logger.warning("Failed to load custom tool %s: %s", name, e)


# Auto-load on import
load_custom_tools()


# ===========================================================================
# Schemas & Registration
# ===========================================================================

CREATE_TOOL_SCHEMA = {
    "name": "create_tool",
    "description": (
        "Create a new tool dynamically. Two modes:\n"
        "- 'api': Wrap any HTTP API endpoint as a tool. Provide url, method, params.\n"
        "- 'code': Write custom Python handler code. Code must set a 'result' variable "
        "or return json.dumps(...).\n"
        "The tool is immediately available after creation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Tool name (lowercase, underscores). Must be unique.",
            },
            "description": {
                "type": "string",
                "description": "What the tool does (shown to the LLM).",
            },
            "mode": {
                "type": "string",
                "enum": ["api", "code"],
                "description": "Creation mode: 'api' for HTTP wrapper, 'code' for custom Python.",
            },
            "url": {
                "type": "string",
                "description": "(api mode) The HTTP endpoint URL to wrap.",
            },
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                "description": "(api mode) HTTP method (default: GET).",
            },
            "headers": {
                "type": "object",
                "description": "(api mode) HTTP headers to include.",
            },
            "body_params": {
                "type": "array",
                "description": (
                    "(api mode) Body parameters. Each: "
                    "{name, type, description, required}."
                ),
                "items": {"type": "object"},
            },
            "query_params": {
                "type": "array",
                "description": (
                    "(api mode) Query string parameters. Each: "
                    "{name, type, description, required}."
                ),
                "items": {"type": "object"},
            },
            "timeout": {
                "type": "integer",
                "description": "(api mode) Request timeout in seconds (default 30).",
            },
            "code": {
                "type": "string",
                "description": (
                    "(code mode) Python handler code. Has access to 'args' dict. "
                    "Must return json.dumps(result_dict)."
                ),
            },
            "parameters": {
                "type": "object",
                "description": "(code mode) JSON Schema for the tool's parameters.",
            },
        },
        "required": ["name", "description", "mode"],
    },
}

DELETE_TOOL_SCHEMA = {
    "name": "delete_tool",
    "description": "Delete a custom-created tool by name.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the custom tool to delete.",
            },
        },
        "required": ["name"],
    },
}

LIST_CUSTOM_TOOLS_SCHEMA = {
    "name": "list_custom_tools",
    "description": "List all dynamically created custom tools.",
    "parameters": {"type": "object", "properties": {}},
}

for name, schema, handler in [
    ("create_tool", CREATE_TOOL_SCHEMA, create_tool_handler),
    ("delete_tool", DELETE_TOOL_SCHEMA, delete_tool_handler),
    ("list_custom_tools", LIST_CUSTOM_TOOLS_SCHEMA, list_custom_tools_handler),
]:
    registry.register(
        name=name, toolset="tool_maker", schema=schema, handler=handler,
    )
