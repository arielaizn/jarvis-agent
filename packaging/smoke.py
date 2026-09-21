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
result.unlink(missing_ok=True)
with tempfile.TemporaryDirectory(prefix='jarvis-smoke-') as state:
    env={**os.environ,'JARVIS_DATA_DIR':state,'JARVIS_GALAXY_MUTE':'1','JARVIS_OPEN_GALAXY':'0'}
    process=subprocess.run([str(exe),'--smoke-test',str(result)],env=env,cwd=root,timeout=120)
    if result.exists():print(result.read_text())
    if process.returncode:raise SystemExit(process.returncode)
    record=json.loads(result.read_text());assert record['frozen'] and all(record['checks'].values()),record
    # Verify the packaged executable can also launch its own HTTP worker.
    # Never rely on a separately installed Python for subprocesses.
    import socket, time
    from urllib.request import urlopen
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    worker=subprocess.Popen([str(exe),'-u',str(Path(state)/'server.py'),'--port',str(port),'--no-card'],env=env,cwd=root,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+30
        while True:
            try:
                with urlopen(f'http://127.0.0.1:{port}/state',timeout=1) as response:
                    live=json.load(response)
                assert isinstance(live.get('known_models'),list)
                with urlopen(f'http://127.0.0.1:{port}/ack',timeout=2) as response:
                    cue=json.load(response)
                assert str(cue.get('audio','')).startswith('data:audio/wav;base64,'), 'Bundled acknowledgment missing on first run'
                record['checks']['fresh_install_acknowledgment']=True
                record['checks']['packaged_server_worker']=True
                result.write_text(json.dumps(record,indent=2));break
            except Exception:
                if worker.poll() is not None or time.monotonic()>deadline:raise
                time.sleep(.2)
    finally:
        worker.terminate()
        try:worker.wait(timeout=5)
        except subprocess.TimeoutExpired:worker.kill();worker.wait(timeout=5)
    print('Packaged server worker: PASS')
