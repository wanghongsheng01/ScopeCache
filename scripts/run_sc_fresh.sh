#!/bin/sh
# Official once-through eval on unseen seeds 3,4,5. Frozen unpin_min=40.
# Does not overwrite v5/v6 files.
set -e
cd "$(dirname "$0")/../code"
# Use the Python that has DuckDB / the requirements (venv recommended).
export SC_DETCOST=1
export SC_THREADS=4
unset SC_UNPIN_MIN   # frozen default 40
M=ScopeCache,PerScope+V,SC-adaptP
mkdir -p ../logs ../results
run_one() {
  setup=$1; seed=$2; users=$3
  echo "===== v7fresh $setup seed=$seed $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  python3 -W ignore -u run.py $setup --seed $seed --calls 3000 --users $users --tag v7fresh --methods $M
}
# SYN-FG first (different duckdb), then public
for seed in 3 4 5; do
  run_one synfg $seed 700 2>&1 | tee -a ../logs/v7fresh.log
done
for setup in tpch tpcds bird ent; do
  for seed in 3 4 5; do
    run_one $setup $seed 400 2>&1 | tee -a ../logs/v7fresh.log
  done
done
echo "===== v7fresh finished $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
