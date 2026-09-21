"""Run browser-independent task lifecycle race checks with Node's built-in runner."""
from pathlib import Path
import shutil
import subprocess


def test_viewer_task_lifecycle():
    node = shutil.which("node")
    assert node, "Node is required for the viewer lifecycle checks"
    result = subprocess.run([node, "--test", str(Path(__file__).with_name("viewer_task_client.mjs"))],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
