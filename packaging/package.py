"""Create native distributables from the already smoke-tested frozen app."""
from pathlib import Path
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'release';OUT.mkdir(exist_ok=True)
VERSION='1.0.0'
ARCH='arm64' if platform.machine().lower() in {'arm64','aarch64'} else 'x64'

if sys.platform=='darwin':
    from apfs_copy import install
    install()
    app=ROOT/'dist'/'Jarvis Agent.app'
    if '--zip' in sys.argv:
        target=OUT/f'Jarvis-Agent-{VERSION}-macOS-{ARCH}.zip'
        subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(target)],check=True)
        with zipfile.ZipFile(target) as archive:
            if archive.testzip() is not None:raise RuntimeError('macOS archive checksum failed')
    else:
        stage=ROOT/'build'/'dmg';stage.mkdir(exist_ok=True)
        link=stage/'Applications'
        if not link.exists():link.symlink_to('/Applications')
        shutil.copytree(app,stage/app.name,symlinks=True,dirs_exist_ok=True)
        target=OUT/f'Jarvis-Agent-{VERSION}-macOS-{ARCH}.dmg'
        subprocess.run(['hdiutil','create','-volname','Jarvis Agent','-srcfolder',str(stage),'-ov','-format','UDZO',str(target)],check=True)
        subprocess.run(['hdiutil','verify',str(target)],check=True)
elif sys.platform=='win32':
    subprocess.run(['iscc','packaging/windows.iss'],cwd=ROOT,check=True)
    with zipfile.ZipFile(OUT/f'Jarvis-Agent-{VERSION}-Windows-{ARCH}-portable.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for file in (ROOT/'dist'/'JarvisAgent').rglob('*'):
            if file.is_file():archive.write(file,file.relative_to(ROOT/'dist'))
else:
    bundle=ROOT/'dist'/'JarvisAgent'
    with tarfile.open(OUT/f'Jarvis-Agent-{VERSION}-Linux-{ARCH}.tar.gz','w:gz') as archive:
        archive.add(bundle,arcname='JarvisAgent')
    deb=ROOT/'build'/'deb';(deb/'DEBIAN').mkdir(parents=True,exist_ok=True)
    target=deb/'opt'/'jarvis-agent';shutil.copytree(bundle,target,symlinks=True,dirs_exist_ok=True)
    (deb/'DEBIAN'/'control').write_text('Package: jarvis-agent\nVersion: '+VERSION+'\nSection: utils\nPriority: optional\nArchitecture: amd64\nMaintainer: Jarvis Agent contributors\nDepends: libnss3, libegl1, libopengl0, libxcb-cursor0, libxkbcommon-x11-0, libasound2t64, libportaudio2\nDescription: Hebrew desktop AI assistant with voice, notes and parallel task agents\n')
    applications=deb/'usr/share/applications';applications.mkdir(parents=True,exist_ok=True)
    (applications/'jarvis-agent.desktop').write_text('[Desktop Entry]\nType=Application\nName=Jarvis Agent\nExec=/opt/jarvis-agent/JarvisAgent\nTerminal=false\nCategories=Utility;Office;\nStartupWMClass=JarvisAgent\n')
    subprocess.run(['dpkg-deb','--build','--root-owner-group',str(deb),str(OUT/f'Jarvis-Agent-{VERSION}-Linux-{ARCH}.deb')],check=True)
for file in OUT.iterdir():
    if file.is_file() and file.suffix!='.sha256':
        digest=hashlib.sha256(file.read_bytes()).hexdigest()
        file.with_name(file.name+'.sha256').write_text(digest+'  '+file.name+'\n')
print('Packaged',sys.platform,ARCH)
