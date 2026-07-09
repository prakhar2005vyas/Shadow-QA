"""
SSRF guard — validates target URLs before Playwright navigates to them.

Strategy: DNS-resolve the hostname, then check every resolved IP against
blocked ranges. We RESOLVE-THEN-CHECK (not string-match-then-check) to
prevent trivial bypasses like 0x7f000001, 127.1, decimal-encoded IPs, etc.

Blocked ranges:
  - 127.0.0.0/8    loopback
  - 10.0.0.0/8     private
  - 172.16.0.0/12  private
  - 192.168.0.0/16 private
  - 169.254.0.0/16 link-local / AWS/GCP metadata endpoint
  - 100.64.0.0/10  shared address space (carrier-grade NAT)
  - 0.0.0.0/8      this-network
  - ::1/128         IPv6 loopback
  - fc00::/7        IPv6 unique local
  - fe80::/10       IPv6 link-local

Only http and https schemes are permitted.
"""

import ipaddress
import socket
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Blocked IP networks (IPv4 + IPv6)
# ---------------------------------------------------------------------------
_BLOCKED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_ALLOWED_SCHEMES = {"http", "https"}


class SSRFError(ValueError):
    """Raised when a URL fails the SSRF guard check."""


def check_url(url: str) -> None:
    """
    Validate that *url* is safe to navigate to.

    Raises:
        SSRFError: URL is blocked (private IP, forbidden scheme, DNS failure, etc.)
        ValueError: URL is malformed and cannot be parsed.

    This function must be called before every Playwright navigation
    initiated from user input.
    """
    if not url:
        raise SSRFError("URL must not be empty.")

    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise ValueError(f"Malformed URL: {exc}") from exc

    # ---- Scheme check ----
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise SSRFError(
            f"Scheme '{parsed.scheme}' is not allowed. "
            f"Only {sorted(_ALLOWED_SCHEMES)} are permitted."
        )

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Could not extract hostname from URL: {url!r}")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    # ---- DNS resolution ----
    try:
        addr_infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFError(
            f"Could not resolve hostname '{hostname}': {exc}"
        ) from exc

    if not addr_infos:
        raise SSRFError(f"DNS returned no addresses for '{hostname}'.")

    # ---- Check every resolved address ----
    for _family, _type, _proto, _canon, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        for network in _BLOCKED_NETWORKS:
            if ip in network:
                raise SSRFError(
                    f"Hostname '{hostname}' resolves to {ip}, which is in blocked "
                    f"range {network}. Requests to private/loopback/link-local "
                    "addresses are not permitted."
                )
