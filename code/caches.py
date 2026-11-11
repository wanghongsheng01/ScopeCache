"""Caches compared in the pilot.  All derivation-based caches share one derivation routine (roll-up,
filter-down, month sub-range, measure-formula recomposition); they differ only in how scope, policy changes
and semantic-layer changes are handled.

  NoCache      production behaviour: every call executes.
  Exact        key = compiled SQL text with the injected row filter (+ snapshot id); answers only.
  SemNoScope   intent-signature cache with roll-up/filter-down (arXiv 2602.19811 style), shared by all
               principals; column grants are checked, row scope is not.
  PerUser      the same cache partitioned by (user, current scope); flushed on snapshot change.
  PerScope     partitioned by canonical scope (users with identical grants share).
  TTL          per-user cache, entries live for `ttl` calls, no event-driven invalidation.
  ViewRewrite  HRU-style greedy views chosen on a training prefix, keeping raw policy attributes so the
               row filter can be applied at query time (VPD over views); views rebuilt on republish.
  mode "raw"   ScopeCache (run.py: "ScopeCache" with pinned views, "SC-online" without): principal-independent
               partial aggregates grouped by the raw policy-attribute values, predicate lifting, measure
               bundles, dependency-hash validity, scope-keyed fallback.
  mode "atoms" the SC-atoms variant: cells coarsened to grant-literal classes (lazy vocabulary refinement).
  mode "scopeplus"  PerScope+: the same lifting and bundles, but entries computed for and keyed on one scope.
  run.py also defines SC-nolift / SC-snap (ablations) and VR-adapt (ViewRewrite re-selected on a window).
"""
import time, math, os
# SC_DETCOST=1: eviction priorities use the rows a re-computation scans (deterministic) instead of measured seconds
DETCOST = os.environ.get("SC_DETCOST") == "1"
import numpy as np, pandas as pd
from engine import Policy, H, in_sql, classify, answer_from, needed_cols, AGG_PD

LIFT = 32


class Entry:
    __slots__ = ("G", "filters", "months", "meas", "df", "size", "cost", "freq", "prio", "part", "src", "voc",
                 "snap", "created", "answer", "maptag", "key", "atoms", "pinned", "creator")


