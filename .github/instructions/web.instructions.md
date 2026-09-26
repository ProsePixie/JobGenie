---
applyTo: "web/**"
---
`web/server.py` is stdlib `http.server`, bound to 127.0.0.1, with Host and same-origin
checks on every request. Keep them. Every file path must pass `inside_project`. New
POST routes go in `ROUTES_POST` and `ACTION_NAMES` (the app log). The log records what
was done, never posting text or career data. `web/ui.html` is one file of plain JS:
no frameworks, no build step, no external scripts.
