"""Routing rules for services that run on this computer."""
from ipaddress import ip_address
from urllib.parse import urlsplit
from functools import lru_cache
import os


def tls_context(*, trust_env=True):
    """Reuse verified CA loading without sharing clients across event loops.

    HTTPX otherwise loads the same CA bundle again for each proxy transport.
    Certificate environment changes select a new context; proxy discovery and
    certificate verification remain HTTPX's normal behavior.
    """
    return _tls_context(trust_env, os.environ.get('SSL_CERT_FILE') if trust_env else None,
                        os.environ.get('SSL_CERT_DIR') if trust_env else None)


@lru_cache(maxsize=4)
def _tls_context(trust_env, cert_file, cert_dir):
    import httpx
    return httpx.create_ssl_context(trust_env=trust_env)


def is_loopback_url(url: str) -> bool:
    try:
        host = (urlsplit(str(url)).hostname or '').lower()
        if host == 'localhost':
            return True
        return ip_address(host).is_loopback
    except ValueError:
        return False
