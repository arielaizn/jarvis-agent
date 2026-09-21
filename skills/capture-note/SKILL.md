---
name: capture-note
description: Capture a thought into the second brain.
---

# Purpose
Capture a thought into the second brain.

# When to use
When the user naturally asks for capture note.

# Process and decision rules
Prepare a short title and preserve the thought in clean Markdown. Call create_note. The application displays a confirmation card. Wait for confirmation; never claim it is saved before execution. New notes go to Inbox/JARVIS without overwriting existing files.

# Preferred tools
Use only registered semantic tools. Reads are allowed; writes require the application confirmation gate.

# Output
Validated JSON with speech, title, state, typed cards and sources. Hebrew, 1-4 spoken sentences, address the user as אדוני.
