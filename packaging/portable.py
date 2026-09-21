"""Assemble Windows/Linux distributions locally without executing foreign code.

Runtime hashes are pinned from the python-build-standalone release. uv resolves
markers and binary wheels for the target, not the machine running this script.
An assembly report is deliberately distinct from an OS runtime smoke test.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tarfile
from urllib.request import urlopen
import zipfile

from export_source import sources

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.0.0'
PYTHON = '3.12.14'
PYTHON_RELEASE = '20260901'
TARGETS = {
    'Windows': ('x86_64-pc-windows-msvc', 'e90c1b6419da3bd812dd73bb3de40287a21abf153438147639ec5e20375ea93f'),
    'Linux': ('x86_64-unknown-linux-gnu', '936c246dfdbbfa7cb22dd01814a21f582a892689fae96b06071a5e433baffa22'),
}
LAUNCHER = '''"""Application launcher; the bundled interpreter also runs background workers."""
from pathlib import Path
import os
import sys
bundle = Path(__file__).resolve().parent
os.environ['JARVIS_PACKAGED'] = '1'
os.environ['JARVIS_RESOURCE_DIR'] = str(bundle)
os.environ['PYTHONPATH'] = str(bundle / 'app-source')
sys.path.insert(0, str(bundle / 'app-source'))
# pywin32's DLL directories must also be available in fresh worker processes.
if sys.platform == 'win32':
    sys.path.extend(str(bundle / 'runtime' / 'Lib' / 'site-packages' / name)
                    for name in ('win32', 'win32/lib', 'Pythonwin'))
from desktop import main
raise SystemExit(main())
'''


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def assemble(target):
    triplet, expected = TARGETS[target]
    work = ROOT / 'build' / ('portable-' + target.lower())
    work.mkdir(parents=True, exist_ok=True)
    bundle = work / 'JarvisAgent'
    if bundle.exists():
        raise SystemExit('Refusing to overwrite existing staging directory: ' + str(bundle))
    bundle.mkdir()
    archive = work / 'python-runtime.tar.gz'
    url = (f'https://github.com/astral-sh/python-build-standalone/releases/download/{PYTHON_RELEASE}/'
           f'cpython-{PYTHON}%2B{PYTHON_RELEASE}-{triplet}-install_only.tar.gz')
    print('Downloading pinned runtime:', target, flush=True)
    if not archive.exists() or sha256(archive) != expected:
        with urlopen(url, timeout=120) as response, archive.open('wb') as output:
            shutil.copyfileobj(response, output)
    if sha256(archive) != expected:
        raise SystemExit('Python runtime checksum mismatch')
    with tarfile.open(archive) as tar:
        # terminfo has case-distinct alias symlinks which cannot coexist on the
        # default macOS filesystem. The GUI runtime does not use terminal data.
        tar.extractall(work, members=[m for m in tar.getmembers()
                                     if '/share/terminfo' not in m.name], filter='data')
    (work / 'python').rename(bundle / 'runtime')
    archive.unlink()
    site = bundle / 'runtime' / ('Lib/site-packages' if target == 'Windows' else 'lib/python3.12/site-packages')
    print('Resolving and installing target dependencies:', triplet, flush=True)
    wheel_platform = 'x86_64-manylinux_2_39' if target == 'Linux' else triplet
    subprocess.run(['uv', 'pip', 'install', '--no-cache', '--python-version', '3.12',
                    '--python-platform', wheel_platform, '--target', str(site), '--link-mode', 'copy',
                    '-r', str(ROOT / 'requirements.txt'), 'setuptools<81'], check=True)
    selected = [p for p in sources(ROOT) if p.relative_to(ROOT).parts[0] not in {'tests', '.github', 'packaging'}]
    manifest = []
    for file in selected:
        name = file.relative_to(ROOT).as_posix()
        dest = bundle / 'app-source' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, dest)
        manifest.append(name)
    (bundle / 'app-manifest.json').write_text(json.dumps(manifest, indent=2))
    (bundle / 'launcher.py').write_text(LAUNCHER, encoding='utf-8')
    for name in ('LICENSE', 'THIRD_PARTY.md', 'README.he.md'):
        shutil.copy2(ROOT / name, bundle / name)
    if target == 'Windows':
        (bundle / 'Jarvis Agent.cmd').write_bytes(b'@echo off\r\ncd /d "%~dp0"\r\n"%~dp0runtime\\python.exe" "%~dp0launcher.py" %*\r\nif errorlevel 1 pause\r\n')
        # pywin32's .pth runs its bootstrap on every Python process.
        assert (site / 'pywin32.pth').exists(), 'Missing pywin32 worker bootstrap'
    else:
        launch = bundle / 'jarvis-agent'
        launch.write_text('#!/bin/sh\nset -eu\nHERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\nexec "$HERE/runtime/bin/python3.12" "$HERE/launcher.py" "$@"\n')
        launch.chmod(0o755)
        (bundle / 'install-desktop.sh').write_text('''#!/bin/sh
set -eu
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$DEST"
# Use a Python-generated desktop entry to escape spaces and desktop field codes.
"$HERE/runtime/bin/python3.12" - "$HERE" "$DEST" <<'PY'
from pathlib import Path
import sys
root, dest = map(Path, sys.argv[1:])
exe = str(root / 'jarvis-agent').replace('\\\\', '\\\\\\\\').replace('"', '\\\\"').replace('`', '\\\\`').replace('$', '\\\\$').replace('%', '%%')
(dest / 'jarvis-agent.desktop').write_text('[Desktop Entry]\\nType=Application\\nName=Jarvis Agent\\nExec="' + exe + '"\\nTerminal=false\\nCategories=Utility;Office;\\n')
PY
echo 'Jarvis Agent added to the applications menu.'
''')
        (bundle / 'install-desktop.sh').chmod(0o755)
    # Strip only disposable Python bytecode, not Qt resources or licenses.
    for folder in list(bundle.rglob('__pycache__')):
        shutil.rmtree(folder)
    distributions = sorted([{'name': d.metadata['Name'], 'version': d.version}
                            for d in importlib.metadata.distributions(path=[str(site)])], key=lambda d: d['name'].lower())
    (bundle / 'dependencies.json').write_text(json.dumps(distributions, indent=2))
    checks = verify(bundle, target)
    report = {'platform': target, 'architecture': 'x86_64', 'python': PYTHON,
              'runtime_source': url, 'runtime_sha256': expected, 'checks': checks,
              'os_execution_tested': False,
              'status': 'assembly verified; native OS execution not tested',
              'dependencies': distributions}
    (ROOT / 'release').mkdir(exist_ok=True)
    (ROOT / 'release' / f'assembly-{target.lower()}.json').write_text(json.dumps(report, indent=2))
    if not all(checks.values()):
        raise SystemExit('Assembly validation failed: ' + json.dumps(checks))
    print(json.dumps(checks), flush=True)
    return bundle


def verify(bundle, target):
    windows = target == 'Windows'
    runtime = bundle / 'runtime'
    executable = runtime / ('python.exe' if windows else 'bin/python3.12')
    site = runtime / ('Lib/site-packages' if windows else 'lib/python3.12/site-packages')
    header = executable.read_bytes()[:64]
    if windows:
        with executable.open('rb') as binary:
            binary.seek(int.from_bytes(header[60:64], 'little'))
            pe_header = binary.read(6)
        correct_arch = pe_header == b'PE\x00\x00\x64\x86'
    else:
        correct_arch = header[4:6] == b'\x02\x01' and header[18:20] == b'\x3e\x00'
    manifest = json.loads((bundle / 'app-manifest.json').read_text())
    forbidden = {'config.json', 'config/api_keys.json', 'viewer/graph-data.js'}
    checks = {
        'runtime_binary_format': header[:2] == b'MZ' if windows else header[:4] == b'\x7fELF',
        'runtime_x86_64': correct_arch,
        'source_manifest_complete': set(manifest) <= {p.relative_to(bundle/'app-source').as_posix()
                                                     for p in (bundle/'app-source').rglob('*') if p.is_file()},
        'no_private_configuration': not forbidden.intersection(manifest) and not any(name.startswith('notes/') for name in manifest),
        'qt_webengine': (site / 'PySide6' / ('QtWebEngineWidgets.pyd' if windows else 'QtWebEngineWidgets.abi3.so')).exists(),
        'qt_worker': any((site / 'PySide6').rglob('QtWebEngineProcess.exe' if windows else 'QtWebEngineProcess')),
        'audio_library': (site / 'sounddevice.py').exists(),
        'model_sdk': (site / 'google/genai/__init__.py').exists(),
        'task_queue': (bundle / 'app-source/core/codex_tasks.py').exists(),
        'launcher': (bundle / ('Jarvis Agent.cmd' if windows else 'jarvis-agent')).exists(),
    }
    wrong = ('macosx', 'manylinux', 'musllinux') if windows else ('macosx', 'win_amd64', 'win32')
    checks['no_foreign_platform_wheels'] = all(not any(word in wheel.read_text() for word in wrong)
                                               for wheel in site.glob('*.dist-info/WHEEL'))
    return checks


def package(bundle, target):
    out = ROOT / 'release'
    # Repackaging after an application change keeps the already downloaded
    # target runtime but always refreshes every allowlisted application file.
    source_dir = bundle / 'app-source'
    shutil.rmtree(source_dir)
    manifest = []
    for file in sources(ROOT):
        relative = file.relative_to(ROOT)
        if relative.parts[0] in {'tests','.github','packaging'}:continue
        dest = source_dir / relative
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,dest)
        manifest.append(relative.as_posix())
    (bundle/'app-manifest.json').write_text(json.dumps(manifest,indent=2))
    for name in ('LICENSE','THIRD_PARTY.md','README.he.md'):shutil.copy2(ROOT/name,bundle/name)
    report_path=out/f'assembly-{target.lower()}.json'
    report=json.loads(report_path.read_text())
    report['checks']=verify(bundle,target)
    report['source_sha256']={name:sha256(source_dir/name) for name in manifest}
    report_path.write_text(json.dumps(report,indent=2))
    if not all(report['checks'].values()):raise SystemExit('Refreshed assembly failed validation')
    if target == 'Windows':
        subprocess.run(['makensis', '-V2', '-DBUNDLE=' + str(bundle), '-DOUTPUT=' + str(out),
                        str(ROOT / 'packaging/windows-local.nsi')], check=True)
        output = out / f'Jarvis-Agent-{VERSION}-Windows-x64-portable.zip'
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for file in bundle.rglob('*'):
                if file.is_file(): archive.write(file, file.relative_to(bundle.parent))
    else:
        output = out / f'Jarvis-Agent-{VERSION}-Linux-x64.tar.gz'
        with tarfile.open(output, 'w:gz', compresslevel=6) as archive:
            archive.add(bundle, arcname='JarvisAgent')
    for path in out.iterdir():
        if path.is_file() and path.suffix != '.sha256':
            path.with_name(path.name + '.sha256').write_text(sha256(path) + '  ' + path.name + '\n')
    print('Created local distribution:', target, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', choices=TARGETS)
    parser.add_argument('--package-existing', action='store_true')
    args = parser.parse_args()
    bundle = ROOT / 'build' / ('portable-' + args.target.lower()) / 'JarvisAgent' if args.package_existing else assemble(args.target)
    if not args.package_existing and not all(verify(bundle, args.target).values()): raise SystemExit('Invalid staged bundle')
    package(bundle, args.target)
