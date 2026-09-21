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


def test_explicit_skill_request_uses_shared_task_queue(monkeypatch):
    ui = MagicMock();ui.galaxy_mode = False
    jarvis = JarvisLive(ui)
    jarvis._native_codex.state = AsyncMock(return_value={"provider": "gemini"})
    jarvis._native_codex.ask = AsyncMock(return_value={"answer":"בדיקה, אדוני.","model":"gemini-3.8-flash","provider":"gemini"})
    jarvis._hud_brain.ask = AsyncMock()
    asyncio.run(jarvis._send_user_command("/sample בדיקה"))
    assert jarvis._native_codex.ask.call_args.args[0] == "/sample בדיקה"
    jarvis._hud_brain.ask.assert_not_called()


def test_gemini_task_receives_slash_skill_before_request(monkeypatch, tmp_path):
    from core.codex_tasks import TaskManager
    from core import gemini_tasks
    from test_codex_integration import wait_task
    monkeypatch.setattr('core.skills.skill_prompt_context',lambda text:'SAMPLE SKILL CONTENT')
    execute=MagicMock(return_value={'answer':'בוצע, אדוני.'})
    monkeypatch.setattr(gemini_tasks,'execute',execute)
    manager=TaskManager(tmp_path,provider='gemini')
    try:
        assert wait_task(manager,manager.start('/sample בדיקה')['id'])['status']=='completed'
        prompt=execute.call_args.args[0]
        assert prompt.index('SAMPLE SKILL CONTENT') < prompt.index('/sample בדיקה')
    finally:manager.close()


def test_setup_status_does_not_call_installed_apps_connected():
    result = collect_status()
    assert isinstance(result["checks"], list)
    assert all(set(item) == {"name", "status", "detail"} for item in result["checks"])
    assert all(item["status"] in {"ready", "needs_setup", "unavailable"} for item in result["checks"])
