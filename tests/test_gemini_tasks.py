from types import SimpleNamespace
from unittest.mock import MagicMock
import threading
from google.genai import types
from core import gemini, gemini_tasks


def test_gemini_task_uses_declared_tools_and_preserves_real_results(monkeypatch, tmp_path):
    target = tmp_path/'result.txt'
    client = MagicMock()
    def response(part):
        return SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(role='model', parts=[part]))])
    client.models.generate_content.side_effect = [
        response(types.Part(function_call=types.FunctionCall(name='file_controller', args={'content':'verified'}))),
        response(types.Part(text='נכתב ונבדק, אדוני.'))]
    monkeypatch.setattr(gemini, 'client', lambda **_: client)
    actions = MagicMock()
    actions.get_tool_declarations.return_value = [{'name':'file_controller','description':'write a file','parameters':{'type':'OBJECT','properties':{'content':{'type':'STRING'}}}}]
    def run(name, args):
        target.write_text(args['content']);return target.read_text()
    actions.run.side_effect = run
    result = gemini_tasks.execute('write', cancel=threading.Event(), progress=lambda _: None, actions=actions)
    assert target.read_text() == 'verified'
    assert result['model'] == 'gemini-3.8-flash' and result['tools'] == ['file_controller']
    sent = client.models.generate_content.call_args.kwargs
    assert sent['model'] == 'gemini-3.8-flash'
    responses = [p.function_response for c in sent['contents'] for p in c.parts if p.function_response]
    assert responses[0].response == {'result':'verified'}
    assert 'אדוני' in sent['config'].system_instruction
    assert sent['config'].thinking_config.thinking_level == 'LOW'


def test_task_registry_includes_computer_browser_files_and_mcp():
    assert {'computer_control','browser_agent','browser_control','file_controller','mcp','open_app','editing_apps'} <= gemini_tasks.registry().names()
