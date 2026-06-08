import logging
import os
import re
import time
from urllib.parse import urlparse, urlunparse

import httpx
from openai import AsyncOpenAI

from app.adapters.tools.base import BaseTool
from app.adapters.tools.registry import register_tool

logger = logging.getLogger("agentzoo.tool.web_fetch")

_MAX_CONTENT_CHARS = 100_000
_MAX_HTTP_BYTES = 10 * 1024 * 1024  # 10 MB
_FETCH_TIMEOUT = 30  # seconds
_MAX_REDIRECTS = 10

_FETCH_HEADERS = {
    "Accept": "text/markdown, text/html, */*",
    "User-Agent": "AgentZoo-WebFetch/1.0",
}

_SUMMARY_GUIDELINES = (
    "Provide a concise response based only on the content above. In your response:\n"
    " - Enforce a strict 125-character maximum for quotes from any source document.\n"
    ' - Use quotation marks for exact language from articles; any language outside\n'
    "   of the quotation should never be word-for-word the same.\n"
    " - You are not a lawyer and never comment on the legality of your own prompts\n"
    "   and responses.\n"
    " - Never produce or reproduce exact song lyrics."
)


def _build_summary_prompt(markdown_content: str, user_prompt: str) -> str:
    return (
        "Web page content:\n"
        "---\n"
        f"{markdown_content}\n"
        "---\n\n"
        f"{user_prompt}\n\n"
        f"{_SUMMARY_GUIDELINES}"
    )


def _strip_html(text: str) -> str:
    """Fallback HTML stripper when markdownify is unavailable."""
    text = re.sub(
        r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(
        r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#x27;", "'", text)
    text = re.sub(r"\n[ \t]+\n", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@register_tool
class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = (
        "Fetches content from a specified URL and processes it using an AI model.\n"
        "- Takes a URL and a prompt as input\n"
        "- Fetches the URL content, converts HTML to markdown\n"
        "- Processes the content with the prompt using a small, fast model\n"
        "- Returns the model's response about the content\n"
        "- HTTP URLs are automatically upgraded to HTTPS\n"
        "- Results may be summarized if the content is very large\n"
        "- This tool is read-only and does not modify any files"
    )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch content from.",
                },
                "prompt": {
                    "type": "string",
                    "description": "The prompt to run on the fetched content.",
                },
            },
            "required": ["url", "prompt"],
        }

    async def execute(self, url: str, prompt: str) -> str:
        start_time = time.time()

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return (
                f"[Error] Unsupported URL scheme '{parsed.scheme}'. "
                "Only HTTP and HTTPS are supported."
            )

        if parsed.scheme == "http":
            parsed = parsed._replace(scheme="https")
            url = urlunparse(parsed)

        # ── fetch ──────────────────────────────────────────────────────
        try:
            async with httpx.AsyncClient(
                timeout=_FETCH_TIMEOUT,
                max_redirects=_MAX_REDIRECTS,
                follow_redirects=True,
            ) as client:
                resp = await client.get(url, headers=_FETCH_HEADERS)
        except httpx.TooManyRedirects:
            return (
                f"[Error] Too many redirects (max {_MAX_REDIRECTS}) "
                f"while fetching {url}."
            )
        except httpx.TimeoutException:
            return (
                f"[Error] Request to {url} timed out "
                f"after {_FETCH_TIMEOUT}s."
            )
        except httpx.RequestError as e:
            return f"[Error] Failed to fetch {url}: {e}"

        content_type = resp.headers.get("content-type", "")

        if resp.status_code >= 400:
            return (
                f"[Error] HTTP {resp.status_code} from {url}. "
                "The server returned an error status."
            )

        raw_bytes = resp.content
        bytes_len = len(raw_bytes)
        if bytes_len > _MAX_HTTP_BYTES:
            return (
                f"[Error] Response too large ({bytes_len} bytes). "
                f"Maximum supported size is {_MAX_HTTP_BYTES // (1024 * 1024)} MB."
            )

        try:
            text = resp.text
        except UnicodeDecodeError:
            return (
                f"[Error] Cannot decode response from {url} "
                f"(binary content-type: {content_type})."
            )

        # ── convert HTML → markdown ────────────────────────────────────
        if "text/html" in content_type:
            try:
                from markdownify import markdownify

                text = markdownify(text)
            except ImportError:
                text = _strip_html(text)

        truncated = False
        if len(text) > _MAX_CONTENT_CHARS:
            text = text[:_MAX_CONTENT_CHARS]
            truncated = True

        # ── secondary model summarization ──────────────────────────────
        summary_prompt = _build_summary_prompt(text, prompt)

        base_url = os.getenv("OPENAI_BASE_URL")
        api_key = os.getenv("OPENAI_API_KEY")
        summary_model = os.getenv("WEB_FETCH_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        client_kwargs: dict = {}
        if base_url:
            client_kwargs["base_url"] = base_url
        if api_key:
            client_kwargs["api_key"] = api_key

        try:
            client = AsyncOpenAI(**client_kwargs)
            response = await client.chat.completions.create(
                model=summary_model,
                messages=[{"role": "user", "content": summary_prompt}],
            )
            summary = response.choices[0].message.content or ""
        except Exception as e:
            logger.exception("secondary model summarization failed")
            summary = (
                f"[Error] Secondary model summarization failed: {e}\n\n"
                f"--- Raw content ---\n{text[:2000]}"
            )

        duration_ms = int((time.time() - start_time) * 1000)

        # ── assemble result ────────────────────────────────────────────
        result = (
            f"URL: {url}\n"
            f"HTTP Status: {resp.status_code}\n"
            f"Content-Type: {content_type}\n"
            f"Size: {bytes_len} bytes\n"
            f"Duration: {duration_ms}ms\n\n"
            f"{summary}"
        )

        if truncated:
            result += "\n\n[Original content was truncated due to length...]"

        return result
