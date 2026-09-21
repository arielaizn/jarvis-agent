---
name: meeting-prep
description: Prepare the user for the next or named meeting.
---

# Purpose
Prepare the user for the next or named meeting.

# When to use
When the user naturally asks for meeting prep.

# Process and decision rules
Find the event using get_calendar_events. Identify attendees, company and topic. Search Gmail for recent relevant correspondence; read messages. Search vault for previous meeting notes and read them. Search Drive when useful. Rank changes, commitments, open issues and decisions. Return a short spoken briefing, meeting/insight/action cards and sources. If Google is unavailable, say which context is missing.

# Preferred tools
Use only registered semantic tools. Reads are allowed; writes require the application confirmation gate.

# Output
Validated JSON with speech, title, state, typed cards and sources. Hebrew, 1-4 spoken sentences, address the user as אדוני.
