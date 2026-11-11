"""Sensitivity of cross-scope reuse on real agent traces to question overlap across principals.
For k in K, keep only the episodes of the first k distinct principals that were assigned each question
(k=1: every question is asked by a single principal, so any cross-principal hit comes from derivation
across different questions).  Writes results/agent_sens.json."""
import os, json, glob
VER = os.environ.get("SC_VER", "v2")   # result-name prefix (v3: deterministic eviction cost)
from agent_eval import build_trace, parse_name, ROOT
from run import run_method

K = [1, 2, 3, 5, 0]          # 0 = all episodes
METHODS = ["SemNoScope", "PerUser", "PerScope", "ViewRewrite", "ScopeCache", "SC-online"]


def subsample(path, k):
    rows = [json.loads(l) for l in open(path)]
    if k == 0:
        return rows
    first = {}
    for r in rows:
        us = first.setdefault(r["task"], [])
        if r["user"] not in us and len(us) < k:
            us.append(r["user"])
    return [r for r in rows if r["user"] in first[r["task"]]]


if __name__ == "__main__":
    out = {}
    tmp = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"scopecache_agent_sub_{os.getpid()}.jsonl")
    pdir = os.path.join(ROOT, "results", f"agent_sens_{VER}")                   # one file per trace, reused if newer than the trace
    os.makedirs(pdir, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(ROOT, "results", "agent", "*_*.jsonl"))):
        if path.endswith("_sub.jsonl"):
            continue
        setup, model, seed = parse_name(path)
        key = f"{setup}/{model}/s{seed}"
        part = os.path.join(pdir, key.replace("/", "_") + ".json")
        if os.path.exists(part) and os.path.getmtime(part) > os.path.getmtime(path):
            out[key] = json.load(open(part))
            continue
        for k in K:
            rows = subsample(path, k)
            with open(tmp, "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            trace = build_trace(setup, tmp, seed)
            res = {}
            for m in METHODS:
                r = run_method(setup, seed, 400, trace, m, 1_000_000, 0.2, 0.5)
                dc = max(1, r["data_calls"])
                res[m] = dict(data_calls=r["data_calls"], hit_rate=round(r["hit_rate"], 3), n_exec=r["n_exec"], wrong=r["wrong"],
                              other=round(r.get("hit_other", 0) / dc, 3), xscope=round(r.get("hit_xscope", 0) / dc, 3),
                              self=round(r.get("hit_self", 0) / dc, 3), view=round(r.get("hit_view", 0) / dc, 3))
            vr, sc = res["ViewRewrite"]["n_exec"], res["ScopeCache"]["n_exec"]
            res["red_vs_view"] = round(1 - sc / vr, 3) if vr else None
            out.setdefault(key, {})[f"k={k or 'all'}"] = dict(calls=len(trace), **res)
            print(key, f"k={k or 'all'}", len(trace), "xscope(SC-online)=", res["SC-online"]["xscope"],
                  "other=", res["SC-online"]["other"], "exec VR/SC/SCo/PS=", vr, sc, res["SC-online"]["n_exec"], res["PerScope"]["n_exec"],
                  "red", res["red_vs_view"], flush=True)
        json.dump(out[key], open(part, "w"), indent=1)
    json.dump(out, open(os.path.join(ROOT, "results", f"agent_sens_{VER}.json"), "w"), indent=1)
