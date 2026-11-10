#!/bin/sh
# Replay the released agent traces through all caches (no LLM calls), then the k-sensitivity.
set -e
cd "$(dirname "$0")/../code"
python -W ignore agent_eval.py
python -W ignore agent_sens.py
