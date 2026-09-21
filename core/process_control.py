"""Terminate an owned subprocess group, even after its leader has exited."""
import os
import signal
import subprocess
import threading

_STOP_LOCK = threading.RLock()


def stop_process_tree(process: subprocess.Popen) -> None:
    # Deadline, cancel and normal completion can arrive together. A group is
    # terminated once; never signal an already reaped process ID a second time.
    with _STOP_LOCK:
        if getattr(process, "_jarvis_tree_stopped", False):
            return
        _stop_process_tree(process)
        process._jarvis_tree_stopped = True


def _stop_process_tree(process: subprocess.Popen) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            process.poll()
            return
        except PermissionError:
            if process.poll() is not None:
                return
            raise
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        # A finished leader does not imply that children released the pipes.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # macOS can return EPERM when the group's only remaining members
            # have already exited. A living group leader must still fail loudly.
            if process.poll() is None:
                raise
        process.wait(timeout=3)
    elif process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
