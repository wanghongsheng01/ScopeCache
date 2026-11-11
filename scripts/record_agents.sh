#!/bin/sh
# Re-record agent traces.  With the released LLM cache (data/llm_cache.tar.gz unpacked into code/cache) every
# response is served from the cache; new calls need SCOPECACHE_LLM_KEYS.
set -e
cd "$(dirname "$0")/../code"
# gpt6 and claude go through an OpenAI-compatible gateway whose key is read from T1688_KEY (seed 0 only)
for m in deepseek glm kimi; do
  for job in "tpch 0" "tpcds 0" "bird 0" "ent 0" "tpch 1" "tpcds 1" "bird 1" "ent 1"; do
    set -- $job; python -W ignore agent_trace.py $1 $m --users 40 --tasks 5 --seed $2 --workers 6
  done
done
