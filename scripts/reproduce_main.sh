#!/bin/sh
# Every rule-based experiment of the paper (results tagged v4*). SC_DETCOST=1 makes eviction priorities and view
# benefits use the rows a re-computation scans, so execution counts are deterministic for a seed.
set -e
cd "$(dirname "$0")/../code"
export SC_DETCOST=1
ALL=NoCache,Exact,SemNoScope,PerUser,PerScope,TTL,ViewRewrite,ScopeCache,SC-online,SC-nolift,SC-snap,SC-atoms,PerScope+,VR-adapt,PerScope+V,SC-online-nolift
EVM=NoCache,Exact,SemNoScope,PerUser,PerScope,TTL,ViewRewrite,ScopeCache,SC-snap
XM=NoCache,PerScope,ViewRewrite,ScopeCache,SC-online,SC-atoms
for s in tpch tpcds bird ent; do
  for seed in 0 1 2; do python -W ignore run.py $s --seed $seed --calls 3000 --tag v4main --methods $ALL; done
  for ev in 0 4 16; do python -W ignore run.py $s --ev $ev --calls 3000 --tag v4ev$ev --methods $EVM; done
  python -W ignore run.py $s --drift 30 --calls 3000 --tag v4drift --methods $XM
  python -W ignore run.py $s --budget 100000 --calls 3000 --tag v4b100k --methods $XM
done
# policy-domain sweep (synthetic; build first with: python datasets.py dom50 dom300 dom1000 dom3000)
for n in 50 300 1000 3000; do
  python -W ignore run.py dom$n --seed 0 --calls 3000 --tag v4dom --methods NoCache,PerScope,PerScope+,PerScope+V,ViewRewrite,ScopeCache,SC-online
done
# scale run (build first with: python datasets.py tpch5; about 1 GB)
python -W ignore run.py tpch5 --seed 0 --calls 3000 --tag v4scale --methods NoCache,PerScope,PerScope+,PerScope+V,ViewRewrite,ScopeCache,SC-online
# The ERP setup (setup erp) needs the non-released grant file; its results are in results/.
