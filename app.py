import json
from typing import Callable, Iterable, Tuple


def app(environ, start_response) -> Iterable[bytes]:
    """
    Minimal WSGI app so Vercel's Python runtime has a valid `app` entrypoint.
    The Telegram bot itself runs via the `/api/telegram` webhook function.
    """
    payload = {"ok": True}
    body = json.dumps(payload).encode("utf-8")
    headers: Tuple[Tuple[str, str], ...] = (
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
    )
    start_response("200 OK", list(headers))
    return [body]

