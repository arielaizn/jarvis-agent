"""Allowlisted source export. Never recursively copy a developer's workspace."""
from pathlib import Path
import argparse
import shutil

ROOT_FILES = {'main.py','ui.py','server.py','desktop.py','build.py','preflight.py','setup.py',
              'requirements.txt','requirements-browser.txt','requirements-build.txt','config.example.json',
              'LICENSE','THIRD_PARTY.md','UPSTREAM.md','readme.md','README.he.md','README.md','.gitignore','AGENTS.md',
              'start.command','install.command','skills-lock.json'}
TREES = {'core','actions','memory','plugins','dashboard','viewer','web','skills','docs','tests','scripts','packaging','.github', '.agents/skills/typesafe-ai'}
SUFFIXES = {'.obj','.svg','.woff','.woff2','.py','.js','.mjs','.ts','.tsx','.wasm','.task','.glb','.html','.css','.txt','.md','.toml','.swift','.yml','.yaml','.spec','.in','.iss','.nsi','.desktop','.plist','.sh','.ps1'}


def sources(root):
    # Enumerate actual directory entries: on macOS README.md and readme.md may
    # refer to one file. A Linux manifest must never contain a phantom alias.
    result = [p for p in root.iterdir() if p.name in ROOT_FILES and p.is_file() and not p.is_symlink()]
    for name in TREES:
        base = root / name
        if not base.exists(): continue
        for p in base.rglob('*'):
            if p.is_symlink() or not p.is_file() or any(part in {'__pycache__','node_modules','.git','.next','out'} for part in p.parts): continue
            if p.suffix not in SUFFIXES or p.name == 'graph-data.js': continue
            result.append(p)
    for name in ('config/jarvis.ico','tests/fixtures/preflight.jpg','web/package.json','web/package-lock.json','web/tsconfig.json','viewer/holo/LICENSE'):
        if (root / name).is_file(): result.append(root / name)
    return sorted(set(result))


def export(root, destination):
    destination.mkdir(parents=True, exist_ok=True)
    count=0
    for source in sources(root):
        target=destination/source.relative_to(root)
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);count+=1
    print('Exported',count,'source files; no runtime credentials, notes, logs or graph data')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('destination',type=Path);parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);args=parser.parse_args()
    export(args.root.resolve(),args.destination.resolve())
