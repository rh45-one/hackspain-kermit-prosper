"""Typed errors for the Prosper platform API."""
from __future__ import annotations


class ProsperError(Exception):
    """Base error for platform API failures."""


class ProsperAuthError(ProsperError):
    """403 - missing, invalid or revoked API key."""


class NotFoundError(ProsperError):
    """404 - unknown id or another team's resource (indistinguishable)."""


class ClinicValidationError(ProsperError):
    """422 - the platform rejected the request parameters."""


class RateLimitedError(ProsperError):
    """429 - too many requests."""
