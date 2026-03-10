#!/bin/bash
# Activate venv and run the bot, logging to file
cd /home/fong/.openclaw/workspace/tg_yt
source .venv/bin/activate
export PYTHONUNBUFFERED=1
exec python run_local.py 2>&1 | tee bot_current.log
