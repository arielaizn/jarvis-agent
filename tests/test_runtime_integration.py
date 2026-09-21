import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from main import JarvisLive
from core.integration_status import collect_status


def test_new_actions_reach_live_model_and_hebrew_instructions():
    ui = MagicMock()
    ui.muted = False
    jarvis = JarvisLive(ui)
    config = jarvis._build_hud_config()
    names = {tool.name for tool in config.tools[0].function_declarations}
    assert {"browser_agent", "editing_apps", "skills", "mcp"} <= names
    assert "Speak and write Hebrew" in config.system_instruction


def test_slash_instructions_arrive_before_user_request(monkeypatch):
    monkeypatch.setattr("main.skill_prompt_context", lambda text: "SAMPLE SKILL CONTENT")
    ui = MagicMock()
    ui.galaxy_mode = False
    jarvis = JarvisLive(ui)
    jarvis._native_codex.state = AsyncMock(return_value={"provider": "gemini"})
    jarvis._hud_brain.ask = AsyncMock(return_value={"answer": "בדיקה", "model": "gemini-3.8-flash", "tools": []})
    asyncio.run(jarvis._send_user_command("/sample בדיקה"))
    parts = jarvis._hud_brain.ask.call_args.args[0]
    assert "SAMPLE SKILL CONTENT" in parts[0].text
    assert parts[-1].text == "/sample בדיקה"


def test_setup_status_does_not_call_installed_apps_connected():
    result = collect_status()
    assert isinstance(result["checks"], list)
    assert all(set(item) == {"name", "status", "detail"} for item in result["checks"])
    assert all(item["status"] in {"ready", "needs_setup", "unavailable"} for item in result["checks"])
