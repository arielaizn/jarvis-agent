"""Cross-process exclusive file locks on Windows and POSIX."""
from contextlib import contextmanager
import os
import time


@contextmanager
def exclusive_file_lock(file):
    if os.name == 'nt':
        import msvcrt
        file.seek(0, 2)
        if file.tell() == 0:
            file.write('0'); file.flush()
        while True:
            file.seek(0)
            try:
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                time.sleep(.05)
        try:
            yield
        finally:
            file.seek(0); msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)
