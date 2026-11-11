"""Replay recorded agent traces through every cache and measure cross-principal reuse (gate C1).
C1 metric = share of data calls that SC-online (no offline views) serves from an entry created by a
different principal.  Writes results/agent_eval.json."""
import os, json, glob
import sys
VER = os.environ.get("SC_VER", "v2")   # result-name prefix (v3: deterministic eviction cost)
import numpy as np
from engine import Env, Query, fresh, Policy
from run import run_method, defkey

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METHODS = ["NoCache", "Exact", "SemNoScope", "PerUser", "PerScope", "ViewRewrite", "ScopeCache", "SC-online", "SC-atoms", "PerScope+", "VR-adapt",
           "PerScope+V"]
# optional restriction (budget sensitivity): SC_SETUPS=ent SC_METHODS=ScopeCache,SC-online
if os.environ.get("SC_METHODS"):
    METHODS = os.environ["SC_METHODS"].split(",")
SETUPS = os.environ.get("SC_SETUPS", "").split(",") if os.environ.get("SC_SETUPS") else None


def parse_name(path):
    """<setup>_<model>[_s<seed>].jsonl -> (setup, model, seed)"""
    parts = os.path.basename(path)[:-6].split("_")
    seed = int(parts[2][1:]) if len(parts) > 2 else 0
    return parts[0], parts[1], seed


def build_trace(setup, path, seed=0):
    env = Env(setup, seed, 400)
    trace = []
    for line in open(path):
        c = json.loads(line)
        q = Query(c["metrics"], c["group"], [(f, v) for f, v in c["filters"]], tuple(c["months"]))
        ans, df, sec, sql = fresh(env, c["user"], q)
        trace.append(("call", c["user"], q, dict(ans=ans, df=df, sec=sec, sql=sql, snap=env.sem.snapshot_id(), defkey=defkey(env, q),
                                                skey=Policy.scope_key(env.pol.scope(c["user"])), replay=False)))
    env.con.close()
    return trace


def exact_overlap(trace):
    """Share of calls whose exact intent was issued earlier by (a) the same user, (b) another principal."""
    seen = {}
    s = o = 0
    for _, u, q, orc in trace:
        k = q.key()
        if k in seen:
            if u in seen[k]:
                s += 1
            else:
                o += 1
        seen.setdefault(k, set()).add(u)
    n = len(trace)
    return {"same_user": round(s / n, 3), "other_principal": round(o / n, 3)}


if __name__ == "__main__":
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000
    out = {}
    pdir = os.path.join(ROOT, "results", f"agent_eval_{VER}_b{budget}")      # one file per trace, reused if newer than the trace
    os.makedirs(pdir, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(ROOT, "results", "agent", "*_*.jsonl"))):
        setup, model, seed = parse_name(path)
        if SETUPS and setup not in SETUPS:
            continue
        key = f"{setup}/{model}/s{seed}"
        part = os.path.join(pdir, key.replace("/", "_") + ".json")
        prev = json.load(open(part)) if os.path.exists(part) and os.path.getmtime(part) > os.path.getmtime(path) else None
        todo = [m for m in METHODS if not prev or m not in prev["methods"]]
        if not todo:
            out[key] = prev
            continue
        trace = build_trace(setup, path, seed)
        out[key] = prev or {"calls": len(trace), "users": len({t[1] for t in trace}), "exact_intent_overlap": exact_overlap(trace), "methods": {}}
        for m in todo:
            r = run_method(setup, seed, 400, trace, m, budget, 0.2, 0.5)
            dc = max(1, r["data_calls"])
            out[key]["methods"][m] = {k: r.get(k, 0) for k in ["data_calls", "hits", "hit_rate", "wrong", "overpriv", "stale", "n_exec", "lat_model_mean", "peak_rows", "hit_self", "hit_other", "hit_view", "hit_xscope"]}
            out[key]["methods"][m]["other_share"] = round(r.get("hit_other", 0) / dc, 3)
            out[key]["methods"][m]["xscope_share"] = round(r.get("hit_xscope", 0) / dc, 3)
        so = out[key]["methods"].get("SC-online", {"other_share": None})
        out[key]["C1_cross_principal_share"] = so["other_share"]
        print(key, out[key]["calls"], "C1=", so["other_share"], "exact", out[key]["exact_intent_overlap"],
              {m: (round(v["hit_rate"], 3), v["n_exec"], v["overpriv"]) for m, v in out[key]["methods"].items()}, flush=True)
        json.dump(out[key], open(part, "w"), indent=1)
    json.dump(out, open(os.path.join(ROOT, "results", f"agent_eval_{VER}_b{budget}.json"), "w"), indent=1)
