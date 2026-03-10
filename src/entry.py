#!/usr/bin/env python3
import sys
import os
import traceback

# Debug: write to volume
try:
    with open('/app/data/entry_debug.log', 'a') as f:
        f.write("entry.py starting\n")
except Exception:
    pass

sys.path.insert(0, '/app')

try:
    from src.bot import main
    with open('/app/data/entry_debug.log', 'a') as f:
        f.write("imported main\n")
except Exception as e:
    with open('/app/data/entry_crash.log', 'a') as f:
        f.write(f"Import error: {e}\n")
        f.write(traceback.format_exc())
    raise

import asyncio

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        with open('/app/data/entry_crash.log', 'a') as f:
            f.write(f"Main crash: {e}\n")
            f.write(traceback.format_exc())
        raise
