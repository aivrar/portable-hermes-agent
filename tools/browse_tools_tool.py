#!/usr/bin/env python3
"""
Browse Tools — Categorized tool discovery and on-demand activation.

Gives the agent a lean view of all available tool categories, then lets it
drill into a category and activate those tools for the current session.
"""

import json
import logging
import os

from tools.registry import registry

logger = logging.getLogger(__name__)

# Human-friendly category labels and descriptions.
# Keys are toolset IDs from the registry. Unlisted toolsets get auto-labeled.
_CATEGORY_META = {
    # These keys must match the toolset IDs in the registry
    "web": ("Web & Search", "Search the web and extract page content"),
    "file": ("Files", "Read, write, edit, and search files"),
    "terminal": ("Terminal", "Run commands and manage processes"),
    "browser": ("Browser Automation", "Navigate, click, type, screenshot web pages"),
    "vision": ("Vision", "Analyze and describe images"),
    "image_gen": ("Image Generation", "Create images from text descriptions (needs FAL_KEY)"),
    "tts": ("Text-to-Speech", "Convert text to spoken audio"),
    "skills": ("Skills", "Browse and load reusable skill guides"),
    "todo": ("Planning", "Task lists and project planning"),
    "memory": ("Memory", "Persistent notes across conversations"),
    "clarify": ("Clarify", "Ask the user multiple-choice questions"),
    "session_search": ("Session History", "Search past conversations"),
    "delegation": ("Delegation", "Spawn sub-agents for parallel tasks"),
    "code_execution": ("Code Execution", "Run Python scripts with tool access"),
    "lm_studio": ("LM Studio", "Load and manage local AI models (needs LM Studio running)"),
    "music": ("Music Generation", "Generate music with local AI (needs music server)"),
    "extension_tts": ("TTS Server", "Advanced text-to-speech with 10+ voice models (needs TTS server)"),
    "comfyui": ("ComfyUI", "AI image generation with Stable Diffusion/Flux (needs ComfyUI)"),
    "model_switcher": ("Model Switcher", "Change which AI model powers Hermes"),
    "gpu": ("GPU Info", "Check NVIDIA GPU status, memory, temperature"),
    "serper": ("Google Search", "Google-quality search results (needs SERPER_API_KEY)"),
    "hermes_update": ("Updates", "Check for Hermes updates"),
    "tool_maker": ("Tool Maker", "Create new tools at runtime from APIs or Python code"),
    "workflows": ("Workflows", "Multi-step automation pipelines with scheduling"),
    "cronjob": ("Cron Jobs", "Schedule recurring tasks"),
    "guide": ("Guide", "Search the built-in user manual"),
    "run_python": ("Python Runner", "Execute Python code directly"),
    "moa": ("Mixture of Agents", "Multi-model reasoning for complex questions"),
    "homeassistant": ("Home Assistant", "Smart home control (needs HASS_TOKEN)"),
    "honcho": ("Honcho Memory", "Cross-session user modeling (needs HONCHO_API_KEY)"),
    "messaging": ("Messaging", "Send messages across platforms"),
    "core": ("Core", "Tool discovery and agent utilities"),
    "rl": ("RL Training", "Reinforcement learning tools (needs TINKER_API_KEY)"),
}


def _build_categories():
    """Build category list from the registry."""
    categories = {}
    for name, entry in registry._tools.items():
        ts = entry.toolset
        if ts not in categories:
            meta = _CATEGORY_META.get(ts)
            if meta:
                label, desc = meta
            else:
                # Auto-label from toolset ID
                label = ts.replace("_", " ").replace("-", " ").title()
                desc = ""
            categories[ts] = {
                "label": label,
                "description": desc,
                "tools": [],
            }
        categories[ts]["tools"].append({
            "name": name,
            "description": entry.schema.get("description", "")[:120],
        })
    return categories


def browse_tools_handler(args: dict, **kwargs) -> str:
    """Browse available tool categories or drill into a specific one."""
    category = (args.get("category") or "").strip().lower()
    activate = args.get("activate", False)

    categories = _build_categories()

    # No category = list all categories
    if not category:
        lines = []
        for ts_id, cat in sorted(categories.items(), key=lambda x: x[1]["label"]):
            count = len(cat["tools"])
            avail = registry.is_toolset_available(ts_id)
            status = "" if avail else " [not running]"
            desc = f" — {cat['description']}" if cat["description"] else ""
            lines.append({
                "category": ts_id,
                "label": cat["label"],
                "tools": count,
                "available": avail,
                "description": cat["description"],
            })
        return json.dumps({
            "total_categories": len(lines),
            "total_tools": sum(c["tools"] for c in lines),
            "categories": lines,
            "hint": "Call browse_tools(category='<category_id>') to see tools in a category. "
                    "Add activate=true to load them into this session.",
        }, indent=2)

    # Find the matching category (fuzzy match on id or label)
    matched_ts = None
    for ts_id, cat in categories.items():
        if (category == ts_id.lower()
            or category == cat["label"].lower()
            or category in ts_id.lower()
            or category in cat["label"].lower()):
            matched_ts = ts_id
            break

    if not matched_ts:
        return json.dumps({
            "error": f"No category matching '{category}'",
            "available": [f"{c['label']} ({ts})" for ts, c in sorted(categories.items(), key=lambda x: x[1]["label"])],
        })

    cat = categories[matched_ts]
    avail = registry.is_toolset_available(matched_ts)

    result = {
        "category": matched_ts,
        "label": cat["label"],
        "description": cat["description"],
        "available": avail,
        "tools": cat["tools"],
    }

    # Activate = add these tools to the current agent session
    if activate:
        agent = kwargs.get("agent")
        if agent and hasattr(agent, "tools"):
            # Get the tool schemas for this toolset
            tool_names = {t["name"] for t in cat["tools"]}
            new_defs = registry.get_definitions(tool_names, quiet=True)

            # Find which tools are already loaded
            existing_names = set()
            for t in agent.tools:
                fn = t.get("function", {})
                existing_names.add(fn.get("name", ""))

            added = []
            for td in new_defs:
                fn_name = td.get("function", {}).get("name", "")
                if fn_name not in existing_names:
                    agent.tools.append(td)
                    added.append(fn_name)

            if added:
                result["activated"] = added
                result["message"] = f"Loaded {len(added)} tools into this session. You can now call them directly."
            else:
                result["message"] = "All tools in this category are already loaded."
        else:
            result["message"] = "Could not activate — no agent context available."
            if not avail:
                result["message"] += f" Also, {cat['label']} requires its service to be running."

    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Schema & Registration
# ---------------------------------------------------------------------------

BROWSE_TOOLS_SCHEMA = {
    "name": "browse_tools",
    "description": (
        "Browse all available tool categories and activate tools on demand. "
        "Call with no arguments to see all categories. "
        "Call with category to see tools in that category. "
        "Call with category + activate=true to load those tools into the current session."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Category ID or name to browse (e.g. 'lm_studio', 'music', 'browser'). Omit to list all.",
            },
            "activate": {
                "type": "boolean",
                "description": "If true, load the tools from this category into the current session so you can call them.",
            },
        },
    },
}

registry.register(
    name="browse_tools",
    toolset="core",
    schema=BROWSE_TOOLS_SCHEMA,
    handler=browse_tools_handler,
)
