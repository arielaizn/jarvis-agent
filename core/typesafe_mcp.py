"""Project-scoped stdio tool for Codex and Jarvis's Gemini tool loop."""
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from core.typesafe_client import TypeSafeError, evaluate

server = FastMCP("jarvis-typesafe")


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                        idempotentHint=True, openWorldHint=True))
def typesafe_evaluate(state: str | dict | list, questions: dict) -> dict:
    """Evaluate explicit data with TypeSafe Jev. Questions map IDs to type,
    instructions and criteria. Types: choice (criteria option map), noul (yes/no),
    score (ordered criteria list). Read the typesafe-ai skill first. Include a
    no-match choice when relevant. Judgments are not permission to execute actions.
    Only the supplied state is sent to TypeSafe; credentials stay inside this tool.
    """
    try:
        return evaluate(state, questions)
    except TypeSafeError as exc:
        return {"ok": False, "error": str(exc)}


if __name__ == "__main__":
    server.run(transport="stdio")
