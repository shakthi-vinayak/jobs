#!/bin/bash
set -e

# Run the pipeline once immediately on startup (bootstrap)
echo "[$(date)] Running initial job fetch..."
cd /app
python main.py || echo "[$(date)] Initial run failed — continuing to cron mode"

# Then start cron in foreground
echo "[$(date)] Starting cron scheduler..."
exec "$@"
