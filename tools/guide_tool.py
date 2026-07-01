#!/usr/bin/env python3
"""
Guide Tool - Search the built-in Hermes user guide.

Loads docs/hermes-guide.md into memory and provides keyword search
across sections delimited by ## headers.
"""

import json
import os
import re
import logging
from typing import Dict, List

from tools.registry import registry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load and parse the guide on import
# ---------------------------------------------------------------------------

_GUIDE_SECTIONS: List[Dict[str, str]] = []

def _load_guide():
    """Load the guide markdown and split into sections by ## headers."""
    global _GUIDE_SECTIONS
    guide_path = os.path.join(os.path.dirname(__file__), "..", "docs", "hermes-guide.md")
    guide_path = os.path.normpath(guide_path)

    try:
        with open(guide_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        logger.warning("Guide not found at %s", guide_path)
        return

    # Split by ## headers (keep the header with its section)
    parts = re.split(r"(?=^## )", content, flags=re.MULTILINE)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Extract the heading (first line starting with ##)
        lines = part.split("\n", 1)
        heading = lines[0].lstrip("#").strip()
        body = lines[1].strip() if len(lines) > 1 else ""

        _GUIDE_SECTIONS.append({
            "heading": heading,
            "body": body,
            "full": part,
        })

    logger.debug("Loaded %d guide sections", len(_GUIDE_SECTIONS))


_load_guide()

# ---------------------------------------------------------------------------
# Search logic
# ---------------------------------------------------------------------------

def _score_section(section: Dict[str, str], keywords: List[str]) -> float:
    """Score a section based on keyword matches. Higher is better."""
    heading_lower = section["heading"].lower()
    body_lower = section["body"].lower()
    score = 0.0

    for kw in keywords:
        kw_lower = kw.lower()
        # Heading matches are worth more
        if kw_lower in heading_lower:
            score += 10.0
        # Count body occurrences
        count = body_lower.count(kw_lower)
        if count > 0:
            score += min(count, 5)  # cap per-keyword body score

    return score


# ---------------------------------------------------------------------------
# Tool schema and handler
# ---------------------------------------------------------------------------

SEARCH_GUIDE_SCHEMA = {
    "name": "search_guide",
    "description": (
        "Search the built-in Hermes user guide for help, how-to information, "
        "tool descriptions, extension setup instructions, and troubleshooting. "
        "Returns the most relevant sections matching the query."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query - keywords or a question about Hermes features, tools, extensions, or setup",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of sections to return (default 3)",
                "default": 3,
            },
        },
        "required": ["query"],
    },
}


def search_guide_handler(args: dict, **kwargs) -> str:
    """Handle search_guide tool calls."""
    query = args.get("query", "")
    max_results = args.get("max_results", 3)

    if not query.strip():
        return json.dumps({"error": "Query cannot be empty"})

    if not _GUIDE_SECTIONS:
        return json.dumps({"error": "Guide not loaded. docs/hermes-guide.md may be missing."})

    # Tokenize query into keywords (strip punctuation, split on whitespace)
    keywords = re.findall(r"[a-zA-Z0-9_\-]+", query)
    if not keywords:
        return json.dumps({"error": "No searchable keywords in query"})

    # Score each section
    scored = []
    for section in _GUIDE_SECTIONS:
        score = _score_section(section, keywords)
        if score > 0:
            scored.append((score, section))

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    # Take top results
    results = []
    for score, section in scored[:max_results]:
        # Truncate very long sections for readability
        body = section["body"]
        if len(body) > 2000:
            body = body[:2000] + "\n\n... (section truncated)"

        results.append({
            "heading": section["heading"],
            "content": body,
            "relevance": round(score, 1),
        })

    if not results:
        return json.dumps({
            "message": f"No sections matched the query '{query}'. Try different keywords.",
            "available_sections": [s["heading"] for s in _GUIDE_SECTIONS],
        })

    return json.dumps({
        "query": query,
        "results": results,
        "total_sections": len(_GUIDE_SECTIONS),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Register with the tool registry
# ---------------------------------------------------------------------------

registry.register(
    name="search_guide",
    toolset="guide",
    schema=SEARCH_GUIDE_SCHEMA,
    handler=search_guide_handler,
)
