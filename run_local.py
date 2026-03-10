#!/usr/bin/env python3
import os
import sys
import traceback
from pathlib import Path

# Immediate debug
with open('/tmp/run_local_debug2.log', 'w') as f:
    f.write('run_local.py started\n')
    f.flush()
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if '=' in line and not line.strip().startswith('#'):
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip().strip('"\'')
else:
    print(".env not found")
    sys.exit(1)

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.bot import main
import asyncio

asyncio.run(main())
