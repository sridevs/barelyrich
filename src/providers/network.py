"""Classify network failures that are worth retrying."""


import errno
import socket
import ssl
from urllib.error import HTTPError, URLError


def is_transient_network_error(error: Exception) -> bool:
    if isinstance(error, HTTPError):
        return _is_transient_http_error(error)
    if isinstance(error, URLError):
        return (
            is_transient_network_error(error.reason)
            if isinstance(error.reason, Exception) else True
        )
    if isinstance(error, ssl.SSLError):
        return False
    if isinstance(error, socket.gaierror):
        return error.errno == socket.EAI_AGAIN
    return isinstance(error, (TimeoutError, ConnectionError)) or (
        isinstance(error, OSError)
        and error.errno in {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ETIMEDOUT}
    )


def _is_transient_http_error(error: HTTPError) -> bool:
    transient = error.code in {408, 429, 500, 502, 503, 504}
    error.close()
    return transient
