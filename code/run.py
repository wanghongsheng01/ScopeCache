"""Run the pilot: oracle pass (fresh execution of every call = NoCache), then each cache over the same
resolved trace with identical policy/semantic events.  Every served answer is compared with the oracle."""
import sys, json, time, argparse, os
import numpy as np
from engine import Env, gen_workload, fresh, same, H, Policy
from caches import Cache, DETCOST

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METHODS = {"NoCache": dict(mode="nocache"), "Exact": dict(mode="exact"), "SemNoScope": dict(mode="none"),
           "PerUser": dict(mode="user"), "PerScope": dict(mode="scope"), "TTL": dict(mode="ttl", ttl=500),
           "ViewRewrite": dict(mode="views"),
           # v2 (2026-11-10): the paper's ScopeCache keys cells on raw policy-attribute values; the policy-atom
           # granularity is kept as the SC-atoms variant.  Results with tag main/ev*/drift/b100k used the v1 names
           # (ScopeCache = atoms+hybrid, SC-raw = raw+hybrid); tags v2* use the names below.
           "ScopeCache": dict(mode="raw", hybrid=True), "SC-online": dict(mode="raw"),
           "SC-nolift": dict(mode="raw", hybrid=True, lift=False), "SC-snap": dict(mode="raw", hybrid=True, snapflush=True),
           "SC-atoms": dict(mode="atoms", hybrid=True),
           # baselines added after the mock review (2026-11-10)
           "PerScope+": dict(mode="scopeplus"), "VR-adapt": dict(mode="views", adapt=600),
           "SC-online-nolift": dict(mode="raw", lift=False),
           "PerScope+V": dict(mode="scopeplus", hybrid=True),
           # VR-adapt with other re-selection periods (2026-11-11)
           "VR-adapt300": dict(mode="views", adapt=300), "VR-adapt1200": dict(mode="views", adapt=1200)}


def apply_event(env, kind):
    if kind == "republish":
        return env.sem.republish(), []
    return kind, env.pol.event(kind)


def defkey(env, q):
    sem = env.sem
    parts = sorted({p for m in q.metrics for p in sem.parts(m)})
    return H([[sem.metrics[m] for m in q.metrics], {p: sem.mhash(p) for p in parts},
              {g: sem.mapver[g] for g in q.group if g in sem.mapping}])


def oracle_pass(name, seed, n_calls, ev_rate, n_users, drift=0, crn=False):
    env0 = Env(name, seed, n_users)
    wl = gen_workload(env0, n_calls, seed, ev_rate, drift=drift, crn=crn)
    env0.con.close()
    env = Env(name, seed, n_users)
    trace, last_q, affected = [], {}, []
    for it in wl:
        if it[0] == "event":
            info, affected = apply_event(env, it[1])
            trace.append(("event", it[1], info, len(affected)))
            continue
        if it[0] == "replay":
            us = [u for u in sorted(affected) if u in last_q]
            if not us:
                continue
            u, q = us[0], last_q[us[0]]
        else:
            _, u, q = it
        ans, df, sec, sql = fresh(env, u, q)
        last_q[u] = q
        trace.append(("call", u, q, dict(ans=ans, df=df, sec=sec, sql=sql, snap=env.sem.snapshot_id(),
                                         defkey=defkey(env, q), skey=Policy.scope_key(env.pol.scope(u)),
                                         replay=it[0] == "replay")))
    env.con.close()
    return trace


def overpriv(env, src, u, q, oans):
    if isinstance(oans, str):
        return True                       # served data where the fresh call is rejected
    sc = env.pol.scope(u)
    if sc is None:
        return True
    if src is None:
        return False
    cb = env.combos
    m = np.ones(len(cb), dtype=bool)
    for c, v in q.filters:
        if c in cb:
            m &= cb[c].isin(list(v)).to_numpy()

    def msk(conj):
        out = np.zeros(len(cb), dtype=bool)
        for c in conj:
            mm = np.ones(len(cb), dtype=bool)
            for a, v in c.items():
                mm &= cb[a].isin(list(v)).to_numpy()
            out |= mm
        return out
    return bool((m & msk(src) & ~msk(sc[0])).any())


