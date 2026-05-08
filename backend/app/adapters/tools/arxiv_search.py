import httpx
import xml.etree.ElementTree as ET
from app.adapters.tools.base import BaseTool
from app.adapters.tools.registry import register_tool

_NS = {"atom": "http://www.w3.org/2005/Atom"}


@register_tool
class ArxivSearchTool(BaseTool):
    name = "arxiv_search"
    description = "Search arxiv.org for academic papers by keyword or topic."

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keywords"},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, max_results: int = 5) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://export.arxiv.org/api/query",
                params={"search_query": f"all:{query}", "max_results": max_results},
                timeout=15,
            )

        root = ET.fromstring(resp.text)
        entries = root.findall("atom:entry", _NS)
        if not entries:
            return "No papers found."

        results = []
        for entry in entries:
            title = (entry.findtext("atom:title", "", _NS) or "").strip()
            summary = (entry.findtext("atom:summary", "", _NS) or "").strip()[:300]
            link = (entry.findtext("atom:id", "", _NS) or "").strip()
            results.append(f"Title: {title}\nSummary: {summary}...\nURL: {link}")

        return "\n\n".join(results)
