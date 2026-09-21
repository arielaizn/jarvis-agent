"""End-to-end SDK tests; no model credentials or global MCP config required."""
from __future__ import annotations
import concurrent.futures
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from core.mcp_client import MCPManager

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_server.py"


class MCPClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "mcp.json"
        self.write_config({"fixture": {"command": sys.executable, "args": [str(FIXTURE)]}})
        self.manager = MCPManager(self.path)

    def write_config(self, servers, **other):
        self.path.write_text(json.dumps({"mcpServers": servers, **other}), encoding="utf-8")

    def tearDown(self):
        self.manager.close()
        self.temp.cleanup()

    def test_tools_structured_result_persistent_session_and_close(self):
        listing = self.manager.execute("list_tools", server="fixture")
        self.assertTrue(listing["ok"], listing)
        tools = {tool["name"]: tool for tool in listing["result"]["tools"]}
        self.assertIn("add", tools)
        self.assertIn("inputSchema", tools["add"])
        first = self.manager.execute("call_tool", "fixture", "add", {"a": 2, "b": 3})
        second = self.manager.execute("call_tool", "fixture", "add", {"a": 1, "b": 3})
        self.assertEqual(first["result"]["structuredContent"]["sum"], 5)
        self.assertEqual(second["result"]["structuredContent"]["calls"], 2)
        self.assertEqual(first["result"]["structuredContent"]["pid"], second["result"]["structuredContent"]["pid"])
        self.assertFalse(first["isError"])
        self.assertTrue(self.manager.execute("status")["servers"][0]["connected"])
        self.manager.close()
        self.assertFalse(self.manager._thread.is_alive())

    def test_resources_templates_and_prompts(self):
        resources = self.manager.execute("list_resources", "fixture")
        self.assertTrue(resources["ok"], resources)
        self.assertEqual(resources["result"]["resources"][0]["uri"], "fixture://greeting")
        read = self.manager.execute("read_resource", "fixture", uri="fixture://greeting")
        self.assertEqual(read["result"]["contents"][0]["text"], "שלום מארח MCP")
        templates = self.manager.execute("list_resource_templates", "fixture")
        self.assertEqual(templates["result"]["resourceTemplates"][0]["uriTemplate"], "fixture://person/{name}")
        prompts = self.manager.execute("list_prompts", "fixture")
        self.assertEqual(prompts["result"]["prompts"][0]["name"], "welcome")
        prompt = self.manager.execute("get_prompt", "fixture", "welcome", {"name": "אריאל"})
        self.assertIn("אריאל", prompt["result"]["messages"][0]["content"]["text"])

    def test_tool_error_preserves_content_and_structured_data(self):
        result = self.manager.execute("call_tool", "fixture", "explicit_error")
        self.assertFalse(result["ok"], result)
        self.assertTrue(result["result"]["isError"])
        self.assertEqual(result["result"]["structuredContent"], {"reason": "fixture", "retry": False})
        self.assertEqual(result["result"]["content"][0]["text"], "שגיאת בדיקה")
        self.assertTrue(self.manager.execute("list_tools", "fixture")["ok"])

    def test_timeout_invalidates_session_then_next_call_reconnects(self):
        initial = self.manager.execute("call_tool", "fixture", "add", {"a": 1, "b": 1})
        old_pid = initial["result"]["structuredContent"]["pid"]
        start = time.monotonic()
        result = self.manager.execute("call_tool", "fixture", "wait_slowly", {"seconds": 2}, timeout=.15)
        self.assertEqual(result["error"], "timeout", result)
        self.assertLess(time.monotonic() - start, 3)
        reconnect = self.manager.execute("call_tool", "fixture", "add", {"a": 3, "b": 3})
        self.assertTrue(reconnect["ok"], reconnect)
        self.assertNotEqual(reconnect["result"]["structuredContent"]["pid"], old_pid)
        self.assertEqual(reconnect["result"]["structuredContent"]["calls"], 1)

    def test_disconnected_process_reconnects_without_replaying(self):
        first = self.manager.execute("call_tool", "fixture", "add", {"a": 1, "b": 2})
        pid = first["result"]["structuredContent"]["pid"]
        os.kill(pid, 15)
        failure = self.manager.execute("call_tool", "fixture", "add", {"a": 4, "b": 5}, timeout=1)
        self.assertFalse(failure["ok"], failure)
        recovered = self.manager.execute("call_tool", "fixture", "add", {"a": 4, "b": 5})
        self.assertTrue(recovered["ok"], recovered)
        self.assertEqual(recovered["result"]["structuredContent"]["calls"], 1)

    def test_large_payload_is_kept_whole_in_private_file(self):
        self.write_config({"fixture": {"command": sys.executable, "args": [str(FIXTURE)]}}, max_result_characters=1000)
        result = self.manager.execute("call_tool", "fixture", "large_result")
        self.assertTrue(result["truncated"], result)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), 1000)
        path = Path(result["full_result_path"])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        full = json.loads(path.read_text())
        self.assertEqual(full["result"]["structuredContent"]["marker"], "retained")
        self.assertEqual(len(full["result"]["structuredContent"]["text"]), 9000)
        self.assertFalse(result["isError"])
        self.manager.close()
        self.assertFalse(path.exists())

    def test_secret_refs_validation_and_no_arbitrary_servers(self):
        self.write_config({"secret": {"url": "https://example.invalid/mcp", "headers": {"Authorization": "Bearer ${JARVIS_TEST_TOKEN}"}}})
        with patch.dict(os.environ, {}, clear=True):
            result = self.manager.execute("list_tools", "secret")
        self.assertEqual(result["error"], "invalid_config")
        with patch.dict(os.environ, {"JARVIS_TEST_TOKEN": "TOP-SECRET-TEST"}):
            status = self.manager.execute("servers")
        self.assertNotIn("TOP-SECRET-TEST", json.dumps(status))
        self.assertNotIn("Authorization", json.dumps(status))
        self.assertEqual(self.manager.execute("call_tool", "unconfigured", "anything")["error"], "unknown_server")
        self.assertEqual(self.manager.execute("register", "anything")["error"], "invalid_action")

    def test_concurrent_calls_share_owner_session(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(self.manager.execute, "call_tool", "fixture", "add", {"a": i, "b": 1}) for i in range(3)]
            results = [future.result() for future in futures]
        self.assertTrue(all(result["ok"] for result in results), results)
        self.assertEqual({r["result"]["structuredContent"]["calls"] for r in results}, {1, 2, 3})
        self.assertEqual(len({r["result"]["structuredContent"]["pid"] for r in results}), 1)

    def test_action_json_arguments(self):
        from actions.mcp import mcp
        with patch("actions.mcp.get_mcp_manager", return_value=self.manager):
            bad = json.loads(mcp({"action": "call_tool", "arguments_json": "broken"}))
            self.assertEqual(bad["error"], "invalid_arguments")
            result = json.loads(mcp({"action": "call_tool", "server": "fixture", "name": "add", "arguments_json": '{"a":5,"b":7}'}))
            self.assertEqual(result["result"]["structuredContent"]["sum"], 12)

    def test_noisy_server_logs_are_counted_without_wire_content(self):
        self.write_config({"fixture": {"command": sys.executable, "args": [str(FIXTURE), "--noisy"]}})
        with self.assertLogs(level="WARNING") as captured:
            result = self.manager.execute("list_tools", "fixture")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["diagnostics"]["protocol_warnings"], 8)
        logs = "\n".join(captured.output)
        self.assertNotIn("TOP-SECRET-TEST", logs)
        self.assertNotIn("untrusted startup", logs)
        self.assertNotIn("Traceback", logs)
        self.assertIn("protocol_warnings=1", logs)
        self.assertLessEqual(len(captured.output), 2)

    def test_missing_invalid_and_disabled_configuration(self):
        self.path.unlink()
        self.assertEqual(self.manager.execute("servers")["servers"], [])
        self.path.write_text("[broken")
        self.assertEqual(self.manager.execute("servers")["error"], "invalid_config")
        self.write_config({"fixture": {"command": sys.executable, "disabled": True}})
        self.assertFalse(self.manager.execute("servers")["servers"][0]["enabled"])
        self.assertEqual(self.manager.execute("list_tools", "fixture")["error"], "invalid_config")

    def test_http_and_legacy_sse_transports_with_real_sdk(self):
        for transport, suffix in [("streamable-http", "/mcp"), ("sse", "/sse")]:
            with self.subTest(transport=transport):
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                process = subprocess.Popen([sys.executable, str(FIXTURE), "--transport", transport, "--port", str(port)],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        try:
                            with socket.create_connection(("127.0.0.1", port), timeout=.1):
                                break
                        except OSError:
                            if process.poll() is not None:
                                self.fail("MCP HTTP fixture exited")
                            time.sleep(.05)
                    self.write_config({"remote": {"transport": transport, "url": f"http://127.0.0.1:{port}{suffix}"}})
                    result = self.manager.execute("call_tool", "remote", "add", {"a": 8, "b": 2}, timeout=5)
                    self.assertTrue(result["ok"], result)
                    self.assertEqual(result["result"]["structuredContent"]["sum"], 10)
                    self.manager.close()
                    self.manager = MCPManager(self.path)
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