def run_method(name, seed, n_users, trace, mname, budget, train_frac, ovh):
    env = Env(name, seed, n_users)
    cfg = dict(METHODS[mname]); cfg["budget"] = budget
    adapt = cfg.pop("adapt", None)
    cache = Cache(env, **cfg)
    calls = [t for t in trace if t[0] == "call"]
    n_train = int(len(calls) * train_frac)
    if cfg["mode"] == "views" or cfg.get("hybrid"):
        tr = calls[:n_train]
        cache.build_views([(t[1], t[2]) for t in tr], [env.rows_in(t[2].months) if DETCOST else t[3]["sec"] for t in tr])
    rec = dict(calls=0, data_calls=0, hits=0, wrong=0, overpriv=0, stale=0, exec_s=0.0, derive_s=0.0, n_exec=0, rows_scanned=0,
               lat_local=[], lat_model=[], lat_pad=[], replay_calls=0, replay_wrong=0, peak_rows=0, view_rebuilds=0, readapt_mat=0)
    mat0 = (cache.stats.get("mat_n", 0), cache.stats.get("mat_rows", 0))
    window = []
    ci = 0
    t_start = time.time()
    for t in trace:
        if t[0] == "event":
            _, kind, _, _ = t
            apply_event(env, kind)
            cache.on_event(kind, None)
            continue
        _, u, q, orc = t
        assert Policy.scope_key(env.pol.scope(u)) == orc["skey"], "nondeterministic replay"
        cache.now = ci
        r = cache.handle(u, q, orc)
        ci += 1
        window.append((u, q, env.rows_in(q.months) if DETCOST else orc["sec"]))
        if adapt and ci > n_train and (ci - n_train) % adapt == 0:      # re-select views on the last `adapt` calls
            w = window[-adapt:]
            nv, sec = cache.readapt([(a, b) for a, b, _ in w], [c for _, _, c in w])
            rec["n_exec"] += nv; rec["exec_s"] += sec; rec["view_rebuilds"] += 1; rec["readapt_mat"] += nv
        if ci <= n_train:
            if ci == n_train:      # view materializations from here on (maintenance, re-selection) are measured work
                mat0 = (cache.stats.get("mat_n", 0), cache.stats.get("mat_rows", 0))
            continue
        rec["calls"] += 1
        data = not isinstance(orc["ans"], str)
        rec["data_calls"] += data
        rec["hits"] += bool(r["hit"]) and data
        if r["hit"] and data:
            c = r.get("creator")
            k = "hit_view" if c == "view" else ("hit_self" if c == u else "hit_other")
            rec[k] = rec.get(k, 0) + 1
            if k == "hit_other" and Policy.scope_key(env.pol.scope(c)) != orc["skey"]:
                rec["hit_xscope"] = rec.get("hit_xscope", 0) + 1
        ok = same(r["ans"], orc["ans"])
        if not ok:
            rec["wrong"] += 1
            if len(rec.setdefault("wrong_examples", [])) < 5:      # diagnostics for any wrong answer
                a, b = r["ans"], orc["ans"]
                diff = None
                if isinstance(a, dict) and isinstance(b, dict):
                    ks = sorted(set(a) ^ set(b), key=str)[:3]
                    vk = [k for k in a if k in b and not same({0: a[k]}, {0: b[k]})][:2]
                    diff = {"keys_only_one_side": [str(k) for k in ks], "n": [len(a), len(b)],
                            "vals": [[str(k), list(a[k]), list(b[k])] for k in vk]}
                rec["wrong_examples"].append({"call": ci, "hit": bool(r["hit"]), "metrics": q.metrics, "group": q.group,
                                              "filters": [[c, list(map(str, v))] for c, v in q.filters], "months": list(q.months),
                                              "ans": str(a)[:120] if not isinstance(a, dict) else None, "orc": str(b)[:120] if not isinstance(b, dict) else None,
                                              "diff": diff})
            if overpriv(env, r["src"], u, q, orc["ans"]):
                rec["overpriv"] += 1
            else:
                rec["stale"] += 1
        if orc["replay"]:
            rec["replay_calls"] += 1; rec["replay_wrong"] += (not ok)
        rec["exec_s"] += r["exec"]; rec["derive_s"] += r["derive"]; rec["n_exec"] += r["n_exec"]
        if r["n_exec"]:
            rec["rows_scanned"] += r.get("rows", env.rows_in(q.months))
        loc = r["exec"] + r["derive"]
        rec["lat_local"].append(loc); rec["lat_model"].append(loc + ovh * r["n_exec"])
        # SC-pad: a hit on an entry not created under the requester's current scope (or on a pinned view) is
        # answered at the latency of a miss, so hit timing reveals nothing about other scopes' activity
        pad = r["hit"] and data and (r.get("creator") == "view" or r.get("creator") is None or
                                     Policy.scope_key(env.pol.scope(r["creator"])) != orc["skey"])
        rec["lat_pad"].append(loc + (orc["sec"] + ovh if pad else ovh * r["n_exec"]))
        rec["peak_rows"] = max(rec["peak_rows"], cache.used)
    # view rebuilds after a republish are warehouse executions too (re-selections of VR-adapt are counted above)
    rec["view_maint"] = cache.stats.get("mat_n", 0) - mat0[0] - rec["readapt_mat"]
    rec["n_exec"] += rec["view_maint"]
    rec["rows_scanned"] += cache.stats.get("mat_rows", 0) - mat0[1]
    ll, lm, lp = np.array(rec.pop("lat_local")), np.array(rec.pop("lat_model")), np.array(rec.pop("lat_pad"))
    rec.update(hit_rate=rec["hits"] / max(1, rec["data_calls"]), lat_local_mean=float(ll.mean()),
               lat_local_p50=float(np.percentile(ll, 50)), lat_local_p95=float(np.percentile(ll, 95)),
               lat_model_mean=float(lm.mean()), lat_model_p95=float(np.percentile(lm, 95)), lat_pad_mean=float(lp.mean()),
               stats=cache.stats, wall=time.time() - t_start,
               views=len(getattr(cache, "view_keys", [])))
    env.con.close()
    return rec


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("setup"); ap.add_argument("--seed", type=int, default=0); ap.add_argument("--calls", type=int, default=3000)
    ap.add_argument("--users", type=int, default=400); ap.add_argument("--budget", type=int, default=1_000_000)
    ap.add_argument("--ev", type=float, default=1.0); ap.add_argument("--ovh", type=float, default=0.5)
    ap.add_argument("--methods", default=",".join(METHODS)); ap.add_argument("--tag", default="main")
    ap.add_argument("--drift", type=int, default=0); ap.add_argument("--crn", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    trace = oracle_pass(a.setup, a.seed, a.calls, a.ev, a.users, a.drift, a.crn)
    ev = {}
    for t in trace:
        if t[0] == "event":
            ev[t[1]] = ev.get(t[1], 0) + 1
    print(f"oracle done {time.time()-t0:.0f}s events={ev}", flush=True)
    out = dict(crn=a.crn, drift=a.drift, setup=a.setup, seed=a.seed, calls=a.calls, users=a.users, budget=a.budget, ev=a.ev, ovh=a.ovh, events=ev, methods={})
    for m in a.methods.split(","):
        r = run_method(a.setup, a.seed, a.users, trace, m, a.budget, 0.2, a.ovh)
        out["methods"][m] = r
        print(f"{m:12s} hit={r['hit_rate']:.3f} wrong={r['wrong']} overpriv={r['overpriv']} stale={r['stale']} "
              f"exec={r['exec_s']:.1f}s nexec={r['n_exec']} p50={r['lat_local_p50']*1e3:.1f}ms p95={r['lat_local_p95']*1e3:.1f}ms "
              f"model_mean={r['lat_model_mean']:.3f}s rows={r['peak_rows']} {r['stats']} wall={r['wall']:.0f}s", flush=True)
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    json.dump(out, open(os.path.join(ROOT, "results", f"{a.tag}_{a.setup}_s{a.seed}.json"), "w"), indent=1, default=str)
