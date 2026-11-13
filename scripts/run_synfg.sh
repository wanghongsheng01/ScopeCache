#!/bin/sh
# SYN-FG main grid (3 seeds) and event sweep (CRN, rates 0/1/4/16). SC_DETCOST=1.
set -e
cd "$(dirname "$0")/../code"
# Use the Python that has DuckDB / the requirements (venv recommended).
export SC_DETCOST=1
export SC_THREADS=4
ALL=NoCache,Exact,SemNoScope,PerUser,PerScope,TTL,ViewRewrite,ScopeCache,SC-online,SC-nolift,SC-snap,SC-atoms,PerScope+,VR-adapt,PerScope+V,SC-online-nolift,VR-adapt300,VR-adapt1200
EVM=NoCache,Exact,SemNoScope,PerUser,PerScope,TTL,ViewRewrite,ScopeCache,SC-snap,PerScope+V
XM=NoCache,PerScope,ViewRewrite,ScopeCache,SC-online,SC-atoms,PerScope+V
mkdir -p ../logs ../results
for seed in 0 1 2; do
  echo "===== v5main synfg seed=$seed $(date -u +%FT%T)Z ====="
  python3 -W ignore -u run.py synfg --seed $seed --calls 3000 --users 700 --tag v5main --methods $ALL \
    2>&1 | tee -a ../logs/synfg_main.log
done
for ev in 0 1 4 16; do
  echo "===== v5cev$ev synfg seed=0 $(date -u +%FT%T)Z ====="
  python3 -W ignore -u run.py synfg --seed 0 --ev $ev --crn --calls 3000 --users 700 --tag v5cev$ev --methods $EVM \
    2>&1 | tee -a ../logs/synfg_event.log
done
echo "===== v5drift synfg $(date -u +%FT%T)Z ====="
python3 -W ignore -u run.py synfg --seed 0 --drift 30 --calls 3000 --users 700 --tag v5drift --methods $XM \
  2>&1 | tee -a ../logs/synfg_extra.log
echo "===== v5b100k synfg $(date -u +%FT%T)Z ====="
python3 -W ignore -u run.py synfg --seed 0 --budget 100000 --calls 3000 --users 700 --tag v5b100k --methods $XM \
  2>&1 | tee -a ../logs/synfg_extra.log
echo "===== SYN-FG runs finished $(date -u +%FT%T)Z ====="
