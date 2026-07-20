#!/usr/bin/env python3
"""Main entry point for C-Bus proxy when run as a module"""

import sys
import asyncio
from .proxy import main

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProxy stopped by user")
        sys.exit(0) 