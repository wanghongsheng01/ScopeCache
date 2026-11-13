#!/bin/sh
# Replay the released agent traces through all caches (no LLM calls), then the k-sensitivity.
set -e
cd "$(dirname "$0")/../code"
export SC_DETCOST=1 SC_VER=v4
python3 -W ignore agent_eval.py
python3 -W ignore agent_sens.py
# ENT with a budget of 10^7 rows (lifted entries fit under the admission bound)
SC_SETUPS=ent SC_METHODS=PerScope,PerScope+,PerScope+V,ViewRewrite,ScopeCache,SC-online python3 -W ignore agent_eval.py 10000000
