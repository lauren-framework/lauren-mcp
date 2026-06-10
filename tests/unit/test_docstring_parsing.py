"""Unit tests for docstring parsing (Google / Sphinx / NumPy styles)."""

from __future__ import annotations

from lauren_mcp.server._docstring import parse_docstring
from lauren_mcp.server._meta import MCP_TOOL_META


def google_style(self, query: str, limit: int = 10) -> list:
    """Search the catalogue.

    Args:
        query: Free-text search query.
        limit (int): Maximum number of results
            to return in one page.

    Returns:
        Matching items.
    """


def sphinx_style(self, query: str, limit: int = 10) -> list:
    """Search the catalogue.

    :param query: Free-text search query.
    :param int limit: Maximum number of results.
    :returns: Matching items.
    """


def numpy_style(self, query: str, limit: int = 10) -> list:
    """Search the catalogue.

    Parameters
    ----------
    query : str
        Free-text search query.
    limit : int
        Maximum number of results.

    Returns
    -------
    list
        Matching items.
    """


class TestTopDescription:
    def test_google(self):
        top, _ = parse_docstring(google_style)
        assert top == "Search the catalogue."

    def test_sphinx(self):
        top, _ = parse_docstring(sphinx_style)
        assert top == "Search the catalogue."

    def test_numpy(self):
        top, _ = parse_docstring(numpy_style)
        assert top == "Search the catalogue."

    def test_no_docstring(self):
        def bare(x):
            pass

        assert parse_docstring(bare) == ("", {})

    def test_multi_line_top_description(self):
        def fn(x):
            """First line
            second line of the same paragraph.

            Args:
                x: A thing.
            """

        top, _ = parse_docstring(fn)
        assert top == "First line second line of the same paragraph."


class TestParamDescriptions:
    def test_google_params(self):
        _, params = parse_docstring(google_style)
        assert params["query"] == "Free-text search query."
        # Continuation lines are merged; the inline type hint is stripped.
        assert params["limit"] == "Maximum number of results to return in one page."

    def test_sphinx_params(self):
        _, params = parse_docstring(sphinx_style)
        assert params["query"] == "Free-text search query."
        assert params["limit"] == "Maximum number of results."

    def test_numpy_params(self):
        _, params = parse_docstring(numpy_style)
        assert params["query"] == "Free-text search query."
        assert params["limit"] == "Maximum number of results."

    def test_returns_section_not_treated_as_param(self):
        _, params = parse_docstring(google_style)
        assert "Returns" not in params
        assert "list" not in params


class TestSchemaIntegration:
    def test_descriptions_injected_into_schema(self):
        from lauren_mcp import mcp_tool

        @mcp_tool()
        async def search(self, query: str, limit: int = 10) -> list:
            """Search the catalogue.

            Args:
                query: Free-text search query.
                limit: Maximum number of results.
            """

        meta = getattr(search, MCP_TOOL_META)
        props = meta.input_schema["properties"]
        assert props["query"]["description"] == "Free-text search query."
        assert props["limit"]["description"] == "Maximum number of results."

    def test_explicit_description_overrides_top_but_keeps_params(self):
        from lauren_mcp import mcp_tool

        @mcp_tool(description="Overridden")
        async def search(self, query: str) -> list:
            """Original top.

            Args:
                query: Q description.
            """

        meta = getattr(search, MCP_TOOL_META)
        assert meta.description == "Overridden"
        assert meta.input_schema["properties"]["query"]["description"] == "Q description."

    def test_prompt_arguments_get_descriptions(self):
        from lauren_mcp import mcp_prompt
        from lauren_mcp.server._meta import MCP_PROMPT_META

        @mcp_prompt()
        async def suggest(self, topic: str) -> str:
            """Suggest something.

            Args:
                topic: What to suggest about.
            """

        meta = getattr(suggest, MCP_PROMPT_META)
        assert meta.arguments[0]["description"] == "What to suggest about."
