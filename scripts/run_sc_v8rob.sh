#!/bin/sh
# Pre-registered v8 robustness. Args: [rob|shift|all] [synfg|public|all]
set -e
cd "$(dirname "$0")/../code"
# Use the Python that has DuckDB / the requirements (venv recommended).
export SC_DETCOST=1
export SC_THREADS="${SC_THREADS:-2}"
unset SC_UNPIN_MIN
mkdir -p ../logs ../results
WHICH="${1:-all}"
PART="${2:-all}"
echo "===== v8 driver $WHICH $PART start $(date '+%Y-%m-%d %H:%M:%S %Z') threads=$SC_THREADS ====="
python3 -W ignore -u run_v8.py "$WHICH" "$PART"
