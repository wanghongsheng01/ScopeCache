#!/bin/sh
# SC-POP (ghost-guided protected online partition) vs already-measured v5 baselines.
# Does not overwrite v5 or v6adapt files.
set -e
cd "$(dirname "$0")/../code"
# Use the Python that has DuckDB / the requirements (venv recommended).
export SC_DETCOST=1
export SC_THREADS=4
M=SC-POP
mkdir -p ../logs ../results
for seed in 0 1 2; do
  echo "===== v6pop synfg seed=$seed $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  python3 -W ignore -u run.py synfg --seed $seed --calls 3000 --users 700 --tag v6pop --methods $M
done
for setup in tpch tpcds bird ent; do
  for seed in 0 1 2; do
    echo "===== v6pop $setup seed=$seed $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
    python3 -W ignore -u run.py $setup --seed $seed --calls 3000 --users 400 --tag v6pop --methods $M
  done
done
echo "===== v6pop finished $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
