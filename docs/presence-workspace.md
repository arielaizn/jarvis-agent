# Presence workspace

The command screen is a face and a single input bar. The menu discloses existing tools; the knowledge view keeps a small face beside note sources. The old native controls are available from settings, not duplicated above the web shell.

Microphone capture remains off at startup. The first-party ear button calls the native Qt permission gate and reports its real state. Camera organs never enable the microphone. Test URLs use `?mute=1`.

Voice input uses local PCM activity detection, 256 ms pre-roll and 650 ms silence before `activityEnd`. Gemini Live's automatic activity detection is disabled: in live reproduction it accepted PCM without producing an input transcript. Explicit start/end events restored transcripts. The address filter still runs before any acknowledgment or task.

Native output workers send numeric mouth frames over private stdout, paced by output writes. The face consumes those frames only while speaking; silence and cancellation close the mouth. This is audio-derived articulation, not phoneme-perfect alignment. The fixed acknowledgment has its own playback-clock envelope. Browser output uses its actual audio analyser.

Eyes follow the pointer. With explicit camera activation, local face landmarks supply an ephemeral gaze target. These coordinates are not included in posture HTTP requests, notes or the ledger. Camera activation and screen sharing remain separate.

Desktop startup no longer attempts privileged firewall changes. The existing phone dashboard can run under the user's existing network policy; manual network administration is separate from launching the assistant. Jarvis never stores a macOS account password.

Validation: `preflight.py` now includes `/preflight/voice-input`, which streams the bundled generic cue through the same activity detector and Gemini Live configuration. It never opens a microphone or stores a transcript. `tests/test_presence.py` covers boundaries, silence and startup elevation.
