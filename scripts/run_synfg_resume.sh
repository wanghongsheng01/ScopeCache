#!/bin/sh
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PY="$ROOT/.venv/bin/python"
cd "$ROOT/code"
export SC_DETCOST=1
export SC_THREADS=4
export PATH="$ROOT/.venv/bin:$PATH"
[ -x "$PY" ] || { echo "missing $PY"; exit 1; }
ALL=NoCache,Exact,SemNoScope,PerUser,PerScope,TTL,ViewRewrite,ScopeCache,SC-online,SC-nolift,SC-snap,SC-atoms,PerScope+,VR-adapt,PerScope+V,SC-online-nolift,VR-adapt300,VR-adapt1200
EVM=NoCache,Exact,SemNoScope,PerUser,PerScope,TTL,ViewRewrite,ScopeCache,SC-snap,PerScope+V
XM=NoCache,PerScope,ViewRewrite,ScopeCache,SC-online,SC-atoms,PerScope+V
mkdir -p "$ROOT/logs" "$ROOT/results"
run() {
  tag=$1; shift
  setup=$1; shift
  seed=$1; shift
  out="$ROOT/results/${tag}_${setup}_s${seed}.json"
  if [ -f "$out" ]; then
    echo "SKIP existing $out"
    return 0
  fi
  echo "===== $tag $setup seed=$seed $(date '+%F %T %Z') ====="
  "$PY" -W ignore -u run.py "$setup" --seed "$seed" --users 700 --tag "$tag" "$@"
  echo "WROTE $out"
}
for seed in 0 1 2; do
  run v5main synfg $seed --calls 3000 --methods $ALL
done
for ev in 0 1 4 16; do
  run v5cev$ev synfg 0 --ev $ev --crn --calls 3000 --methods $EVM
done
run v5drift synfg 0 --drift 30 --calls 3000 --methods $XM
run v5b100k synfg 0 --budget 100000 --calls 3000 --methods $XM
echo "===== SYN-FG runs finished $(date '+%F %T %Z') ====="
