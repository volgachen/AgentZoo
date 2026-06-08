import logging
from datetime import datetime
from urllib.parse import urlparse

import httpx

from app.adapters.tools.base import BaseTool
from app.adapters.tools.registry import register_tool

logger = logging.getLogger("agentzoo.tool.web_search")

_MAX_RESULTS = 20
_CURRENT_MONTH_YEAR = datetime.now().strftime("%B %Y")


@register_tool
class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "- Allows the agent to search the web and use the results to inform responses\n"
        "- Provides up-to-date information for current events and recent data\n"
        "- Returns search result information including links\n"
        "- Use this tool for accessing information beyond the agent's knowledge cutoff\n"
        "- Searches are performed within a single API call\n\n"
        "CRITICAL REQUIREMENT - You MUST follow this:\n"
        "  - After answering the user's question, you MUST include a \"Sources:\" "
        "section at the end of your response\n"
        "  - In the Sources section, list all relevant URLs from the search results "
        "as markdown hyperlinks: [Title](URL)\n"
        "  - This is MANDATORY - never skip including sources in your response\n"
        "  - Example format:\n\n"
        "    [Your answer here]\n\n"
        "    Sources:\n"
        "    - [Source Title 1](https://example.com/1)\n"
        "    - [Source Title 2](https://example.com/2)\n\n"
        "Usage notes:\n"
        "  - Domain filtering is supported to include or block specific websites\n"
        "  - The current month is "
        + _CURRENT_MONTH_YEAR
        + ". You MUST use this year when searching "
        "for recent information, documentation, or current events.\n"
        "  - Example: If the user asks for \"latest React docs\", search for "
        "\"React documentation\" with the current year, NOT last year"
    )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to use",
                },
                "allowed_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Only include search results from these domains",
                },
                "blocked_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Never include search results from these domains",
                },
                "max_results": {
                    "type": "integer",
                    "description": f"Maximum results (default: 10, max: {_MAX_RESULTS})",
                    "default": 10,
                },
            },
            "required": ["query"],
        }

    async def execute(
        self,
        query: str,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
        max_results: int = 10,
    ) -> str:
        max_results = min(max_results, _MAX_RESULTS)

        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": query,
                    "format": "json",
                    "no_html": "1",
                    "skip_disambig": "1",
                },
                headers={"User-Agent": "AgentZoo-WebSearch/1.0"},
            )
            data = resp.json()

        results: list[dict] = []

        for item in data.get("Results", []) or []:
            if isinstance(item, dict) and item.get("FirstURL") and item.get("Text"):
                results.append({"title": item["Text"], "url": item["FirstURL"]})

        for item in data.get("RelatedTopics", []) or []:
            if isinstance(item, dict) and item.get("FirstURL") and item.get("Text"):
                results.append({"title": item["Text"], "url": item["FirstURL"]})

        # Deduplicate by URL, preserving order
        seen: set[str] = set()
        unique: list[dict] = []
        for r in results:
            if r["url"] not in seen:
                seen.add(r["url"])
                unique.append(r)

        # Domain filtering
        if allowed_domains:
            allowed_set = {d.lower().strip() for d in allowed_domains}
            unique = [r for r in unique if _extract_domain(r["url"]) in allowed_set]

        if blocked_domains:
            blocked_set = {d.lower().strip() for d in blocked_domains}
            unique = [r for r in unique if _extract_domain(r["url"]) not in blocked_set]

        unique = unique[:max_results]

        # Build output
        header = f'Web search results for query: "{query}"'

        if not unique:
            abstract = data.get("AbstractText", "")
            if abstract:
                return (
                    f"{header}\n\n{abstract}\n\n"
                    "No links found.\n\n"
                    "REMINDER: You MUST include the sources above in your response "
                    "to the user using markdown hyperlinks."
                )
            return (
                f"No results found for query: \"{query}\".\n\n"
                "REMINDER: You MUST include the sources above in your response "
                "to the user using markdown hyperlinks."
            )

        lines = [header, ""]
        for i, r in enumerate(unique, 1):
            lines.append(f"{i}. [{r['title']}]({r['url']})")

        lines.append("")
        lines.append(
            "REMINDER: You MUST include the sources above in your response "
            "to the user using markdown hyperlinks."
        )

        return "\n".join(lines)


def _extract_domain(url: str) -> str:
    try:
        hostname = urlparse(url).hostname or ""
        return hostname.removeprefix("www.").lower()
    except Exception:
        return ""
