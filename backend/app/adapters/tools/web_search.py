import httpx
from app.adapters.tools.base import BaseTool
from app.adapters.tools.registry import register_tool


@register_tool
class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web for current information using DuckDuckGo."

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        }

    async def execute(self, query: str) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                timeout=10,
                follow_redirects=True,
            )
            data = resp.json()

        parts: list[str] = []
        if data.get("AbstractText"):
            parts.append(data["AbstractText"])
        for item in data.get("RelatedTopics", [])[:5]:
            if isinstance(item, dict) and item.get("Text"):
                parts.append(item["Text"])

        return "\n".join(parts) if parts else "No results found."
