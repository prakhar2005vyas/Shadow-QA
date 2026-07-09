"""
Unit tests for the SSRF URL guard.

Tests cover:
  - Private IP ranges (10.x, 172.16.x, 192.168.x)
  - Loopback (127.x, localhost)
  - Link-local / metadata (169.254.x)
  - Forbidden schemes (ftp, file, javascript, data)
  - Malformed / empty URLs
  - IPv6 loopback (::1)

NOTE: We do NOT test that public URLs are allowed in unit tests, because that
      would require DNS resolution and network access. Public URL testing is
      covered by the integration test which uses a real local server.
"""

import pytest

from app.security.url_guard import SSRFError, check_url


# ---------------------------------------------------------------------------
# Blocked IP ranges
# ---------------------------------------------------------------------------


class TestBlockedIPRanges:
    def test_loopback_127_blocked(self):
        with pytest.raises(SSRFError, match="blocked range"):
            check_url("http://127.0.0.1/anything")

    def test_loopback_127_x_blocked(self):
        with pytest.raises(SSRFError, match="blocked range"):
            check_url("http://127.0.0.2/path")

    def test_localhost_resolves_to_loopback_blocked(self):
        with pytest.raises(SSRFError):
            check_url("http://localhost/anything")

    def test_private_10_blocked(self):
        with pytest.raises(SSRFError, match="blocked range"):
            check_url("http://10.0.0.1/")

    def test_private_10_x_blocked(self):
        with pytest.raises(SSRFError, match="blocked range"):
            check_url("http://10.255.255.255/path")

    def test_private_172_16_blocked(self):
        with pytest.raises(SSRFError, match="blocked range"):
            check_url("http://172.16.0.1/")

    def test_private_172_31_blocked(self):
        with pytest.raises(SSRFError, match="blocked range"):
            check_url("http://172.31.255.255/")

    def test_private_192_168_blocked(self):
        with pytest.raises(SSRFError, match="blocked range"):
            check_url("http://192.168.1.100/")

    def test_link_local_169_254_blocked(self):
        # AWS/GCP/Azure metadata endpoint
        with pytest.raises(SSRFError, match="blocked range"):
            check_url("http://169.254.169.254/latest/meta-data/")

    def test_ipv6_loopback_blocked(self):
        with pytest.raises(SSRFError):
            check_url("http://[::1]/path")


# ---------------------------------------------------------------------------
# Forbidden schemes
# ---------------------------------------------------------------------------


class TestForbiddenSchemes:
    def test_ftp_blocked(self):
        with pytest.raises(SSRFError, match="not allowed"):
            check_url("ftp://example.com/file.txt")

    def test_file_scheme_blocked(self):
        with pytest.raises(SSRFError, match="not allowed"):
            check_url("file:///etc/passwd")

    def test_javascript_blocked(self):
        with pytest.raises(SSRFError, match="not allowed"):
            check_url("javascript:alert(1)")

    def test_data_scheme_blocked(self):
        with pytest.raises(SSRFError, match="not allowed"):
            check_url("data:text/html,<h1>hi</h1>")

    def test_ssh_blocked(self):
        with pytest.raises(SSRFError, match="not allowed"):
            check_url("ssh://user@host/")


# ---------------------------------------------------------------------------
# Malformed / edge case URLs
# ---------------------------------------------------------------------------


class TestMalformedUrls:
    def test_empty_url_raises(self):
        with pytest.raises(SSRFError):
            check_url("")

    def test_no_scheme_raises(self):
        # urlparse("example.com/path") — scheme is empty string
        with pytest.raises((SSRFError, ValueError)):
            check_url("example.com/path")

    def test_no_host_raises(self):
        with pytest.raises((SSRFError, ValueError)):
            check_url("http:///path")

    def test_unresolvable_hostname_raises(self):
        with pytest.raises(SSRFError, match="resolve"):
            check_url("http://this-definitely-does-not-exist-hostname-xyz123.invalid/")
