"""`python -m referee`."""

import sys

from referee.cli import main

if __name__ == "__main__":
    # A terminal that cannot show a character gets an escape for it, not a crash.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")
    sys.exit(main())
