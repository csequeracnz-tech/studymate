from __future__ import annotations

import base64
import hashlib
import hmac
import os
import shlex
import threading
import time
import secrets
from collections import defaultdict, deque
from pathlib import Path

from fastapi import Request
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse, RedirectResponse


AUTH_FILE = Path.home() / ".config" / "studymate" / "auth.env"


def load_auth_config() -> dict[str, str]:
    if not AUTH_FILE.exists():
        raise RuntimeError(
            f"StudyMate auth configuration not found: {AUTH_FILE}"
        )

    values = {}

    for raw_line in AUTH_FILE.read_text().splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        key, separator, value = line.partition("=")

        if not separator:
            continue

        parsed = shlex.split(value)

        values[key.strip()] = (
            parsed[0] if parsed else ""
        )

    required = [
        "STUDYMATE_USERNAME",
        "STUDYMATE_PASSWORD_SALT",
        "STUDYMATE_PASSWORD_HASH",
        "STUDYMATE_SESSION_SECRET",
    ]

    missing = [
        key for key in required
        if not values.get(key)
    ]

    if missing:
        raise RuntimeError(
            "Missing StudyMate auth settings: "
            + ", ".join(missing)
        )

    return values


AUTH = load_auth_config()


# Login brute-force protection.
#
# This is intentionally small and in-memory because StudyMate currently
# runs as a single Uvicorn application for one user. Failed-attempt state
# resets when the application restarts.
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 10 * 60
LOGIN_LOCKOUT_SECONDS = 15 * 60

_login_failures: dict[str, deque[float]] = defaultdict(deque)
_login_lockouts: dict[str, float] = {}
_login_lock = threading.Lock()


def get_login_client_key(request: Request) -> str:
    # Do not trust X-Forwarded-For yet. Once StudyMate is behind our
    # controlled HTTPS reverse proxy, proxy handling will be configured
    # explicitly.
    if request.client and request.client.host:
        return request.client.host

    return "unknown"


def login_retry_after(client_key: str) -> int:
    now = time.monotonic()

    with _login_lock:
        locked_until = _login_lockouts.get(client_key)

        if locked_until:
            if locked_until > now:
                return max(1, int(locked_until - now) + 1)

            _login_lockouts.pop(client_key, None)

        failures = _login_failures.get(client_key)

        if failures:
            cutoff = now - LOGIN_WINDOW_SECONDS

            while failures and failures[0] < cutoff:
                failures.popleft()

            if not failures:
                _login_failures.pop(client_key, None)

    return 0


def record_login_failure(client_key: str) -> int:
    now = time.monotonic()

    with _login_lock:
        failures = _login_failures[client_key]
        cutoff = now - LOGIN_WINDOW_SECONDS

        while failures and failures[0] < cutoff:
            failures.popleft()

        failures.append(now)

        if len(failures) >= LOGIN_MAX_FAILURES:
            locked_until = now + LOGIN_LOCKOUT_SECONDS
            _login_lockouts[client_key] = locked_until
            failures.clear()
            return LOGIN_LOCKOUT_SECONDS

    return 0


def clear_login_failures(client_key: str) -> None:
    with _login_lock:
        _login_failures.pop(client_key, None)
        _login_lockouts.pop(client_key, None)


def verify_credentials(
    username: str,
    password: str,
) -> bool:
    username_ok = hmac.compare_digest(
        username.strip().lower(),
        AUTH["STUDYMATE_USERNAME"].strip().lower(),
    )

    try:
        salt = base64.b64decode(
            AUTH["STUDYMATE_PASSWORD_SALT"]
        )

        expected = base64.b64decode(
            AUTH["STUDYMATE_PASSWORD_HASH"]
        )
    except Exception:
        return False

    actual = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )

    password_ok = hmac.compare_digest(
        actual,
        expected,
    )

    return username_ok and password_ok


def add_session_middleware(app) -> None:
    app.add_middleware(
        SessionMiddleware,
        secret_key=AUTH["STUDYMATE_SESSION_SECRET"],
        session_cookie="studymate_session",
        max_age=60 * 60 * 24 * 30,
        same_site="lax",

        # StudyMate is served to clients exclusively through
        # HTTPS deployment.
        https_only=True,
    )


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_or_create_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")

    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token

    return token


def install_csrf_middleware(app) -> None:
    @app.middleware("http")
    async def csrf_protection(
        request: Request,
        call_next,
    ):
        if request.method in SAFE_METHODS:
            return await call_next(request)

        path = request.url.path

        # Login cannot use the authenticated session CSRF token yet.
        # Require browser submissions to originate from this host.
        if path == "/login":
            origin = request.headers.get("origin")

            if origin:
                try:
                    from urllib.parse import urlparse

                    origin_host = urlparse(origin).netloc
                    request_host = request.headers.get("host", "")

                    if not hmac.compare_digest(
                        origin_host,
                        request_host,
                    ):
                        return JSONResponse(
                            {
                                "success": False,
                                "error": "Invalid request origin",
                            },
                            status_code=403,
                        )
                except Exception:
                    return JSONResponse(
                        {
                            "success": False,
                            "error": "Invalid request origin",
                        },
                        status_code=403,
                    )

            return await call_next(request)

        # Everything else requires authentication first. The auth
        # middleware remains responsible for the actual auth decision.
        if not request.session.get("authenticated"):
            return await call_next(request)

        expected = request.session.get("csrf_token")
        supplied = request.headers.get("x-csrf-token")

        if (
            not expected
            or not supplied
            or not hmac.compare_digest(expected, supplied)
        ):
            return JSONResponse(
                {
                    "success": False,
                    "error": "Invalid CSRF token",
                },
                status_code=403,
            )

        return await call_next(request)



PUBLIC_PATHS = {
    "/health",
    "/login",
    "/logout",
}


def install_auth_middleware(app) -> None:
    @app.middleware("http")
    async def require_auth(
        request: Request,
        call_next,
    ):
        path = request.url.path

        if path in PUBLIC_PATHS:
            return await call_next(request)

        if request.session.get("authenticated"):
            return await call_next(request)

        accepts_html = (
            "text/html"
            in request.headers.get("accept", "")
        )

        if request.method == "GET" and accepts_html:
            return RedirectResponse(
                "/login",
                status_code=303,
            )

        return JSONResponse(
            {
                "success": False,
                "error": "Authentication required",
            },
            status_code=401,
        )
