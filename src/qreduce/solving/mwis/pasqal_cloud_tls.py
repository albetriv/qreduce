"""Pasqal Cloud transport settings shared by submission and recovery."""

from contextlib import AbstractContextManager

from qreduce.cloud_tls import cloud_ca_environment


def pasqal_ca_environment() -> AbstractContextManager[None]:
    """Configure Requests trust for authentication and later SDK calls."""
    return cloud_ca_environment("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")