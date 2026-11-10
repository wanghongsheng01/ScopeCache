#!/bin/sh
# Main grid (4 setups x 3 seeds) and extras of the paper; about 6 CPU-hours on one laptop core per run.
set -e
cd "$(dirname "$0")/../code"
ALL=NoCache,Exact,SemNoScope,PerUser,PerScope,TTL,ViewRewrite,ScopeCache,SC-online,SC-nolift,SC-snap,SC-atoms
EVM=NoCache,Exact,SemNoScope,PerUser,PerScope,TTL,ViewRewrite,ScopeCache,SC-snap
XM=NoCache,PerScope,ViewRewrite,ScopeCache,SC-online,SC-atoms
for s in tpch tpcds bird ent; do
  for seed in 0 1 2; do python -W ignore run.py $s --seed $seed --calls 3000 --tag v2main --methods $ALL; done
  for ev in 0 4 16; do python -W ignore run.py $s --ev $ev --calls 3000 --tag v2ev$ev --methods $EVM; done
  python -W ignore run.py $s --drift 30 --calls 3000 --tag v2drift --methods $XM
  python -W ignore run.py $s --budget 100000 --calls 3000 --tag v2b100k --methods $XM
  for seed in 0 1 2; do python -W ignore run.py $s --seed $seed --calls 3000 --tag v2sup --methods PerScope+,VR-adapt; done
  for seed in 0 1 2; do python -W ignore run.py $s --seed $seed --calls 3000 --tag v2psv --methods PerScope+V; done
  python -W ignore run.py $s --seed 0 --calls 3000 --tag v2nolift --methods SC-online,SC-online-nolift
done
# policy-domain sweep (synthetic; build with: python datasets.py dom50 dom300 dom1000 dom3000)
for n in 50 300 1000 3000; do
  python -W ignore run.py dom$n --seed 0 --calls 3000 --tag v2dom --methods NoCache,PerScope,PerScope+,PerScope+V,ViewRewrite,ScopeCache,SC-online
done
# The ERP setup (tag v2main/v2psv/v2nolift, setup erp) needs the non-released grant file; its results are in results/.
