#!/usr/bin/env python3
"""
Serper Search Tool — Google-quality search via Serper.dev API.

Provides structured search results including:
- Organic results (title, url, snippet)
- Knowledge graph (if available)
- Answer box (direct answers)

Requires SERPER_API_KEY environment variable.
Free tier: 2,500 searches/month at https://serper.dev
"""

import json
import logging
import os

from tools.registry import registry

logger = logging.getLogger(__name__)

_SERPER_URL = "https://google.serper.dev/search"


def _check_serper() -> bool:
    """Check if Serper API key is configured."""
    return bool(os.environ.get("SERPER_API_KEY"))


def serper_search_handler(args: dict, **kwargs) -> str:
    """Search Google via Serper.dev API."""
    query = args.get("query", "").strip()
    if not query:
        return json.dumps({"error": "query is required"})

    api_key = os.environ.get("SERPER_API_KEY", "")
    if not api_key:
        return json.dumps({"error": "SERPER_API_KEY not set. Get one free at https://serper.dev"})

    num_results = min(int(args.get("num_results", 5)), 20)
    search_type = args.get("type", "search")  # search, news, images

    try:
        import httpx

        endpoint = f"https://google.serper.dev/{search_type}"
        r = httpx.post(
            endpoint,
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            },
            json={"q": query, "num": num_results},
            timeout=15.0,
        )

        if r.status_code == 403:
            return json.dumps({"error": "Invalid Serper API key (403)"})
        if r.status_code == 429:
            return json.dumps({"error": "Rate limited — try again shortly"})
        if r.status_code != 200:
            return json.dumps({"error": f"Serper returned {r.status_code}: {r.text[:300]}"})

        data = r.json()

        # Build structured results
        result = {
            "query": query,
            "engine": "google (via serper)",
        }

        # Organic results
        organic = data.get("organic", [])
        result["results"] = [
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "position": item.get("position"),
            }
            for item in organic[:num_results]
        ]
        result["count"] = len(result["results"])

        # Knowledge graph
        kg = data.get("knowledgeGraph")
        if kg:
            result["knowledge_graph"] = {
                "title": kg.get("title"),
                "type": kg.get("type"),
                "description": kg.get("description"),
                "url": kg.get("descriptionLink"),
            }

        # Answer box (direct answer from Google)
        ab = data.get("answerBox")
        if ab:
            result["answer"] = ab.get("answer") or ab.get("snippet") or ab.get("title")

        # People also ask
        paa = data.get("peopleAlsoAsk")
        if paa:
            result["related_questions"] = [
                q.get("question") for q in paa[:3] if q.get("question")
            ]

        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"Search failed: {e}"})


# ===========================================================================
# Schema & Registration
# ===========================================================================

SERPER_SEARCH_SCHEMA = {
    "name": "serper_search",
    "description": (
        "Search Google via Serper.dev API. Returns structured results with "
        "titles, URLs, snippets, knowledge graph, and direct answers. "
        "Higher quality than DuckDuckGo for factual queries. "
        "Supports search types: search, news, images."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query.",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results (default 5, max 20).",
            },
            "type": {
                "type": "string",
                "enum": ["search", "news", "images"],
                "description": "Search type (default: search).",
            },
        },
        "required": ["query"],
    },
}

registry.register(
    name="serper_search",
    toolset="serper",
    schema=SERPER_SEARCH_SCHEMA,
    handler=serper_search_handler,
    check_fn=_check_serper,
    requires_env=["SERPER_API_KEY"],
)
