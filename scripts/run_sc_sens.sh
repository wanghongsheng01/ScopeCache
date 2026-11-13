#!/bin/sh
# Sensitivity of unpin_min on the SAME unseen seeds 3,4,5.
# 40 is the official v7fresh run — not repeated. Report only, do not retune.
set -e
cd "$(dirname "$0")/../code"
# Use the Python that has DuckDB / the requirements (venv recommended).
export SC_DETCOST=1
export SC_THREADS=4
M=SC-adaptP
mkdir -p ../logs ../results
for umin in 10 20 80; do
  export SC_UNPIN_MIN=$umin
  for seed in 3 4 5; do
    echo "===== v7sens${umin} synfg seed=$seed $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
    python3 -W ignore -u run.py synfg --seed $seed --calls 3000 --users 700 --tag v7sens${umin} --methods $M \
      2>&1 | tee -a ../logs/v7sens.log
  done
  for setup in tpch tpcds bird ent; do
    for seed in 3 4 5; do
      echo "===== v7sens${umin} $setup seed=$seed $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
      python3 -W ignore -u run.py $setup --seed $seed --calls 3000 --users 400 --tag v7sens${umin} --methods $M \
        2>&1 | tee -a ../logs/v7sens.log
    done
  done
done
echo "===== v7sens finished $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
