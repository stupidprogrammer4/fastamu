from __future__ import annotations

from starlette.requests import Request

from src.core.config import get_settings

FORWARDED_FOR = "X-Forwarded-For"
UNKNOWN = "unknown"


def client_ip(request: Request) -> str:
    """Resolve the caller's address — the bucket every default rule counts in.

    ``X-Forwarded-For`` is believed only when the immediate peer is one of the
    configured ``trusted_proxies``. Behind a load balancer the peer is always
    the balancer, so without that check every caller would share one bucket;
    without the trust list, any caller could forge a header and get a fresh one.

    Args:
        request (Request): The incoming request.
    Returns:
        (str): The client address, or ``"unknown"`` for a connection with no peer.
    """
    peer = request.client.host if request.client else None
    trusted = get_settings().rate_limit.trusted_proxies
    if peer is not None and peer in trusted:
        forwarded = request.headers.get(FORWARDED_FOR)
        if forwarded:
            return forwarded.split(",")[0].strip()
    return peer or UNKNOWN
