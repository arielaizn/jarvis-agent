# Third-party notices

The application is derived from MARK LIV / JARVIS, Copyright (c) 2026 FatihMakes, under CC BY-NC 4.0. See LICENSE. Changes in this repository do not remove the original attribution or noncommercial condition.

Desktop builds use **PySide6 / Qt for Python** in place of PyQt. PySide6 and the applicable Qt libraries are dynamically linked. Qt for Python is available under LGPLv3/GPLv3 and commercial licenses; individual bundled Qt and Chromium components have their own notices. The open-source license files supplied by the installed PySide6 wheels are retained in the package. Qt source and license information: https://doc.qt.io/qtforpython-6/licenses.html and https://code.qt.io/ . Users may replace the LGPL shared libraries with compatible modified versions; reverse engineering necessary to debug those modifications is not prohibited by this application's license notice.

The build uses PyInstaller with its distribution exception: https://pyinstaller.org/en/stable/license.html . Python and other packages retain their upstream licenses. Locally assembled Windows/Linux bundles include dependencies.json with the installed versions. Their CPython runtime comes from python-build-standalone (https://github.com/astral-sh/python-build-standalone), with the upstream Python license retained. The source is available in this repository; dependency source is available from its upstream project/package distribution.

The 3D viewer loads 3d-force-graph from jsDelivr. Its source and MIT license are available at https://github.com/vasturiano/3d-force-graph . TypeSafe skill content preserves its own license and attribution under `.agents/skills/typesafe-ai`.

No ownership of upstream software, model names, trademarks or external editor products is claimed.

## HOLO gestures

`viewer/holo/` derives from https://github.com/zubair-trabzada/holo-gestures
at commit 55626ff00f6b49c649a407ffdb3cad174479c637. Original MIT license is
preserved in `viewer/holo/LICENSE`. Local changes scope its URLs, connect the
Jarvis note index, make camera activation explicit, and honor muted test pages.
MediaPipe Tasks Vision is Apache-2.0; three.js and GLTFLoader are MIT.
The Apollo 11 and Triceratops models are Smithsonian CC0 digitizations.
The upstream HOLO SHIM in both MediaPipe WASM loaders is preserved.

## Command center

The `web/` source uses Next.js, React, TypeScript, Tailwind, Framer Motion,
Lucide and Zod. Dependency versions are locked in `web/package-lock.json`.
Desktop packages serve the static export; Node is required only to develop or
rebuild this frontend. The existing Python application remains the local API
and desktop execution engine.
