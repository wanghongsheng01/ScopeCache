#!/bin/sh
# SC-adaptP (training-only portfolio + always-on POP) vs default and PSV.
# Does not overwrite v5 / v6adapt / v6pop files.
set -e
cd "$(dirname "$0")/../code"
# Use the Python that has DuckDB / the requirements (venv recommended).
export SC_DETCOST=1
export SC_THREADS=4
M=SC-adaptP
mkdir -p ../logs ../results
for seed in 0 1 2; do
  echo "===== v6adaptp synfg seed=$seed $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  python3 -W ignore -u run.py synfg --seed $seed --calls 3000 --users 700 --tag v6adaptp --methods $M \
    2>&1 | tee -a ../logs/v6adaptp_synfg.log
done
echo "===== v6adaptp synfg finished $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
