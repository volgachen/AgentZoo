# Import all tools to trigger @register_tool decoration
from app.adapters.tools import (  # noqa: F401
    web_search,
    arxiv_search,
    web_fetch,
    subagent,
    bash,
    read,
    write,
    edit,
    session_send,
)
