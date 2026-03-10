#!/usr/bin/env python3
import os
import sys
from pathlib import Path

with open('/tmp/test_errors_start.txt', 'w') as f:
    f.write('started\n')
    f.flush()

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

sys.path.insert(0, str(Path(__file__).parent / 'src'))

try:
    from src.bot import main
    with open('/tmp/bot_imported.txt', 'w') as f:
        f.write('imported ok\n')
    import asyncio
    asyncio.run(main())
except Exception as e:
    with open('/tmp/bot_crash.log', 'w') as f:
        f.write(f"CRASH: {e}\n")
        import traceback
        f.write(traceback.format_exc())
    raise
