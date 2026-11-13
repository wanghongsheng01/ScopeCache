#!/bin/sh
# Smoke test (about 10 minutes): one setup, one seed, 600 calls, every method; checks zero wrong answers.
set -e
cd "$(dirname "$0")/../code"
SC_DETCOST=1 python3 -W ignore run.py bird --seed 0 --calls 600 --tag quick
python - <<'PY'
import json; d = json.load(open("../results/quick_bird_s0.json"))
for m, r in d["methods"].items():
    print(f"{m:12s} hit={r['hit_rate']:.3f} exec={r['n_exec']} wrong={r['wrong']} overpriv={r['overpriv']}")
safe = [m for m in d["methods"] if m not in ("SemNoScope", "TTL")]
assert all(d["methods"][m]["wrong"] == 0 for m in safe), "a safe cache returned a wrong answer"
print("OK: all safe caches returned only fresh answers")
PY
