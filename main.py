"""Snipe-IT Device Onboarding — Web Application.

Compatibility entry point. The application now lives in the `app/` package
(see `app/main.py:create_app`). Keep running it exactly as before:

    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8080 --reload

Attribute access is forwarded lazily (PEP 562) to `app.main`, so
`main.app`, `main.current_user`, `main.oauth`, ... always resolve to the
current objects even across module reloads in tests.
"""

import app.main as _app_main


def __getattr__(name):
    return getattr(_app_main, name)
