#!/bin/sh
# SC-adaptP with evidence-threshold POP (unpin_min=40). Rerun SYN-FG and the
# public setups where POP could unpin (TPC-H, TPC-DS). BIRD/ENT evicted=0, skip.
# Does not overwrite v6adaptp / v5 files (tag v6adaptp2).
set -e
cd "$(dirname "$0")/../code"
# Use the Python that has DuckDB / the requirements (venv recommended).
export SC_DETCOST=1
export SC_THREADS=4
M=SC-adaptP
mkdir -p ../logs ../results
for seed in 0 1 2; do
  echo "===== v6adaptp2 synfg seed=$seed $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  python3 -W ignore -u run.py synfg --seed $seed --calls 3000 --users 700 --tag v6adaptp2 --methods $M \
    2>&1 | tee -a ../logs/v6adaptp2.log
done
for setup in tpch tpcds; do
  for seed in 0 1 2; do
    echo "===== v6adaptp2 $setup seed=$seed $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
    python3 -W ignore -u run.py $setup --seed $seed --calls 3000 --users 400 --tag v6adaptp2 --methods $M \
      2>&1 | tee -a ../logs/v6adaptp2.log
  done
done
echo "===== v6adaptp2 finished $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
