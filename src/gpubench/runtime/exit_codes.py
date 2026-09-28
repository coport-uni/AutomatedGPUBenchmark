"""Process exit codes shared by the CLI and the runtime.

The mapping follows DevSpec section 4.8 so that scripted callers can
branch on the verdict without parsing output.
"""

from enum import IntEnum


class ExitCode(IntEnum):
    """Exit status of ``gpubench run``; the other commands reuse it."""

    PASS = 0
    WARN = 1
    FAIL = 2
    INCOMPLETE = 3
    ERROR = 4
