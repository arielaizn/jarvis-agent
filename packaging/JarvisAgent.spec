# Explicit source manifest: no developer configuration or note indexes in binaries.
from pathlib import Path
import sys, json, importlib.util
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
root=Path(SPECPATH).parent
spec=importlib.util.spec_from_file_location('export_source',root/'packaging/export_source.py')
export=importlib.util.module_from_spec(spec);spec.loader.exec_module(export)
files=[p for p in export.sources(root) if p.relative_to(root).parts[0] not in {'tests','.github','packaging'}]
manifest=root/'build'/'app-manifest.json';manifest.parent.mkdir(exist_ok=True)
manifest.write_text(json.dumps([p.relative_to(root).as_posix() for p in files]))
datas=[(str(p), 'app-source/'+p.relative_to(root).parent.as_posix()) for p in files]
datas.append((str(manifest),'.'))
# Dynamic action/plugin discovery and module-dispatched worker processes.
hidden=['main','ui','server','build','preflight']
for package in ('core','actions','memory','dashboard','plugins','google.genai'):
    hidden+=collect_submodules(package, on_error='warn once')
datas+=collect_data_files('certifi')
datas+=collect_data_files('PySide6', includes=['**/LICENSE*','**/licenses/*'])
a=Analysis([str(root/'desktop.py')],pathex=[str(root)],binaries=[],datas=datas,hiddenimports=hidden,
           hookspath=[],runtime_hooks=[],excludes=['PyQt6','PyQt5','PySide2','tkinter','torch','tensorflow','pytest','sklearn','scipy','pandas','matplotlib','IPython','notebook'])
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
