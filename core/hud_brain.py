"""Bounded REST conversation/tool loop for the native Jarvis HUD."""
from __future__ import annotations

import asyncio
import contextlib
from google.genai import types
from core import gemini

MAX_TOOL_ROUNDS = 6
MAX_TOOL_CALLS = 12
HISTORY_TURNS = 6
REQUEST_TIMEOUT_MS = 45_000
TRANSIENT_ATTEMPTS = 3


class BrainUnavailable(RuntimeError):
    def __init__(self, message, *, status=None):
        super().__init__(message)
        self.status = status if isinstance(status, int) else None


class TurnSuperseded(RuntimeError):
    pass


class HudBrain:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.history = []

    def clear(self):
        self.history.clear()

    async def ask(self, parts, config, execute, *, cancelled=lambda: False,
                  take_vision=lambda: []):
        """Only function calls from this pinned REST request reach execute."""
        async with self.lock:
            def current():
                if cancelled():
                    raise TurnSuperseded()

            current()
            turn = [types.Content(role="user", parts=parts)]
            contents = [content for previous in self.history for content in previous] + turn
            calls = 0
            used_tools = []
            client = gemini.client(timeout_ms=REQUEST_TIMEOUT_MS)
            try:
                for _ in range(MAX_TOOL_ROUNDS + 1):
                    current()
                    response = None
                    for attempt in range(TRANSIENT_ATTEMPTS):
                        try:
                            response = await asyncio.to_thread(
                                client.models.generate_content,
                                model=gemini.MODEL, contents=contents, config=config)
                            break
                        except Exception as error:
                            current()
                            status = getattr(error, "code", None)
                            if status not in {500, 502, 503, 504} or attempt + 1 == TRANSIENT_ATTEMPTS:
                                raise BrainUnavailable(
                                    f"{gemini.MODEL} unavailable; status={status if isinstance(status, int) else 'unknown'}",
                                    status=status,
                                ) from None
                            await asyncio.sleep(attempt + 1)
                    current()
                    candidates = getattr(response, "candidates", None) or []
                    content = candidates[0].content if candidates else None
                    if content is None or not content.parts:
                        raise BrainUnavailable(f"{gemini.MODEL} returned no answer")
                    turn.append(content)
                    contents.append(content)
                    functions = [part.function_call for part in content.parts if part.function_call]
                    if not functions:
                        answer = "".join(part.text or "" for part in content.parts if not part.thought).strip()
                        if not answer:
                            raise BrainUnavailable(f"{gemini.MODEL} returned no answer")
                        self.history.append(turn)
                        self.history = self.history[-HISTORY_TURNS:]
                        return {"answer": answer, "model": gemini.MODEL, "tools": used_tools}
                    calls += len(functions)
                    if calls > MAX_TOOL_CALLS or _ == MAX_TOOL_ROUNDS:
                        raise BrainUnavailable("The tool limit was reached before a final answer")
                    tool_parts = []
                    for function in functions:
                        current()
                        result = await execute(function)
                        current()
                        used_tools.append(function.name)
                        # Live-only scheduling fields must not reach REST.
                        tool_parts.append(types.Part(function_response=types.FunctionResponse(
                            id=result.id, name=result.name, response=result.response)))
                    tool_content = types.Content(role="user", parts=tool_parts)
                    contents.append(tool_content)
                    turn.append(tool_content)
                    vision = take_vision()
                    if vision:
                        # A frame is attached to this request only, never kept
                        # in subsequent conversation history.
                        contents.append(types.Content(role="user", parts=vision))
                raise BrainUnavailable("The tool limit was reached before a final answer")
            finally:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(client.close)
