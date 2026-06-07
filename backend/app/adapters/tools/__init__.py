# Import all tools to trigger @register_tool decoration
from app.adapters.tools import (  # noqa: F401
    web_search,
    arxiv_search,
    bash,
    read,
    write,
    edit,
)
