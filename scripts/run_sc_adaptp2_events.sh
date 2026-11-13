#!/bin/sh
# SYN-FG event sweep (seed 0, ev=0/1/4/16, --crn) for SC-adaptP (unpin_min=40).
# Also rerun PerScope+V as a same-trace sanity check against v5cev.
# Does not overwrite v5cev* files.
set -e
cd "$(dirname "$0")/../code"
# Use the Python that has DuckDB / the requirements (venv recommended).
export SC_DETCOST=1
export SC_THREADS=4
mkdir -p ../logs ../results
for ev in 0 1 4 16; do
  echo "===== v6cevap2 ev=$ev synfg seed=0 $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  python3 -W ignore -u run.py synfg --seed 0 --ev $ev --crn --calls 3000 --users 700 \
    --tag v6cevap2 --methods PerScope+V,SC-adaptP \
    2>&1 | tee -a ../logs/v6cevap2_synfg.log
done
echo "===== v6cevap2 finished $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
