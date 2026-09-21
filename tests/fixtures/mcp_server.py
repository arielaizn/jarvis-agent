"""Real SDK fixture, isolated from user MCP configuration and applications."""
import argparse
import asyncio
import os
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

parser = argparse.ArgumentParser()
parser.add_argument("--transport", default="stdio")
parser.add_argument("--port", type=int, default=8000)
parser.add_argument("--noisy", action="store_true")
args = parser.parse_args()
if args.noisy:
    for _ in range(8):
        print("untrusted startup output TOP-SECRET-TEST", flush=True)
server = FastMCP("jarvis-test", host="127.0.0.1", port=args.port, log_level="ERROR")
calls = 0


@server.tool()
def add(a: int, b: int) -> dict[str, int]:
    """Add integers and report the subprocess identifier."""
    global calls
    calls += 1
    return {"sum": a + b, "calls": calls, "pid": os.getpid()}


@server.tool(structured_output=False)
def explicit_error() -> CallToolResult:
    """Produce a protocol tool error with structured metadata."""
    return CallToolResult(isError=True, content=[TextContent(type="text", text="שגיאת בדיקה")],
                          structuredContent={"reason": "fixture", "retry": False})


@server.tool()
async def wait_slowly(seconds: float = 2) -> dict[str, float]:
    """A cancellable slow operation."""
    await asyncio.sleep(min(seconds, 5))
    return {"waited": seconds}


@server.tool()
def large_result() -> dict[str, str]:
    """A large structured result for truncation tests."""
    return {"text": "אבג" * 3000, "marker": "retained"}


@server.resource("fixture://greeting")
def greeting() -> str:
    return "שלום מארח MCP"


@server.resource("fixture://person/{name}")
def person(name: str) -> str:
    return f"שלום {name}"


@server.prompt()
def welcome(name: str) -> str:
    return f"שלום {name}, כתוב הודעת פתיחה בעברית"


server.run(transport=args.transport)
