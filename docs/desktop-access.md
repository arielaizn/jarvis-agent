# Desktop access and first run

The desktop requests configuration on its first launch, immediately after installation when launched. The native setup records completion once per user profile. Closing without saving leaves setup pending. Settings > Computer access can reopen it later, and live checks still detect revoked permissions.

Full computer access is an explicit native setting. It changes Codex from workspace-write to danger-full-access for computer tasks only. Background research remains read-only. OS permissions, provider authentication and installed dependencies are independent of that setting. The command center shows them separately.

On macOS, the dialog opens the Accessibility, Full Disk Access, Automation and Screen Recording panes. It requests microphone/camera permission without opening capture devices. System Settings may require the user to add the installed app, approve each target application, and restart. Full Disk Access has no public preflight API; the UI reports manual verification instead of testing protected private files. Apple may request permission again following revocation or an unsigned application update. Production signing/notarization is still required for trusted distribution.

Windows uses fixed privacy Settings URLs and ordinary user filesystem permissions; there is no universal desktop approval for all files or applications. Linux access depends on the login session, display server and screen-sharing portal. The setup does not elevate to administrator/root or bypass OS restrictions.

Computer tasks expose a bundled `jarvis_computer` stdio MCP adapter with browser, file, application and desktop actions. A full-access check occurs on every call. It is disabled in restricted mode and does not depend on the developer's installed MCP plugins. Tools can still report missing browsers, dependencies or OS permissions. Codex CLI must be installed and authenticated separately, or Gemini must be configured.

The automatic route sends explicit app/file operations to the computer queue. Unclear routing uses a bounded TypeSafe choice with a no-match outcome; it cannot modify permissions. Capability questions return current settings rather than asking the note planner to speculate about access.

## Verification

- Native Qt window, muted microphone, rendered frontend and permission dialog.
- Live stdio MCP discovery plus actual create/read file and browser discovery.
- Fresh-profile setup persistence, revocation and fixed settings destinations tested.
- OS prompts still require a person; opening a pane is not evidence of granting access.
