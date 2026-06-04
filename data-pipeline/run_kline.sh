#!/bin/bash
cd /home/claw/invest-infra/data-pipeline
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)
exec python src/bootstrap_runner.py etf_kline
