"""Test the built executable, with isolated state and no developer credentials."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
root=Path(__file__).resolve().parents[1]
exe=(root/'dist'/'Jarvis Agent.app'/'Contents'/'MacOS'/'JarvisAgent' if sys.platform=='darwin' else root/'dist'/'JarvisAgent'/('JarvisAgent.exe' if os.name=='nt' else 'JarvisAgent'))
result=root/'build'/('smoke-'+sys.platform+'.json')
with tempfile.TemporaryDirectory(prefix='jarvis-smoke-') as state:
    env={**os.environ,'JARVIS_DATA_DIR':state,'JARVIS_GALAXY_MUTE':'1','JARVIS_OPEN_GALAXY':'0'}
    process=subprocess.run([str(exe),'--smoke-test',str(result)],env=env,cwd=root,timeout=120)
    if result.exists():print(result.read_text())
    if process.returncode:raise SystemExit(process.returncode)
    record=json.loads(result.read_text());assert record['frozen'] and all(record['checks'].values()),record
