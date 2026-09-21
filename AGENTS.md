# TypeSafe in Jarvis

For work in this project that benefits from semantic judgments, read
`.agents/skills/typesafe-ai/SKILL.md` and its relevant current official docs.
Use TypeSafe for bounded routing, ranking, extraction and verification decisions.
Keep deterministic rules in code and preserve the requested task scope.

Jarvis task sessions expose the `jarvis_typesafe` MCP server and its
`typesafe_evaluate` tool. Supply only the state needed for the judgment; do not
upload notes, screenshots or files unrelated to the user's task. Include an
explicit no-match option when appropriate. Probabilities never authorize actions.
The tool reads its credential privately; never read or print the credential file.
For local development, `python -m core.typesafe_client` accepts the same
`{"state": ..., "questions": ...}` JSON on stdin.

Codex GPT 6 Astra with high reasoning remains Jarvis's main task model.
Run `preflight.py` before declaring a Jarvis change complete. Preserve inherited
Hebrew writing rules and run the human voice checker for user-facing text.
