"""Holdout selection among ScopeCache configurations (SC-adapt).

A small portfolio is scored on a held-out slice of the *training* prefix
(never the test 80%).  The winning configuration is then trained on the
full training prefix and evaluated on the test slice, same protocol as
the other caches.

Portfolio (existing engine switches only):
  raw_hybrid  — default ScopeCache (pinned views + raw policy attrs + lift)
  online      — no pinned views (SC-online)
  atoms       — views + policy atoms when they compress (SC-atoms)
  pop50/pop30 — same as raw_hybrid but views may use only 50%/30% of the
                budget, reserving the rest for online entries.

This module does not fabricate scores: every n_exec is produced by
running Cache.handle on the validation calls.
"""
from __future__ import annotations

import time

from engine import Env, same, Policy
from caches import Cache, DETCOST

# Stable order used as a tie-break: prefer the historical default when
# validation executions are equal, so we do not switch without evidence.
PORTFOLIO = (
    ("raw_hybrid", dict(mode="raw", hybrid=True, lift=True, view_frac=1.0)),
    ("online",     dict(mode="raw", hybrid=False, lift=True)),
    ("atoms",      dict(mode="atoms", hybrid=True, lift=True, view_frac=1.0)),
    ("pop50",      dict(mode="raw", hybrid=True, lift=True, view_frac=0.5)),
    ("pop30",      dict(mode="raw", hybrid=True, lift=True, view_frac=0.3)),
)


def _apply_event(env, kind):
    if kind == "republish":
        return env.sem.republish(), []
    return kind, env.pol.event(kind)


def _score(setup, seed, n_users, trace, cfg, budget, n_sel, n_train):
    """Build views on the first n_sel calls; count executions on calls (n_sel, n_train]."""
    env = Env(setup, seed, n_users)
    cache = Cache(env, budget=budget, **cfg)
    calls = [t for t in trace if t[0] == "call"]
    if cfg.get("hybrid") or cfg.get("mode") == "views":
        tr = calls[:n_sel]
        cache.build_views(
            [(t[1], t[2]) for t in tr],
            [env.rows_in(t[2].months) if DETCOST else t[3]["sec"] for t in tr],
        )
    n_exec = 0
    wrong = 0
    data_calls = 0
    evicted_end = 0
    ci = 0
    t0 = time.time()
    for t in trace:
        if t[0] == "event":
            _apply_event(env, t[1])
            cache.on_event(t[1], None)
            continue
        _, u, q, orc = t
        r = cache.handle(u, q, orc)
        ci += 1
        if n_sel < ci <= n_train:
            data = not isinstance(orc["ans"], str)
            data_calls += int(data)
            n_exec += r["n_exec"]
            if not same(r["ans"], orc["ans"]):
                wrong += 1
        if ci >= n_train:
            evicted_end = cache.stats.get("evicted", 0)
            break
    env.con.close()
    return dict(
        name=None,
        n_exec=n_exec,
        wrong=wrong,
        data_calls=data_calls,
        evicted=evicted_end,
        views=len(getattr(cache, "view_keys", [])),
        wall=round(time.time() - t0, 3),
        cfg={k: cfg[k] for k in cfg},
    )


def select_config(setup, seed, n_users, trace, budget, train_frac=0.2, sel_frac=0.75, pop=False):
    """Return (chosen_cfg, record) using only the training prefix.

    sel_frac is the fraction of the training prefix used to *build* views;
    the remainder of the training prefix is the validation slice.
    If pop=True, every portfolio member is scored with the ARC-style
    protected online partition, matching the test-time SC-adaptP cache.
    """
    calls = [t for t in trace if t[0] == "call"]
    n_train = int(len(calls) * train_frac)
    n_sel = max(1, int(n_train * sel_frac))
    if n_sel >= n_train:
        n_sel = max(1, n_train - 1)
    scores = []
    for name, cfg in PORTFOLIO:
        c = dict(cfg)
        if pop:
            c["pop"] = True
        s = _score(setup, seed, n_users, trace, c, budget, n_sel, n_train)
        s["name"] = name
        scores.append(s)
        print(
            f"  SC-adapt val {name:11s} nexec={s['n_exec']} wrong={s['wrong']} "
            f"views={s['views']} evicted={s['evicted']} wall={s['wall']:.1f}s",
            flush=True,
        )
    # Prefer zero-wrong, then fewer validation executions, then PORTFOLIO order.
    ranked = sorted(scores, key=lambda s: (s["wrong"], s["n_exec"], _order(s["name"])))
    best = ranked[0]
    rec = dict(
        n_train=n_train,
        n_sel=n_sel,
        n_val=n_train - n_sel,
        scores=scores,
        chosen=best["name"],
        chosen_n_exec=best["n_exec"],
        chosen_wrong=best["wrong"],
    )
    print(f"  SC-adapt chose {best['name']} (val nexec={best['n_exec']}, wrong={best['wrong']})", flush=True)
    return dict(best["cfg"]), rec


def _order(name):
    names = [n for n, _ in PORTFOLIO]
    return names.index(name) if name in names else 99
