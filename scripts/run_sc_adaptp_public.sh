#!/bin/sh
# Public regression for SC-adaptP. Seed 0 also reruns ScopeCache and PerScope+V
# as a sanity check that the rebuilt scopecache.duckdb matches v5.
# Does not overwrite v5 / v6adapt / v6pop files.
set -e
cd "$(dirname "$0")/../code"
# Use the Python that has DuckDB / the requirements (venv recommended).
export SC_DETCOST=1
export SC_THREADS=4
mkdir -p ../logs ../results
for setup in tpch tpcds bird ent; do
  echo "===== v6adaptp $setup seed=0 (sanity+adaptP) $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  python3 -W ignore -u run.py $setup --seed 0 --calls 3000 --users 400 --tag v6adaptp \
    --methods ScopeCache,PerScope+V,SC-adaptP \
    2>&1 | tee -a ../logs/v6adaptp_public.log
  for seed in 1 2; do
    echo "===== v6adaptp $setup seed=$seed $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
    python3 -W ignore -u run.py $setup --seed $seed --calls 3000 --users 400 --tag v6adaptp \
      --methods SC-adaptP \
      2>&1 | tee -a ../logs/v6adaptp_public.log
  done
done
echo "===== v6adaptp public finished $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
