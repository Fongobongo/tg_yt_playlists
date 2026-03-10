#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# Load .env
env_path = Path(__file__).parent / '.env'
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
