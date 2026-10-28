"""Exceptions shared by the CLMS service layer.

The GUI catches these and shows the message to the user, so every message
should be written for a laboratory staff member, not a developer.
"""


class CLMSError(Exception):
    """Base class for all expected, user-facing errors."""


class ValidationError(CLMSError):
    """Input is missing or malformed."""


class PermissionDenied(CLMSError):
    """The signed-in user's role is not allowed to perform the action."""


class NotFound(CLMSError):
    """A referenced record does not exist."""


class InvalidState(CLMSError):
    """The record is not in a state that allows the action (e.g. a completed sale)."""
