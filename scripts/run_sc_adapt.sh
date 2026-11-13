#!/bin/sh
# SC-adapt vs the current default and the strongest baseline. Does not overwrite v5 files.
set -e
cd "$(dirname "$0")/../code"
# Use the Python that has DuckDB / the requirements (venv recommended).
export SC_DETCOST=1
export SC_THREADS=4
# Only the methods needed for the SOTA-gate comparison; v5 JSONs are left untouched.
M=ScopeCache,SC-online,SC-atoms,PerScope+V,SC-adapt
mkdir -p ../logs ../results
# SYN-FG first (the three losses), then public setups to check for regressions.
for seed in 0 1 2; do
  echo "===== v6adapt synfg seed=$seed $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  python3 -W ignore -u run.py synfg --seed $seed --calls 3000 --users 700 --tag v6adapt --methods $M \
    2>&1 | tee -a ../logs/v6adapt_synfg.log
done
for setup in tpch tpcds bird ent; do
  for seed in 0 1 2; do
    echo "===== v6adapt $setup seed=$seed $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
    python3 -W ignore -u run.py $setup --seed $seed --calls 3000 --users 400 --tag v6adapt --methods $M \
      2>&1 | tee -a ../logs/v6adapt_public.log
  done
done
echo "===== v6adapt finished $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
