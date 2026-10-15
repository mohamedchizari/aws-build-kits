"""Keep AWS account ids off the screen and out of the results files.

The state file is local and git-ignored, so it holds the full account id. Nothing
this kit prints or writes into results/ shows more than the last four digits: an
account id is a 12-digit number, and it appears inside bucket names, role ARNs,
knowledge base ARNs and AWS error messages, so the numbered scripts filter their
whole output rather than each line by hand.
"""
from __future__ import annotations

import functools
import re
import sys

_ACCOUNT_ID = re.compile(r"(?<![0-9A-Za-z])\d{8}(\d{4})(?![0-9A-Za-z])")
MASK = "********"


def redact(text: str) -> str:
    """Replace the first eight digits of every 12-digit number with asterisks."""
    return _ACCOUNT_ID.sub(lambda match: MASK + match.group(1), text)


def account_label(account_id: str | None) -> str:
    """'********3333' for an account id, 'unknown' for none."""
    if not account_id:
        return "unknown"
    account_id = str(account_id)
    return MASK + account_id[-4:]


class _RedactingStream:
    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        return self._stream.write(redact(text) if isinstance(text, str) else text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


def protect_output(main):
    """Decorator for a script's main(): everything it prints passes through redact()."""
    @functools.wraps(main)
    def wrapper(*args, **kwargs):
        saved = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = _RedactingStream(sys.stdout), _RedactingStream(sys.stderr)
        try:
            return main(*args, **kwargs)
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            sys.stdout, sys.stderr = saved
    return wrapper
