#!/bin/sh
# Every rule-based experiment of the paper (results tagged v5*). SC_DETCOST=1 makes eviction priorities and view
# benefits use the rows a re-computation scans, so execution counts are deterministic for a seed.  Executions include
# view rebuilds after a republish and view re-selections; rows_scanned counts the fact-table rows they scan.
set -e
cd "$(dirname "$0")/../code"
export SC_DETCOST=1
ALL=NoCache,Exact,SemNoScope,PerUser,PerScope,TTL,ViewRewrite,ScopeCache,SC-online,SC-nolift,SC-snap,SC-atoms,PerScope+,VR-adapt,PerScope+V,SC-online-nolift,VR-adapt300,VR-adapt1200
EVM=NoCache,Exact,SemNoScope,PerUser,PerScope,TTL,ViewRewrite,ScopeCache,SC-snap,PerScope+V
XM=NoCache,PerScope,ViewRewrite,ScopeCache,SC-online,SC-atoms,PerScope+V
DM=NoCache,PerScope,PerScope+,PerScope+V,ViewRewrite,ScopeCache,SC-online
for s in tpch tpcds bird ent; do
  for seed in 0 1 2; do python -W ignore run.py $s --seed $seed --calls 3000 --tag v5main --methods $ALL; done
  # event sweep with common random numbers: the same calls at every rate
  for ev in 0 1 4 16; do python -W ignore run.py $s --ev $ev --crn --calls 3000 --tag v5cev$ev --methods $EVM; done
  python -W ignore run.py $s --drift 30 --calls 3000 --tag v5drift --methods $XM
  python -W ignore run.py $s --budget 100000 --calls 3000 --tag v5b100k --methods $XM
done
# policy-domain sweep (synthetic; build first with: python datasets.py dom50 dom300 dom1000 dom3000)
for n in 50 300 1000 3000; do
  python -W ignore run.py dom$n --seed 0 --calls 3000 --tag v5dom --methods $DM
done
# scale run (build first with: python datasets.py tpch5; about 1 GB)
python -W ignore run.py tpch5 --seed 0 --calls 3000 --tag v5scale --methods $DM
# The ERP setup (setup erp: main grid and event sweep, tags v5main and v5cev) needs the non-released grant file; its results are in results/.