class Cache:
    def __init__(self, env, mode, budget=1_000_000, lift=True, snapflush=None, ttl=None, hybrid=False, view_frac=1.0):
        self.env, self.mode, self.budget, self.lift, self.ttl = env, mode, budget, lift, ttl
        self.hybrid, self.view_frac, self.pinned = hybrid, view_frac, 0
        self.snapflush = (mode in ("none", "user", "scope")) if snapflush is None else snapflush
        self.buckets = {}            # part -> list[Entry]
        self.exact = {}              # key -> Entry (answers)
        self.used, self.L = 0, 0.0
        self.voc_cache, self.cls_cache = {}, {}
        self.gver = None
        self.stats = {"flushed": 0, "split_miss": 0, "fallback": 0, "evicted": 0, "maint_sec": 0.0}
        self.now = 0

    # ------------------------------------------------------------------ helpers
    def part_of(self, u, sc):
        m = self.mode
        if m == "none":
            return "*"
        if m == "user":
            return (u, Policy.scope_key(sc))
        if m == "ttl":
            return u
        return Policy.scope_key(sc)    # scope, and scoped fallback of atoms/raw

    def vocab(self):
        pol = self.env.pol
        if self.gver != pol.gversion:
            voc = pol.vocabulary()
            vid = H({a: sorted(((str(k), c) for k, c in m.items())) for a, m in voc.items()})
            if vid not in self.voc_cache:
                attrs = list(voc)
                ncls = [max(m.values()) + 1 for m in voc.values()]
                strides = [int(np.prod(ncls[i + 1:])) for i in range(len(attrs))]
                cls_sets = {a: {} for a in attrs}
                for a in attrs:
                    for v, c in voc[a].items():
                        cls_sets[a].setdefault(c, set()).add(v)
                cls_sets = {a: {c: frozenset(s) for c, s in d.items()} for a, d in cls_sets.items()}
                cb = self.env.combos
                bid = sum(cb[a].map(voc[a]).to_numpy() * s for a, s in zip(attrs, strides))
                blocks = {}
                for b, row in zip(bid, cb.itertuples(index=False)):
                    blocks[int(b)] = tuple(voc[a][getattr(row, a)] for a in attrs)
                expr = " + ".join(
                    "(CASE " + a + " " + " ".join(f"WHEN {_lit(v)} THEN {c * s}" for v, c in voc[a].items() if c * s) + " ELSE 0 END)"
                    if s and max(voc[a].values()) > 0 else "0" for a, s in zip(attrs, strides))
                self.voc_cache[vid] = {"voc": voc, "cls": cls_sets, "blocks": list(blocks.items()), "expr": expr}
            self.cur_voc, self.gver = vid, pol.gversion
        return self.cur_voc

    def allowed(self, vid, conj, skey):
        k = (vid, skey)
        if k not in self.cls_cache:
            V = self.voc_cache[vid]
            self.cls_cache[k] = classify(conj, V["voc"], V["cls"], V["blocks"])
        return self.cls_cache[k]

    def admit(self, e, bucket=None):
        if e.size > self.budget / 10 or e.size > self.budget - self.pinned:
            return False
        while self.used + e.size > self.budget:
            self.evict()
        e.freq = 1; e.prio = self.L + e.cost / max(1, e.size)
        if bucket is None:
            self.exact[e.part] = e
        else:
            self.buckets.setdefault(bucket, []).append(e)
        self.used += e.size
        return True

    def evict(self):
        best, where = None, None
        for b, lst in self.buckets.items():
            for i, e in enumerate(lst):
                if e.pinned:
                    continue
                if best is None or e.prio < best.prio:
                    best, where = e, (b, i)
        for k, e in self.exact.items():
            if best is None or e.prio < best.prio:
                best, where = e, (None, k)
        b, i = where
        if b is None:
            del self.exact[i]
        else:
            self.buckets[b].pop(i)
        self.used -= best.size; self.L = best.prio; self.stats["evicted"] += 1

    def touch(self, e):
        if e.pinned:
            return
        e.freq += 1; e.prio = self.L + e.cost * e.freq / max(1, e.size)

    def drop(self, pred):
        n = 0
        for b in list(self.buckets):
            keep = []
            for e in self.buckets[b]:
                if pred(e):
                    self.used -= e.size; n += 1
                    if e.pinned:
                        self.pinned -= e.size
                else:
                    keep.append(e)
            self.buckets[b] = keep
        for k in list(self.exact):
            if pred(self.exact[k]):
                self.used -= self.exact[k].size; del self.exact[k]; n += 1
        return n

    # ------------------------------------------------------------------ events
    def on_event(self, kind, info):
        env = self.env
        if kind == "republish":
            if self.snapflush:
                snap = env.sem.snapshot_id()
                self.stats["flushed"] += self.drop(lambda e: e.snap != snap)
            elif self.mode in ("atoms", "raw", "views", "scopeplus"):
                def dead(e):
                    if e.answer is not None:
                        return e.snap != self.defkey_any(e)
                    if e.pinned:
                        return False          # pinned atom views stay; their unchanged measure columns remain valid
                    return all(env.sem.measures.get(m) is None or env.sem.mhash(m) != h for m, h in e.meas.items())
                if self.mode == "views" or self.hybrid:
                    self.rebuild_views()          # only views whose measure hashes changed
                if self.mode != "views":
                    self.stats["flushed"] += self.drop(dead)

    def defkey_any(self, e):
        return e.snap   # exact side-store entries are keyed by their definition hash; never flushed eagerly

    # ------------------------------------------------------------------ derivation
    def derive(self, e, q, mask_fn, check_sem=True):
        env, sem = self.env, self.env.sem
        ms = sorted({p for m in q.metrics for p in sem.parts(m)})
        if any(sem.metrics[m].startswith("DISTINCT:") for m in q.metrics):
            return None
        for m in ms:
            if m not in e.meas or (check_sem and e.meas[m] != sem.mhash(m)):
                return None
        gspec = []
        for g in q.group:
            if g in sem.mapping:
                src = env.sp["mapped"][g][0]
                tag = f"{g}@{sem.mapver[g]}"
                if tag in e.G:
                    gspec.append((tag, None))
                elif not check_sem and e.maptag.get(g) in e.G:
                    gspec.append((e.maptag[g], None))
                elif src in e.G:
                    gspec.append((src, g))
                else:
                    return None
            elif g in e.G:
                gspec.append((g, None))
            else:
                return None
        qf = dict(q.filters)
        for c, vals in e.filters.items():
            if c not in qf or not set(qf[c]) <= vals:
                return None
        resid = {}
        for c, vals in qf.items():
            if c in e.filters and set(vals) == e.filters[c]:
                continue
            if c not in e.G:
                return None
            resid[c] = vals
        m1, m2 = q.months
        if m1 < e.months[0] or m2 > e.months[1]:
            return None
        if (m1, m2) != tuple(e.months) and "month" not in e.G:
            return None
        df = e.df
        mask = np.ones(len(df), dtype=bool)
        if (m1, m2) != tuple(e.months):
            mv = df["month"].to_numpy(); mask &= (mv >= m1) & (mv <= m2)
        for c, vals in resid.items():
            mask &= df[c].isin(list(vals)).to_numpy()
        if mask_fn is not None:
            mm = mask_fn(e)
            if mm is None:
                return None
            mask &= mm
        sub = df[mask]
        keys = []
        tmp = {}
        for i, (col, mp) in enumerate(gspec):
            kname = f"_k{i}"
            tmp[kname] = sub[col].map(sem.mapping[mp]).fillna("other") if mp else sub[col]
            keys.append(kname)
        agg = {"_n": "sum"}
        for m in ms:
            agg[f"m_{m}"] = AGG_PD[sem.measures[m][0]]
        part = pd.DataFrame(tmp, index=sub.index)
        for c in agg:
            part[c] = sub[c]
        if keys:
            gb = part.groupby(keys, sort=False, dropna=False)
            # SQL semantics: a SUM over only NULL partials is NULL (pandas would return 0), so use min_count=1
            sums = [c for c, a in agg.items() if a == "sum"]
            others = {c: a for c, a in agg.items() if a != "sum"}
            g = gb[sums].sum(min_count=1)
            if others:
                g = g.join(gb.agg(others))
            g = g[list(agg)].reset_index()
        else:
            g = pd.DataFrame({c: [part[c].sum(min_count=1) if a == "sum" else part[c].agg(a)] for c, a in agg.items()})
        return answer_from(env, q, g, keys)

    # ------------------------------------------------------------------ main entry point
    def handle(self, u, q, orc):
        """orc = oracle record (answer, df, sec, sql, snapshot, defkey).  Returns dict(ans, exec, derive, hit, src)."""
        env, pol, sem = self.env, self.env.pol, self.env.sem
        mode = self.mode
        self.cur_user = u
        t0 = time.perf_counter()
        sc = pol.scope(u)
        if mode != "ttl":
            if sc is None:
                return dict(ans="NOGRANT", exec=0.0, derive=0.0, hit=False, src=None, n_exec=0)
            if (needed_cols(env, q) & set(env.sp["sensitive"])) - sc[1]:
                return dict(ans="DENY", exec=0.0, derive=0.0, hit=False, src=None, n_exec=0)
        if mode == "nocache":
            return dict(ans=orc["ans"], exec=orc["sec"], derive=0.0, hit=False, src=None, n_exec=1)
        if mode == "exact":
            k = (orc["sql"], orc["defkey"])      # compiled SQL incl. the metric formulas
            e = self.exact.get(k)
            if e is not None:
                self.touch(e)
                return dict(ans=e.answer, exec=0.0, derive=time.perf_counter() - t0, hit=True, creator=e.creator, src=e.src, n_exec=0)
            self._admit_answer(k, orc, sc, q)
            return dict(ans=orc["ans"], exec=orc["sec"], derive=0.0, hit=False, src=None, n_exec=1)

        part = self.part_of(u, sc)
        rejected = mode == "ttl" and isinstance(orc["ans"], str)   # TTL hits skip the check; a miss is checked by the warehouse
        distinct = any(sem.metrics[m].startswith("DISTINCT:") for m in q.metrics)
        check_sem = mode != "ttl"
        # 1) exact side store (non-decomposable aggregates); ttl ignores definitions
        if distinct or mode == "views":
            dk = orc["defkey"] if check_sem else "-"
            k = (part if mode not in ("atoms", "raw", "views") else Policy.scope_key(sc), q.key(), dk)
            e = self.exact.get(k)
            if e is not None and self._fresh(e):
                self.touch(e)
                return dict(ans=e.answer, exec=0.0, derive=time.perf_counter() - t0, hit=True, creator=e.creator, src=e.src, n_exec=0)
            if distinct:
                if rejected:
                    return dict(ans=orc["ans"], exec=0.0, derive=0.0, hit=False, src=None, n_exec=0)
                if orc["df"] is not None and mode != "views":
                    self._admit_answer(k, orc, sc, q)
                self.stats["fallback"] += 1
                return dict(ans=orc["ans"], exec=orc["sec"], derive=0.0, hit=False, src=None, n_exec=1)
        # 2) derivation entries
        cand = []
        if mode == "scopeplus":                  # partitioned: only entries computed for the requester's own scope
            if self.hybrid:                      # PerScope+V: the same pinned (principal-independent) views first
                cand.append(("*", self._mask_for(sc)))
            cand.append((Policy.scope_key(sc), self._mask_for(sc)))
        elif mode in ("atoms", "raw", "views"):
            cand.append(("*", self._mask_for(sc)))
            cand.append((Policy.scope_key(sc), None))
        else:
            cand.append((part, None))
        for b, mf in cand:
            for e in self.buckets.get(b, ()):
                if not self._fresh(e):
                    continue
                ans = self.derive(e, q, mf, check_sem)
                if ans is not None:
                    self.touch(e)
                    return dict(ans=ans, exec=0.0, derive=time.perf_counter() - t0, hit=True,
                                creator=e.creator, src=e.src, n_exec=0)
        # 3) miss
        if mode in ("atoms", "raw", "scopeplus"):
            r = self._miss_shared(q, sc)
            if r is not None:
                return r
            self.stats["fallback"] += 1
            self._admit_scoped(Policy.scope_key(sc), q, orc, sc)
            return dict(ans=orc["ans"], exec=orc["sec"], derive=0.0, hit=False, src=None, n_exec=1)
        if mode == "views":
            return dict(ans=orc["ans"], exec=orc["sec"], derive=0.0, hit=False, src=None, n_exec=1)
        if rejected:
            return dict(ans=orc["ans"], exec=0.0, derive=0.0, hit=False, src=None, n_exec=0)
        self._admit_scoped(part, q, orc, sc)
        return dict(ans=orc["ans"], exec=orc["sec"], derive=0.0, hit=False, src=None, n_exec=1)

    def _fresh(self, e):
        if self.ttl is not None and self.now - e.created > self.ttl:
            return False
        if self.snapflush and e.snap != self.env.sem.snapshot_id() and e.answer is None:
            return False
        return True

    def _mask_for(self, sc):
        """Row mask of an entry's partial rows that lie inside scope(u): block classification for
        atom-partitioned entries, direct evaluation of the grant DNF for raw-attribute entries."""
        conj, _ = sc
        skey = Policy.scope_key(sc)

        def f(e):
            if e.voc is not None:
                al = self.allowed(e.voc, conj, skey)
                if al is None:
                    self.stats["split_miss"] += 1
                    return None
                return e.df["_blk"].isin(list(al)).to_numpy()
            if any(a not in e.df.columns for c in conj for a in c):
                return np.ones(len(e.df), dtype=bool)   # scope-keyed entry: computed for exactly this scope
            m = np.zeros(len(e.df), dtype=bool)
            for c in conj:
                mm = np.ones(len(e.df), dtype=bool)
                for a, v in c.items():
                    mm &= e.df[a].isin(list(v)).to_numpy()
                m |= mm
            return m
        return f

    def _base_entry(self, sc):
        e = Entry(); e.created = self.now; e.snap = self.env.sem.snapshot_id(); e.answer = None
        e.src = sc[0] if sc else None; e.voc = None; e.maptag = {}; e.pinned = False
        e.creator = getattr(self, "cur_user", None)
        return e

    def _admit_answer(self, k, orc, sc, q=None):
        e = self._base_entry(sc)
        e.answer = orc["ans"]; e.size = max(1, len(orc["ans"]) if isinstance(orc["ans"], dict) else 1)
        e.cost = self.env.rows_in(q.months) if (DETCOST and q is not None) else orc["sec"]
        e.part = k; e.snap = orc["snap"] if self.mode == "exact" else orc["defkey"]
        e.G = (); e.filters = {}; e.months = (); e.meas = {}; e.df = None
        self.admit(e)

    def _admit_scoped(self, part, q, orc, sc):
        if orc["df"] is None:
            return
        env, sem = self.env, self.env.sem
        e = self._base_entry(sc)
        e.df = orc["df"]; e.size = max(1, len(e.df)); e.cost = self.env.rows_in(q.months) if DETCOST else orc["sec"]; e.part = part
        e.G = tuple(e.df.columns[:len(q.group)])
        e.maptag = {g: f"{g}@{sem.mapver[g]}" for g in q.group if g in sem.mapping}
        e.filters = {c: set(v) for c, v in q.filters}; e.months = q.months
        e.meas = {m: sem.mhash(m) for m in {p for mm in q.metrics for p in sem.parts(mm)}}
        self.admit(e, part)

    def _miss_shared(self, q, sc):
        env, sem = self.env, self.env.sem
        pol_attrs = env.sp["policy"]
        for lift in (["full", "year", None] if self.lift else [None]):
            G, gsel = [], []
            for g in q.group:
                if g == "month":
                    G.append("month"); gsel.append("month")
                elif g in sem.mapping:
                    src = env.sp["mapped"][g][0]
                    if len(env.domains[src]) <= LIFT or src in pol_attrs:
                        G.append(src); gsel.append(src)
                    else:
                        ex, al = env.gexpr(g); G.append(al); gsel.append(f"{ex} AS \"{al}\"")
                else:
                    G.append(g); gsel.append(g)
            filters = {}
            for c, v in q.filters:
                if lift and (len(env.domains[c]) <= LIFT or c in pol_attrs) and c not in G:
                    G.append(c); gsel.append(c)
                elif c in G:
                    pass
                else:
                    filters[c] = set(v)
            months = q.months
            if lift == "full":
                months = (env.months[0], env.months[-1])
            elif lift == "year":
                y1, y2 = q.months[0] // 100, q.months[1] // 100
                months = (max(env.months[0], y1 * 100 + 1), min(env.months[-1], y2 * 100 + 12))
            if lift:
                if months != tuple(q.months) and "month" not in G:
                    G.append("month"); gsel.append("month")
            ncomb = len(env.combos)
            gran = "raw"
            if self.mode == "atoms":
                vid = self.vocab()
                nblk = len({b for b, _ in self.voc_cache[vid]["blocks"]})
                if ncomb > 2 * nblk:          # cost-based granularity: atoms only when they compress >= 2x
                    gran = "atoms"
            praw = [c for c in G if c in pol_attrs]
            npraw = int(np.prod([len(env.domains[c]) for c in praw])) if praw else 1
            est = min(ncomb, npraw * nblk) if gran == "atoms" else ncomb
            for c in G:
                if c in pol_attrs:
                    continue
                n = (sum(1 for m in env.months if months[0] <= m <= months[1]) if c == "month"
                     else len(env.domains.get(c, sem.mapping.get(c.split("@")[0], {0: 0}))))
                est *= max(1, n)
            if est > min(self.budget / 10, self.budget - self.pinned):
                continue                       # admission-aware lifting: never compute an entry that cannot be kept
            ms = sorted(sem.measures)
            raw_pol = [a for a in pol_attrs if a not in G]
            where = [f"month BETWEEN {months[0]} AND {months[1]}"] + [in_sql(c, v) for c, v in sorted(filters.items())]
            if self.mode == "scopeplus":       # PerScope+: same lifting and bundles, but computed for the scope only
                where.append(Policy.scope_sql(sc[0]))
            ng = len(gsel) + len(raw_pol)
            inner = f"SELECT {', '.join(gsel + raw_pol + env.measure_sql(ms))} FROM {env.t} WHERE {' AND '.join(where)}"
            if ng:
                inner += f" GROUP BY {', '.join(str(i + 1) for i in range(ng))}"
            if gran == "atoms":
                # two-phase: group by raw policy attributes in the scan, compress to policy atoms afterwards
                outs = [f'"{c}"' if c not in pol_attrs else c for c in G]
                aggs = ["SUM(_n) AS _n"] + [f"{ {'sum': 'SUM', 'count': 'SUM', 'max': 'MAX', 'min': 'MIN'}[sem.measures[m][0]] }(m_{m}) AS m_{m}" for m in ms]
                sql = (f"SELECT {', '.join(outs + ['(' + self.voc_cache[vid]['expr'] + ') AS _blk'] + aggs)} FROM ({inner}) "
                       f"GROUP BY {', '.join(str(i + 1) for i in range(len(G) + 1))}")
                pol_cols = ["_blk"]
            else:
                sql, vid, pol_cols = inner, None, raw_pol
            df, sec = env.run(sql)
            e = self._base_entry(None)
            bucket = Policy.scope_key(sc) if self.mode == "scopeplus" else "*"
            e.df = df; e.size = max(1, len(df)); e.cost = self.env.rows_in(months) if DETCOST else sec; e.part = bucket; e.voc = vid
            e.G = tuple(G + pol_cols); e.filters = filters; e.months = months
            e.meas = {m: sem.mhash(m) for m in ms}
            self.admit(e, bucket)
            mf = self._mask_for(sc)
            ans = self.derive(e, q, mf, True)
            if ans is None:      # cannot happen for a fresh entry under the current vocabulary
                raise RuntimeError("fresh entry not derivable")
            return dict(ans=ans, exec=sec, derive=0.0, hit=False, src=None, n_exec=1, rows=env.rows_in(months))
        return None

    # ------------------------------------------------------------------ static views
    def build_views(self, train_calls, oracle_times, keep=None):
        """Offline greedy selection (HRU-style marginal benefit per row) over candidate views, one per
        distinct training grouping: required columns + month over the whole history + policy columns,
        full measure bundle.  ViewRewrite keeps raw policy attributes; ScopeCache stores policy atoms when
        they compress >= 2x.  Benefit = oracle seconds of not-yet-covered training queries the view answers."""
        env, sem = self.env, self.env.sem
        pol = env.sp["policy"]
        vb = self.budget * (self.view_frac if self.hybrid else 1.0)
        reqs = []
        for (u, q), t in zip(train_calls, oracle_times):
            if any(sem.metrics[m].startswith("DISTINCT:") for m in q.metrics):
                continue
            cols = set(env.sp["mapped"][g][0] if g in sem.mapping else g for g in q.group) | {c for c, _ in q.filters}
            cols.discard("month")
            reqs.append((frozenset(cols), None, t))
        keys = sorted({r[0] for r in reqs}, key=lambda x: sorted(x))
        atoms = False
        if self.mode == "atoms":
            vid = self.vocab()
            atoms = len(env.combos) > 2 * len({b for b, _ in self.voc_cache[vid]["blocks"]})
        cands = {(k | frozenset(pol), False) for k in keys}          # raw policy attributes (VPD over views)
        if atoms:
            cands |= {(k, True) for k in keys}                      # policy atoms for unreferenced attributes
        sized = {}
        t0 = time.perf_counter()
        for key, at in sorted(cands, key=lambda x: (sorted(x[0]), x[1])):
            npc = sorted(key) + ["month"]
            rest = [a for a in pol if a not in key]
            if at:
                n = env.con.execute(f"SELECT COUNT(*) FROM (SELECT DISTINCT {', '.join(npc)}, ({self.voc_cache[vid]['expr']}) "
                                    f"FROM (SELECT DISTINCT {', '.join(npc + rest)} FROM {env.t}))").fetchone()[0]
            else:
                n = env.con.execute(f"SELECT COUNT(*) FROM (SELECT DISTINCT {', '.join(npc + rest)} FROM {env.t})").fetchone()[0]
            sized[(key, at)] = n
        def greedy(pool):
            """Benefit-per-row greedy over `pool`, plus the best single view; return the better (T5)."""
            covered = [False] * len(reqs)
            chosen, used, total = [], 0, 0.0
            while True:
                best = None
                for c in pool:
                    n = sized[c]
                    if c in chosen or used + n > vb:
                        continue
                    ben = sum(t for i, (k, _, t) in enumerate(reqs) if not covered[i] and k <= c[0])
                    if ben > 0 and (best is None or ben / n > best[0]):
                        best = (ben / n, c, ben)
                if best is None:
                    break
                c = best[1]; chosen.append(c); used += sized[c]; total += best[2]
                for i, (k, _, _) in enumerate(reqs):
                    if k <= c[0]:
                        covered[i] = True
            single = max(((sum(t for k, _, t in reqs if k <= c[0]), [c]) for c in pool if sized[c] <= vb),
                         default=(0.0, []), key=lambda x: x[0])
            return max((total, chosen), single, key=lambda x: x[0])
        pools = [[c for c in sized if not c[1]]]
        if atoms:
            pools.append(list(sized))
        sols = [greedy(p) for p in pools]
        chosen = max(sols, key=lambda x: x[0])[1]
        self.stats["view_cover_sec"] = [round(x[0], 3) for x in sols]
        self.stats["view_build_sec"] = time.perf_counter() - t0
        self.view_keys = []
        for key, at in chosen:
            old = (keep or {}).get((tuple(sorted(key)), at))
            if old is not None:                  # still selected: keep the materialized view
                self.buckets.setdefault("*", []).append(old); self.used += old.size; self.pinned += old.size
            else:
                self.stats["view_build_sec"] += self._materialize(tuple(sorted(key)), at)
            self.view_keys.append((key, at))

    def _materialize(self, key, atoms=False):
        env, sem = self.env, self.env.sem
        pol = env.sp["policy"]
        ms = sorted(sem.measures)
        npc = list(key) + ["month"]
        rest = [a for a in pol if a not in key]
        inner = (f"SELECT {', '.join(npc + rest + env.measure_sql(ms))} FROM {env.t} "
                 f"GROUP BY {', '.join(str(i + 1) for i in range(len(npc) + len(rest)))}")
        e = self._base_entry(None)
        if atoms:
            vid = self.vocab()
            aggs = ["SUM(_n) AS _n"] + [f"{ {'sum': 'SUM', 'count': 'SUM', 'max': 'MAX', 'min': 'MIN'}[sem.measures[m][0]] }(m_{m}) AS m_{m}" for m in ms]
            sql = (f"SELECT {', '.join(npc + ['(' + self.voc_cache[vid]['expr'] + ') AS _blk'] + aggs)} FROM ({inner}) "
                   f"GROUP BY {', '.join(str(i + 1) for i in range(len(npc) + 1))}")
            e.voc, e.G = vid, tuple(npc + ["_blk"])
        else:
            sql, e.G = inner, tuple(npc + rest)
        df, sec = env.run(sql)
        self.stats["mat_n"] = self.stats.get("mat_n", 0) + 1
        self.stats["mat_rows"] = self.stats.get("mat_rows", 0) + env.rows_in((env.months[0], env.months[-1]))
        e.df = df; e.size = len(df); e.cost = sec * 1e6; e.part = "*"; e.freq = 1; e.prio = 1e12; e.pinned = True; e.creator = "view"
        e.filters = {}; e.months = (env.months[0], env.months[-1]); e.key = key; e.atoms = atoms
        e.meas = {m: sem.mhash(m) for m in ms}
        self.buckets.setdefault("*", []).append(e); self.used += e.size; self.pinned += e.size
        return sec

    def readapt(self, window_calls, window_times):
        """ViewRewrite-adaptive: drop the pinned views and select new ones on the recent window; returns the
        number of materializations and their seconds (online warehouse work)."""
        keep = {(e.key, e.atoms): e for e in self.buckets.get("*", []) if e.pinned}
        self.drop(lambda e: e.pinned)
        n0, t0 = self.stats.get("mat_n", 0), self.stats.get("view_build_sec", 0.0)
        self.build_views(window_calls, window_times, keep=keep)
        return self.stats.get("mat_n", 0) - n0, self.stats["view_build_sec"] - t0

    def rebuild_views(self):
        """ViewRewrite maintenance on republication: any view with a changed measure is recomputed."""
        sem = self.env.sem
        stale = [e for e in self.buckets.get("*", []) if e.pinned and any(sem.mhash(m) != h for m, h in e.meas.items())]
        for e in stale:
            self.buckets["*"].remove(e); self.used -= e.size; self.pinned -= e.size
            self.stats["maint_sec"] += self._materialize(e.key, e.atoms)
            self.stats["flushed"] += 1


def _lit(v):
    return "'" + str(v).replace("'", "''") + "'" if isinstance(v, str) else str(v)
