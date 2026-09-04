import os
import socket


def _is_port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def resolve_bind_port(preferred_port: int | str | None = None) -> int:
    """Return a free local port, falling back to the next available one."""
    requested = int(preferred_port if preferred_port is not None else os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")

    if _is_port_free(host, requested):
        return requested

    for candidate in range(requested + 1, requested + 21):
        if _is_port_free(host, candidate):
            return candidate

    raise RuntimeError(
        f"No free port available between {requested} and {requested + 20} on {host}. "
        "Free the port or set HOST/PORT to a different value."
    )