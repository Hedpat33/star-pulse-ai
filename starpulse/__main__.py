"""Allow `python -m starpulse` invocation."""

import sys

from starpulse.cli import main

if __name__ == "__main__":
    sys.exit(main())
