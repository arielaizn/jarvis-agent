# Jarvis Agent

Hebrew desktop assistant for macOS, Windows and Linux. Native Qt window, voice input and output, a 3D Markdown knowledge map, and server-owned AI task agents.

This preview contains locally built macOS Apple Silicon, Windows x64 and Linux x64 packages. The macOS app was launched and tested on macOS. Windows and Linux were assembled on macOS from target-specific Python runtimes and wheels, with structural checks; they have not been executed on those operating systems. Intel macOS is not included.

## Downloads

Get the application from [GitHub Releases](https://github.com/arielaizn/jarvis-agent/releases). The release includes checksums, a macOS runtime smoke report and separate Windows/Linux assembly reports. An assembly check does not establish that the application launches on its target OS.

- **macOS 14.2+ Apple Silicon**: download the arm64 DMG. Drag Jarvis Agent to Applications.
- **Windows 10/11 x64**: run the per-user Setup EXE, or extract the portable ZIP and launch `Jarvis Agent.cmd`.
- **Linux x64**: extract the TAR.GZ, run `./JarvisAgent/jarvis-agent`, and optionally run `./JarvisAgent/install-desktop.sh` to add it to the applications menu. Keep the extracted directory in place. Ubuntu 24.04+ with a graphical desktop is the intended target; install the system libraries listed below.

The initial packages are not notarized by Apple or signed with a Windows Authenticode certificate. The operating system may require explicit approval to open them. No signing certificates or API credentials are distributed.

## First start

1. Open Settings and configure your own Gemini API key for voice and vision. Keys stay in your local user-data directory.
2. Install and sign in to Codex CLI to use the default task brain: `gpt-6-astra`, reasoning `high`. The CLI is an external dependency; the desktop installer does not log in for you.
3. Enable the microphone deliberately when you want to speak. Screen and camera sharing also require explicit activation.
4. A clean installation starts with a private `notes` folder and one welcome note. To use another directory, set `notes_dir` in the user-data `config.json` before starting the local server.

Model availability, quotas and charges depend on your provider account. Requested model IDs are not silently replaced. Voice/vision use `gemini-3.8-live`; the configured alternate task provider is `gemini-3.8-flash`. Missing access is reported as an error.

## Voice and desktop presence

The microphone starts off. Completed speech is filtered before any acknowledgment or task: noise, fragments and background conversation are ignored. Saying “Jarvis” followed by a request is the immediate path. Natural requests without the name use a bounded TypeSafe judgment when your TypeSafe credential is configured; if that service is unavailable, say “Jarvis” explicitly. The filter cannot establish speaker identity from a transcript and is not voice authentication. Typed commands go directly to the task queue.

For a computer task naming a supported app, Jarvis activates its existing window and switches to a small floating companion. It shows elapsed task time and server-reported progress, with stop and restore controls. It stays clear of the pointer and follows the screen where you work; it does not intercept scrolling or pretend to know which control the agent is using. Double-click the card to reopen Jarvis. During an active focus session, its buttons control pause/resume, abort and retarget. Background research agents do not shrink the desktop window.

Use the **פנים**, **ליבה** and **חלונית עבודה** buttons for the animated portrait, orbital core and compact view. The microphone remains off until you turn it on.

## Parallel agents

Up to three workers and twelve accepted active/queued tasks. Choose **סוכן רקע** or say **סוכן רקע: ...** for an independent analysis/research agent. Background Codex workers have no shell or configured desktop MCP tools. Gemini background workers have no action tools.

Computer and file-modification tasks retain the configured action tools and share one execution queue. Each task has its own progress, result and cancellation control. A provider change stops active jobs before switching. Codex quota fallback does not replay a request that has already started using tools.

## Platform capabilities

| Capability | macOS | Windows | Linux |
| --- | --- | --- | --- |
| Native desktop UI, settings, notes, task queue | Runtime smoke-tested | Packaged; OS test pending | Packaged; OS test pending |
| Microphone, audio and explicit screen/camera sharing | Subject to OS permissions and devices | Subject to OS permissions and devices | Subject to desktop/portal support and devices |
| Codex task tools | External authenticated CLI required | External authenticated CLI required | External authenticated CLI required |
| Focus foreground app + Chrome host tracking | Native macOS integration | Not yet supported | Not yet supported |
| DaVinci Resolve / editor scripting adapters | Application-specific setup required | Adapter support varies | Adapter support varies |
| Browser-use automation | Optional separate Python environment and browser required | Optional separate Python environment and browser required | Optional separate Python environment and browser required |

The browser-use integration keeps its dependency environment separate; see `requirements-browser.txt` and integration settings. OS-specific integrations report unavailable status where they cannot run. These packages do not grant OS permissions automatically.

## Private data locations

- macOS: `~/Library/Application Support/Jarvis Agent`
- Windows: `%LOCALAPPDATA%\Jarvis Agent`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/jarvis-agent`

`JARVIS_DATA_DIR` overrides the location for isolated tests. Source checkouts retain their existing project-local configuration. Installers and source exports omit API keys, conversation memory, notes, graph indexes, screenshots, logs and machine-specific integration settings.

## Build and verify

Use Python 3.12 on the target operating system:

```sh
python -m pip install -r requirements-build.txt
python -m PyInstaller --clean --noconfirm packaging/JarvisAgent.spec
python packaging/smoke.py
python packaging/package.py
```

Linux needs a graphical display; CI runs the smoke test with `xvfb-run`. The smoke test starts the actual packaged executable with isolated state, renders a native window and exercises the real local HTTP server. It does not claim that an unconfigured API key, model, microphone or external editor works.

For the configured live application, run `python preflight.py`. It makes real provider calls and checks notes capture, vision, voice, parallel agents, file execution, served files and configuration privacy. Any failed chain yields a non-zero exit; missing quota is a failure, not a successful skip.

For local cross-platform assembly, install `uv` and (for Windows) `makensis`, then run:

```sh
python packaging/portable.py Windows
python packaging/portable.py Linux
```

These commands download hash-pinned CPython 3.12 runtimes from [python-build-standalone](https://github.com/astral-sh/python-build-standalone), resolve OS-specific dependencies, and produce an NSIS installer/portable ZIP or a Linux TAR.GZ. They never claim to execute the foreign applications. Each bundle includes the application source and dependency licenses. Linux runtime dependencies on Ubuntu 24.04:

```sh
sudo apt-get install libportaudio2 libegl1 libopengl0 libnss3 libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 libxcb-render-util0 libxcb-image0 libasound2t64
```

Wayland can restrict desktop automation; use an X11 session for Xlib-based actions. Playwright browser binaries are an optional separate download. The native build workflow in `.github/workflows/desktop.yml` runs only when manually requested. Published preview binaries are built locally and uploaded to Releases.

## Attribution and license

Derived from **MARK LIV / JARVIS by FatihMakes**. The upstream attribution and **CC BY-NC 4.0** license are preserved in `LICENSE`; commercial use is not granted. This fork adds Hebrew workflows, knowledge/focus tools, Codex integration, parallel task management and desktop packaging. See `UPSTREAM.md` for the original documentation and `THIRD_PARTY.md` for dependency notices.
