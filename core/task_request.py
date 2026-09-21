"""Explicit voice controls for task mode; ambiguous requests retain desktop ordering."""
import re

BACKGROUND_PREFIX = re.compile(r'^(?:סוכן\s+רקע|משימת\s+רקע|background\s+(?:agent|task))\s*[:،,\-]?\s+', re.I)


def task_request(question, mode=None):
    match = BACKGROUND_PREFIX.match(question)
    if match and mode is None:
        return question[match.end():].strip(), 'background'
    return question, mode or 'computer'
