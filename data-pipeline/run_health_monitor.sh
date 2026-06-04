#!/bin/bash
cd /home/claw/invest-infra/data-pipeline
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)
exec python src/collector/etf_health_monitor.py --etf-codes 562500,560630,159819,515070,515980,512480,159813,159325,515030,159889,516520,512660,512680,159667,515700,516390
