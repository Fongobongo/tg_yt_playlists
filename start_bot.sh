#!/bin/bash
# Run the bot through uv, logging to file
cd /home/fong/.openclaw/workspace/tg_yt
export PYTHONUNBUFFERED=1
exec uv run python -m src.bot 2>&1 | tee bot_current.log
