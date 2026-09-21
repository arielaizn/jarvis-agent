# Jarvis Agent

Hebrew desktop assistant for macOS, Windows and Linux. Native Qt window, voice input and output, a 3D Markdown knowledge map, and server-owned AI task agents.

This preview release currently provides the locally verified macOS Apple Silicon package. Windows, Linux and Intel macOS packages remain pending successful CI builds. The source and build definitions for all platforms are included.

## Downloads

Get the application from [GitHub Releases](https://github.com/arielaizn/jarvis-agent/releases). Each platform is built and smoke-tested on its own operating system. The release includes checksums and machine-readable smoke-test results.

- **macOS 13+**: choose the Apple Silicon (arm64) or Intel (x64) DMG. Drag Jarvis Agent to Applications.
- **Windows 10/11 x64**: run the per-user Setup EXE, or extract the portable ZIP and launch `JarvisAgent.exe`.
- **Linux x64**: Ubuntu 24.04+ DEB, or extract the TAR.GZ and run `JarvisAgent`. A graphical desktop and the system Qt/Chromium dependencies listed in the package control file are required.

The initial packages are not notarized by Apple or signed with a Windows Authenticode certificate. The operating system may require explicit approval to open them. No signing certificates or API credentials are distributed.

## First start

1. Open Settings and configure your own Gemini API key for voice and vision. Keys stay in your local user-data directory.
2. Install and sign in to Codex CLI to use the default task brain: `gpt-6-astra`, reasoning `high`. The CLI is an external dependency; the desktop installer does not log in for you.
3. Enable the microphone deliberately when you want to speak. Screen and camera sharing also require explicit activation.
4. A clean installation starts with a private `notes` folder and one welcome note. To use another directory, set `notes_dir` in the user-data `config.json` before starting the local server.

Model availability, quotas and charges depend on your provider account. Requested model IDs are not silently replaced. Voice/vision use `gemini-3.8-live`; the configured alternate task provider is `gemini-3.8-flash`. Missing access is reported as an error.

## Parallel agents

Up to three workers and twelve accepted active/queued tasks. Choose **סוכן רקע** or say **סוכן רקע: ...** for an independent analysis/research agent. Background Codex workers have no shell or configured desktop MCP tools. Gemini background workers have no action tools.

Computer and file-modification tasks retain the configured action tools and share one execution queue. Each task has its own progress, result and cancellation control. A provider change stops active jobs before switching. Codex quota fallback does not replay a request that has already started using tools.

## Platform capabilities

| Capability | macOS | Windows | Linux |
| --- | --- | --- | --- |
| Native desktop UI, settings, notes, task queue | Yes | Yes | Yes |
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
python -m PyInstaller --noconfirm packaging/JarvisAgent.spec
python packaging/smoke.py
python packaging/package.py
```

Linux needs a graphical display; CI runs the smoke test with `xvfb-run`. The smoke test starts the actual packaged executable with isolated state, renders a native window and exercises the real local HTTP server. It does not claim that an unconfigured API key, model, microphone or external editor works.

For the configured live application, run `python preflight.py`. It makes real provider calls and checks notes capture, vision, voice, parallel agents, file execution, served files and configuration privacy. Any failed chain yields a non-zero exit; missing quota is a failure, not a successful skip.

Build workflow: `.github/workflows/desktop.yml`. Tagged releases publish only after all platform builds and package smoke tests succeed.

## Attribution and license

Derived from **MARK LIV / JARVIS by FatihMakes**. The upstream attribution and **CC BY-NC 4.0** license are preserved in `LICENSE`; commercial use is not granted. This fork adds Hebrew workflows, knowledge/focus tools, Codex integration, parallel task management and desktop packaging. See `UPSTREAM.md` for the original documentation and `THIRD_PARTY.md` for dependency notices.
