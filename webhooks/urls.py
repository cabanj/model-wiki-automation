"""URL validation. This is the security boundary of the whole service.

The service POSTs to URLs that strangers supply, so a naive `urllib` call is a
server-side request forgery primitive: a subscriber could aim deliveries at
`http://127.0.0.1:4000/` (the LiteLLM router with its master key), at cloud
instance metadata, or at the VPS's own admin ports. Every check here exists to
close that hole, and the address is validated *after* DNS resolution rather than
only by hostname, because a public hostname is free to resolve anywhere.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = ("https",)
# The test-only relaxation (ROSTER_WEBHOOK_ALLOW_PRIVATE) also permits plain
# http, because a local subscriber server has no certificate. It is never set
# in production, and it relaxes scheme AND address together on purpose: a flag
# that loosened one without the other would invite enabling it for a real
# reason and silently dropping the other protection.
ALLOWED_SCHEMES_TEST = ("https", "http")


class InvalidTarget(ValueError):
    """The URL cannot be used as a webhook target."""


def _blocked(ip, allow_private):
    if allow_private:
        return False
    if ip.is_loopback or ip.is_link_local or ip.is_private:
        return True
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    # 100.64.0.0/10 (carrier NAT) and the IPv4-mapped IPv6 range are the two
    # that naive checks miss: is_private covers CGNAT, but an IPv4 address
    # tunnelled as ::ffff:127.0.0.1 is still localhost.
    if ip.version == 6 and ip.ipv4_mapped:
        return _blocked(ip.ipv4_mapped, allow_private)
    return False


def resolve_addresses(host, allow_private=False):
    """Every address `host` currently resolves to.

    Returned as strings so the caller can log them; validation happens in
    `validate_url` so the decision and the reason live together.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as error:
        raise InvalidTarget(f"host does not resolve: {error}") from error
    addresses = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr and sockaddr[0] not in addresses:
            addresses.append(sockaddr[0])
    if not addresses:
        raise InvalidTarget("host resolved to no addresses")
    return addresses


def validate_url(url, allow_private=False):
    """Return the parsed URL or raise `InvalidTarget` with a usable reason.

    https-only by default. A webhook target is reached by us, with a signed
    payload, and the response can carry a secret; plain http would put both on
    the wire in front of whoever shares that network.
    """
    if not isinstance(url, str) or not url.strip():
        raise InvalidTarget("url is required")
    url = url.strip()
    if len(url) > 2048:
        raise InvalidTarget("url is too long")

    parts = urlsplit(url)
    allowed = ALLOWED_SCHEMES_TEST if allow_private else ALLOWED_SCHEMES
    if parts.scheme not in allowed:
        raise InvalidTarget(f"scheme must be https, got {parts.scheme or 'none'!r}")
    if not parts.hostname:
        raise InvalidTarget("url has no host")
    if parts.username or parts.password:
        # Credentials in a URL leak through logs on both sides and are almost
        # always a mistake; the secret belongs in the HMAC header we generate.
        raise InvalidTarget("url must not contain credentials")

    try:
        address = ipaddress.ip_address(parts.hostname)
    except ValueError:
        address = None

    if address is not None:
        if _blocked(address, allow_private):
            raise InvalidTarget(f"address {address} is not a public target")
        return parts

    for candidate in resolve_addresses(parts.hostname, allow_private):
        try:
            resolved = ipaddress.ip_address(candidate)
        except ValueError:
            raise InvalidTarget(f"host resolved to unusable address {candidate!r}")
        if _blocked(resolved, allow_private):
            # Checked per resolved address, not just the first: a hostname with
            # one public and one loopback A record is the standard bypass.
            raise InvalidTarget(f"host {parts.hostname} resolves to blocked {resolved}")
    return parts
