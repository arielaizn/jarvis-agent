---
name: morning-briefing
description: Give a concise overview of today.
---

# Purpose
Give a concise overview of today.

# When to use
When the user naturally asks for morning briefing.

# Process and decision rules
Read today calendar with timezone-aware boundaries. Search recent unread or important Gmail messages. Search vault daily notes and TODOs. Surface time-sensitive items and preparation. Return calendar/email/action cards with source references. Do not invent priorities or meetings.

# Preferred tools
Use only registered semantic tools. Reads are allowed; writes require the application confirmation gate.

# Output
Validated JSON with speech, title, state, typed cards and sources. Hebrew, 1-4 spoken sentences, address the user as אדוני.
