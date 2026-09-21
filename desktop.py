"""Packaged desktop entrypoint and dispatcher for bundled helper processes."""
from pathlib import Path
import json
import os
import runpy
import shutil
import sys

VERSION = '1.0.0'


def prepare_runtime():
    from core.app_paths import resource_root, runtime_root, is_packaged
    root, resources = runtime_root(), resource_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if is_packaged():
        from core.file_lock import exclusive_file_lock
        with (root / '.install.lock').open('a+') as lock, exclusive_file_lock(lock):
            manifest = json.loads((resources / 'app-manifest.json').read_text())
            for name in manifest:
                relative = Path(name)
                if relative.is_absolute() or '..' in relative.parts:
                    raise RuntimeError('Invalid packaged resource path')
                source, target = resources / 'app-source' / relative, root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists() or target.read_bytes() != source.read_bytes():
                    temporary = target.with_name(target.name + '.install-tmp')
                    shutil.copyfile(source, temporary)
                    os.replace(temporary, target)
    native = resources / 'native' / 'focus-surface'
    if is_packaged() and native.is_file():
        target = root / '.runtime' / 'focus-surface'
        target.parent.mkdir(exist_ok=True)
        if not target.exists() or target.read_bytes() != native.read_bytes():
            shutil.copyfile(native, target); target.chmod(0o700)
        os.utime(target, None)
    config = root / 'config.json'
    if not config.exists():
        notes = root / 'notes'
        notes.mkdir(exist_ok=True)
        (notes / 'Welcome.md').write_text('# Welcome to Jarvis Agent\n\nYour private notes stay on this computer. Set notes_dir in your local config.json before starting the server to use a different directory.\n', encoding='utf-8')
        with config.open('x', encoding='utf-8') as stream:
            json.dump({'api_provider':'codex', 'model':'gpt-6-astra', 'notes_dir':str(notes)}, stream)
        config.chmod(0o600)
    os.chdir(root)
    return root


def smoke_test(root, destination):
    """Real packaged imports, local HTTP service and native Qt window. No API calls."""
    os.environ['JARVIS_OPEN_GALAXY'] = '0'
    os.environ['JARVIS_GALAXY_MUTE'] = '1'
    import threading
    from urllib.request import urlopen
    from server import GalaxyApp, GalaxyServer
    from PySide6.QtCore import QTimer
    app = GalaxyApp(root)
    server = GalaxyServer(('127.0.0.1', 0), app)
    worker = threading.Thread(target=server.serve_forever, daemon=True);worker.start()
    checks = {'native_render':False,'command_center':False,'embedded_galaxy':False,'microphone_off':False,'native_bridge':False}
    try:
        base = 'http://127.0.0.1:' + str(server.server_port)
        with urlopen(base + '/') as response: checks['viewer_http'] = response.status == 200
        with urlopen(base + '/graph') as response: checks['graph'] = len(json.load(response)['nodes']) > 0
        with urlopen(base + '/tasks') as response: checks['parallel_workers'] = json.load(response)['max_workers'] == 3
        os.environ['JARVIS_PORT'] = str(server.server_port)
        from core import galaxy_service
        galaxy_service.BASE = base
        from ui import JarvisUI
        ui = JarvisUI(str(root / 'config' / 'jarvis.ico'));ui.muted = True
        ui._win._open_galaxy()
        panel = ui._win._galaxy_panel
        checks['native_window'] = ui._win.isVisible()
        def finish():
            checks['native_render'] = not ui._win.grab().isNull()
            ui._win.grab().save(str(Path(destination).with_suffix('.png')))
            ui._win.close();ui._app.quit()
        settled = False
        def inspect(value):
            nonlocal settled
            if isinstance(value, str):
                try: value = json.loads(value)
                except ValueError: return
            if settled or not value or not value.get('ready'): return
            settled = True
            checks['command_center'] = bool(value.get('command_ready'))
            checks['embedded_galaxy'] = bool(value.get('rendered'))
            checks['microphone_off'] = bool(value.get('muted'))
            checks['native_bridge'] = bool(value.get('native_bridge'))
            timer.stop()
            # Let WebEngine paint after graph initialization before capturing it.
            QTimer.singleShot(2500, finish)
        timer = QTimer()
        timer.timeout.connect(lambda: panel.page.runJavaScript('''(() => { const c=window.JarvisCommand?.inspect(); if(!c?.ready)return null; let f=document.querySelector('.galaxy-frame'); if(!f){document.querySelector('.sidebar button[title="המוח השני"]')?.click();return null;} const g=f.contentWindow?.JarvisGalaxy?.inspect(); return JSON.stringify(g?{...g,command_ready:c.ready,native_bridge:c.native_bridge,muted:c.muted}:null); })()''', inspect))
        timer.start(300)
        def timeout():
            if not settled:
                checks['embedded_galaxy'] = False
                timer.stop();finish()
        QTimer.singleShot(45000, timeout)
        ui._app.exec()
        checks['keys_not_bundled'] = not (root / 'config' / 'api_keys.json').exists()
        if sys.platform == 'darwin':
            import subprocess
            native = root / '.runtime' / 'focus-surface'
            sample = subprocess.run([str(native)],capture_output=True,text=True,timeout=5)
            checks['bundled_focus_reader'] = sample.returncode == 0 and isinstance(json.loads(sample.stdout).get('readable'),bool)
        record = {'version': VERSION, 'platform': sys.platform, 'frozen':bool(getattr(sys,'frozen',False)), 'checks': checks}
        Path(destination).write_text(json.dumps(record, indent=2), encoding='utf-8')
        return 0 if all(checks.values()) else 1
    finally:
        server.shutdown();server.server_close();app.close()


def main():
    import multiprocessing
    multiprocessing.freeze_support()
    # macOS Finder and Windows windowed apps have no inherited terminal.
    if sys.stdout is None: sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None: sys.stderr = open(os.devnull, 'w')
    from core.app_paths import is_packaged
    if is_packaged():
        candidates = [Path.home()/'.local/bin',Path.home()/'.npm-global/bin',Path('/opt/homebrew/bin'),Path('/usr/local/bin')]
        if os.name == 'nt': candidates.append(Path(os.environ.get('APPDATA', Path.home()))/'npm')
        os.environ['PATH'] = os.pathsep.join([str(p) for p in candidates if p.is_dir()] + [os.environ.get('PATH','')])
    root = prepare_runtime()
    args = sys.argv[1:]
    while args and args[0] in {'-u', '-B'}: args.pop(0)
    if args and args[0] == '--smoke-test':
        return smoke_test(root, args[1])
    if args and args[0] == '-m':
        module = args[1]
        allowed = {'core.live_speech','core.galaxy_card','core.typesafe_mcp','core.typesafe_client'}
        if module not in allowed: raise SystemExit('This optional worker needs an external Python installation: ' + module)
        sys.argv = [module, *args[2:]]
        runpy.run_module(module, run_name='__main__')
        return 0
    if args and args[0].endswith('.py'):
        script = Path(args[0]).resolve()
        modules = {root/'main.py':'main', root/'server.py':'server', root/'core/typesafe_mcp.py':'core.typesafe_mcp', root/'preflight.py':'preflight'}
        if script not in modules: raise SystemExit('This script needs an external Python installation')
        sys.argv = [str(script), *args[1:]]
        runpy.run_module(modules[script], run_name='__main__')
        return 0
    os.environ.setdefault('JARVIS_OPEN_GALAXY', '1')
    from main import main as launch
    launch()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
