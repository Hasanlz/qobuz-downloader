# 01 — UI screens

Status: ready-for-human

Login (email/token, remember-me, logout), main screen with Queue/Search/Log
tabs, settings modal (naming templates, lyrics toggle), toasts, search spinner,
teardown-safe event handling. Implemented in `tui/src/quaver/app.py` and
`tui/src/quaver/login.py`.

## Comments

- Verified via Textual Pilot tests (`tui/tests/`) and raw-PTY checks (pyte
  renders): login navigation, paste/edit keys, Ctrl+C quit, logout flow.
