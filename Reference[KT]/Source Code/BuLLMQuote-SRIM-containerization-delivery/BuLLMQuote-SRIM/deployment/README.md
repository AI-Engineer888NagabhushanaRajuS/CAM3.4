# deployment/

Placeholder — not yet populated.

There is currently no dedicated deployment tooling; the live system is
orchestrated by `manage_backend.py` inside
`C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\`, which hardcodes
paths to every service (backend scripts, the accomplish-ui frontend, Superset).
A real `deployment/` setup (Docker, install scripts, service orchestration)
that doesn't depend on those hardcoded paths is deferred to a follow-up pass.
