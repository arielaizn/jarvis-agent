"""Copy-on-write staging on APFS; ordinary shutil copies on other filesystems.

PyInstaller stages identical signed Qt binaries several times. Clones preserve
independent files while avoiding duplicate allocation on small startup volumes.
"""
import ctypes
import os
from pathlib import Path
import shutil
import sys
import uuid


def install():
    if sys.platform != 'darwin':return
    original=shutil.copyfile
    if getattr(original,'_jarvis_clone',False):return
    clone=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True).clonefile
    clone.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_int];clone.restype=ctypes.c_int
    def copyfile(src,dst,*,follow_symlinks=True):
        source,target=Path(src),Path(dst)
        if follow_symlinks and source.is_file() and not source.is_symlink() and source.resolve()!=target.resolve() and target.parent.is_dir() and not target.is_symlink():
            temporary=target.with_name('.jarvis-clone-'+uuid.uuid4().hex)
            try:
                if clone(os.fsencode(source),os.fsencode(temporary),0)==0:
                    os.replace(temporary,target)
                    return dst
            finally:
                temporary.unlink(missing_ok=True)
        return original(src,dst,follow_symlinks=follow_symlinks)
    copyfile._jarvis_clone=True
    shutil.copyfile=copyfile
