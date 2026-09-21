# Explicit source manifest: no developer configuration or note indexes in binaries.
from pathlib import Path
import sys, json, importlib.util
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
root=Path(SPECPATH).parent
clone_spec=importlib.util.spec_from_file_location('apfs_copy',root/'packaging/apfs_copy.py')
clone_module=importlib.util.module_from_spec(clone_spec);clone_spec.loader.exec_module(clone_module);clone_module.install()
spec=importlib.util.spec_from_file_location('export_source',root/'packaging/export_source.py')
export=importlib.util.module_from_spec(spec);spec.loader.exec_module(export)
files=[p for p in export.sources(root) if p.relative_to(root).parts[0] not in {'tests','.github','packaging'}]
manifest=root/'build'/'app-manifest.json';manifest.parent.mkdir(exist_ok=True)
manifest.write_text(json.dumps([p.relative_to(root).as_posix() for p in files]))
datas=[(str(p), 'app-source/'+p.relative_to(root).parent.as_posix()) for p in files]
datas.append((str(manifest),'.'))
if sys.platform=='darwin':
    import subprocess
    native=root/'build'/'focus-surface'
    subprocess.run(['/usr/bin/swiftc',str(root/'scripts/focus_surface.swift'),'-o',str(native)],check=True)
    datas.append((str(native),'native'))
# Dynamic action/plugin discovery and module-dispatched worker processes.
hidden=['main','ui','server','build','preflight']
for package in ('core','actions','memory','dashboard','plugins','google.genai'):
    hidden+=collect_submodules(package, on_error='warn once')
datas+=collect_data_files('certifi')
datas+=collect_data_files('PySide6', includes=['**/LICENSE*','**/licenses/*'])
a=Analysis([str(root/'desktop.py')],pathex=[str(root)],binaries=[],datas=datas,hiddenimports=hidden,
           hookspath=[],runtime_hooks=[],excludes=['PyQt6','PyQt5','PySide2','tkinter','torch','tensorflow','pytest','sklearn','scipy','pandas','matplotlib','IPython','notebook'])
# Some Qt wheels contain a non-version Resources directory under Versions.
# PyInstaller may select it as the framework version; Qt resolves Current -> A.
if sys.platform == 'darwin':
    wrong = 'QtWebEngineCore.framework/Versions/Resources/'
    correct = 'QtWebEngineCore.framework/Versions/A/'
    a.datas = [(dest.replace(wrong, correct), source, kind) for dest, source, kind in a.datas]
    a.binaries = [(dest.replace(wrong, correct), source, kind) for dest, source, kind in a.binaries]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='JarvisAgent',debug=False,bootloader_ignore_signals=False,
        strip=False,upx=False,console=False,icon=str(root/'config/jarvis.ico'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='JarvisAgent')
if sys.platform=='darwin':
    app=BUNDLE(coll,name='Jarvis Agent.app',icon=str(root/'config/jarvis.ico'),bundle_identifier='ai.jarvisagent.desktop',
        info_plist={'CFBundleShortVersionString':'1.0.0','CFBundleVersion':'1',
                    'NSMicrophoneUsageDescription':'Jarvis uses the microphone only when you turn on voice input.',
                    'NSCameraUsageDescription':'Jarvis uses the camera only when you enable it.',
                    'NSAppleEventsUsageDescription':'Jarvis controls applications when you request a task.',
                    'NSHighResolutionCapable':True})

    signer_spec=importlib.util.spec_from_file_location('sign_macos',root/'packaging/sign_macos.py')
    signer=importlib.util.module_from_spec(signer_spec);signer_spec.loader.exec_module(signer)
    signer.sign(app.name)
