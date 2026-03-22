"""Central registry for all hermes-agent tools.

Each tool file calls ``registry.register()`` at module level to declare its
schema, handler, toolset membership, and availability check.  ``model_tools.py``
queries the registry instead of maintaining its own parallel data structures.

Import chain (circular-import safe):
    tools/registry.py  (no imports from model_tools or tool files)
           ^
    tools/*.py  (import from tools.registry at module level)
           ^
    model_tools.py  (imports tools.registry + all tool modules)
           ^
    run_agent.py, cli.py, batch_runner.py, etc.
"""

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class ToolEntry:
    """Metadata for a single registered tool."""

    __slots__ = (
        "name", "toolset", "schema", "handler", "check_fn",
        "requires_env", "is_async", "description",
    )

    def __init__(self, name, toolset, schema, handler, check_fn,
                 requires_env, is_async, description):
        self.name = name
        self.toolset = toolset
        self.schema = schema
        self.handler = handler
        self.check_fn = check_fn
        self.requires_env = requires_env
        self.is_async = is_async
        self.description = description


class ToolRegistry:
    """Singleton registry that collects tool schemas + handlers from tool files."""

    def __init__(self):
        self._tools: Dict[str, ToolEntry] = {}
        self._toolset_checks: Dict[str, Callable] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        toolset: str,
        schema: dict,
        handler: Callable,
        check_fn: Callable = None,
        requires_env: list = None,
        is_async: bool = False,
        description: str = "",
    ):
        """Register a tool.  Called at module-import time by each tool file."""
        self._tools[name] = ToolEntry(
            name=name,
            toolset=toolset,
            schema=schema,
            handler=handler,
            check_fn=check_fn,
            requires_env=requires_env or [],
            is_async=is_async,
            description=description or schema.get("description", ""),
        )
        if check_fn and toolset not in self._toolset_checks:
            self._toolset_checks[toolset] = check_fn

    # ------------------------------------------------------------------
    # Schema retrieval
    # ------------------------------------------------------------------

    def get_definitions(self, tool_names: Set[str], quiet: bool = False) -> List[dict]:
        """Return OpenAI-format tool schemas for the requested tool names.

        Only tools whose ``check_fn()`` returns True (or have no check_fn)
        are included.  Runs all check_fn calls in parallel to avoid slow
        sequential HTTP timeouts when services aren't running.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Separate tools with check_fn from those without
        no_check = []
        needs_check = []
        for name in sorted(tool_names):
            entry = self._tools.get(name)
            if not entry:
                continue
            if entry.check_fn:
                needs_check.append(entry)
            else:
                no_check.append(entry)

        # Run all check_fn calls in parallel (max 2s per check → ~2s total)
        check_results = {}  # name -> bool
        if needs_check:
            # Deduplicate check_fn by identity — many tools in a toolset
            # share the same check_fn so we only call it once.
            fn_to_names = {}
            for entry in needs_check:
                fn_id = id(entry.check_fn)
                if fn_id not in fn_to_names:
                    fn_to_names[fn_id] = (entry.check_fn, [])
                fn_to_names[fn_id][1].append(entry.name)

            def _run_check(fn, names):
                try:
                    ok = fn()
                except Exception:
                    ok = False
                return names, ok

            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(_run_check, fn, names)
                           for fn, names in fn_to_names.values()]
                for fut in as_completed(futures):
                    names, ok = fut.result()
                    for n in names:
                        check_results[n] = ok

        result = []
        for entry in no_check:
            result.append({"type": "function", "function": entry.schema})
        for entry in needs_check:
            if check_results.get(entry.name, False):
                result.append({"type": "function", "function": entry.schema})
            elif not quiet:
                logger.debug("Tool %s unavailable (check failed)", entry.name)
        return result

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch(self, name: str, args: dict, **kwargs) -> str:
        """Execute a tool handler by name.

        * Async handlers are bridged automatically via ``_run_async()``.
        * All exceptions are caught and returned as ``{"error": "..."}``
          for consistent error format.
        * Every call is logged with args preview and result preview.
        """
        import time as _time
        entry = self._tools.get(name)
        if not entry:
            logger.warning("TOOL_DISPATCH unknown tool=%s", name)
            return json.dumps({"error": f"Unknown tool: {name}"})

        # Log tool call with truncated args
        args_preview = json.dumps(args, ensure_ascii=False, default=str)
        if len(args_preview) > 500:
            args_preview = args_preview[:500] + "..."
        logger.info("TOOL_CALL tool=%s args=%s", name, args_preview)

        t0 = _time.monotonic()
        try:
            if entry.is_async:
                from model_tools import _run_async
                result = _run_async(entry.handler(args, **kwargs))
            else:
                result = entry.handler(args, **kwargs)

            elapsed = _time.monotonic() - t0
            # Log result preview
            result_preview = result if isinstance(result, str) else json.dumps(result, default=str)
            if len(result_preview) > 500:
                result_preview = result_preview[:500] + "..."
            has_error = '"error"' in result_preview[:200] if result_preview else False
            level = logging.WARNING if has_error else logging.INFO
            logger.log(level, "TOOL_RESULT tool=%s duration=%.2fs error=%s result=%s",
                       name, elapsed, has_error, result_preview)
            return result

        except Exception as e:
            elapsed = _time.monotonic() - t0
            logger.exception("TOOL_CRASH tool=%s duration=%.2fs error=%s", name, elapsed, e)
            return json.dumps({"error": f"Tool execution failed: {type(e).__name__}: {e}"})

    # ------------------------------------------------------------------
    # Query helpers  (replace redundant dicts in model_tools.py)
    # ------------------------------------------------------------------

    def get_all_tool_names(self) -> List[str]:
        """Return sorted list of all registered tool names."""
        return sorted(self._tools.keys())

    def get_toolset_for_tool(self, name: str) -> Optional[str]:
        """Return the toolset a tool belongs to, or None."""
        entry = self._tools.get(name)
        return entry.toolset if entry else None

    def get_tool_to_toolset_map(self) -> Dict[str, str]:
        """Return ``{tool_name: toolset_name}`` for every registered tool."""
        return {name: e.toolset for name, e in self._tools.items()}

    def is_toolset_available(self, toolset: str) -> bool:
        """Check if a toolset's requirements are met.

        Returns False (rather than crashing) when the check function raises
        an unexpected exception (e.g. network error, missing import, bad config).
        """
        check = self._toolset_checks.get(toolset)
        if not check:
            return True
        try:
            return bool(check())
        except Exception:
            logger.debug("Toolset %s check raised; marking unavailable", toolset)
            return False

    def check_toolset_requirements(self) -> Dict[str, bool]:
        """Return ``{toolset: available_bool}`` for every toolset."""
        toolsets = set(e.toolset for e in self._tools.values())
        return {ts: self.is_toolset_available(ts) for ts in sorted(toolsets)}

    def get_available_toolsets(self) -> Dict[str, dict]:
        """Return toolset metadata for UI display."""
        toolsets: Dict[str, dict] = {}
        for entry in self._tools.values():
            ts = entry.toolset
            if ts not in toolsets:
                toolsets[ts] = {
                    "available": self.is_toolset_available(ts),
                    "tools": [],
                    "description": "",
                    "requirements": [],
                }
            toolsets[ts]["tools"].append(entry.name)
            if entry.requires_env:
                for env in entry.requires_env:
                    if env not in toolsets[ts]["requirements"]:
                        toolsets[ts]["requirements"].append(env)
        return toolsets

    def get_toolset_requirements(self) -> Dict[str, dict]:
        """Build a TOOLSET_REQUIREMENTS-compatible dict for backward compat."""
        result: Dict[str, dict] = {}
        for entry in self._tools.values():
            ts = entry.toolset
            if ts not in result:
                result[ts] = {
                    "name": ts,
                    "env_vars": [],
                    "check_fn": self._toolset_checks.get(ts),
                    "setup_url": None,
                    "tools": [],
                }
            if entry.name not in result[ts]["tools"]:
                result[ts]["tools"].append(entry.name)
            for env in entry.requires_env:
                if env not in result[ts]["env_vars"]:
                    result[ts]["env_vars"].append(env)
        return result

    def check_tool_availability(self, quiet: bool = False):
        """Return (available_toolsets, unavailable_info) like the old function."""
        available = []
        unavailable = []
        seen = set()
        for entry in self._tools.values():
            ts = entry.toolset
            if ts in seen:
                continue
            seen.add(ts)
            if self.is_toolset_available(ts):
                available.append(ts)
            else:
                unavailable.append({
                    "name": ts,
                    "env_vars": entry.requires_env,
                    "tools": [e.name for e in self._tools.values() if e.toolset == ts],
                })
        return available, unavailable


# Module-level singleton
registry = ToolRegistry()
