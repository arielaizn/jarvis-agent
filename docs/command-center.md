# Command center integration

The new UI is a Next.js/React/TypeScript static export in `viewer/command`.
Python serves it at `/`; `/index.html` retains the original knowledge galaxy.
The desktop embeds the same origin. Hash navigation preserves voice/session
state. Node, npm and a web build are not required for installed desktop users.

Development: `cd web && npm ci && npm run build`. Start the Python desktop,
then `npm start` in `web` for the optional localhost:3000 entry point. The Node
HTTP adapter only proxies the fixed loopback backend and validates Host and
Origin. This reuses the Python engine instead of duplicating execution and
credential handling in a second backend.

`core/command_center.py` supplies a bounded semantic registry, short server-side
conversation history, typed activity events and one-use expiring confirmations.
Codex/Claude are planners in this lane, with shell and external MCP tools disabled.
The application executes only named wrappers. Existing explicitly selected
computer tasks retain the user's separately configured desktop permissions.

Google tools require an installed, authenticated GWS CLI. Merely finding the
executable never marks Google verified. This machine currently needs GWS OAuth
setup. The shipped interfaces do not claim email/calendar demo success until
real authorized calls pass. Google document reads support Google Docs exports and bounded textual Drive files.

ElevenLabs is an optional web voice provider configured privately in
`config/command-center.json`. Neither keys nor this file are served. The browser
records only after the ear button, uses local silence detection, and interrupts
playback on a new utterance. Audio is transcribed by Scribe v2. The TTS stream is
buffered by the current server adapter into an audio response; incremental network
playback is not implemented. Native microphone capture retains the existing
Gemini transport and explicit physical ear button. Gemini remains the default
voice and fresh-screen model. ElevenLabs requires a key and voice ID to test live.

HOLO is a pinned local copy under `viewer/holo`, with no automatic camera start.
Its built-in synthetic probe and the original focus probe must be run in a visible
1440x900 browser, with `mute=1`. A passing synthetic gesture probe is not a test
of a real user's camera, lighting or hand tracking.

Verification artifacts stay private under `.artifacts/command-center`. Public
source export excludes credentials, personal notes, graph data and debug artifacts.
