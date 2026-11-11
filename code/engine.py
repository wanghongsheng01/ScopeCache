"""ScopeCache pilot engine: policy model, versioned semantic layer, agent workload, caches and the oracle.

Terminology (see 01_研究计划书.md):
  scope(u)   = OR of conjuncts, each conjunct = AND over policy attributes of (attr IN value-set); {} = TRUE.
  vocabulary = per attribute, the value-sets used by any current grant literal; values with the same
               membership signature form one class; a block (policy atom) is a tuple of classes.
  entry      = partial aggregates of base measures grouped by G' (and by block for ScopeCache).
"""
import hashlib, json, math, os, time, random, itertools
from collections import defaultdict
import duckdb, numpy as np, pandas as pd
from datasets import spec, DB

AGG_SQL = {"sum": "SUM({})", "count": "COUNT(*)", "max": "MAX({})", "min": "MIN({})"}
AGG_PD = {"sum": "sum", "count": "sum", "max": "max", "min": "min"}


def H(x):
    return hashlib.sha1(json.dumps(x, sort_keys=True, default=str).encode()).hexdigest()[:12]


def lit(v):
    return "'" + str(v).replace("'", "''") + "'" if isinstance(v, str) else str(v)


def in_sql(col, vals):
    return f"{col} IN ({','.join(lit(v) for v in sorted(vals, key=str))})"


# ------------------------------------------------------------------------------------------------ semantic layer
class Semantic:
    def __init__(self, sp, domains, rng):
        self.sp = sp
        self.measures = dict(sp["measures"])
        self.metrics = dict(sp["metrics"])
        self.mapping, self.mapver = {}, {}
        for d, (src, mp) in sp["mapped"].items():
            if mp is None:
                dom = sorted(domains[src], key=str)
                mp = {v: f"G{i % 4}" for i, v in enumerate(dom)}
            self.mapping[d] = dict(mp); self.mapver[d] = 0
        self.domains = domains
        self.rng = rng
        self.gen = 0

    def mhash(self, m):
        return H(self.measures[m][:2])

    def snapshot_id(self):
        return H([self.measures, self.metrics, self.mapping])

    def parts(self, metric):
        f = self.metrics[metric]
        if f.startswith("DISTINCT:"):
            return []
        return [m for m in self.measures if _uses(f, m)]

    def cols_of(self, metric):
        f = self.metrics[metric]
        if f.startswith("DISTINCT:"):
            return [f.split(":", 1)[1]]
        return sorted({c for m in self.parts(metric) for c in self.measures[m][2]})

    def republish(self):
        """One governed change: a measure definition, a metric formula or a dimension mapping."""
        self.gen += 1
        kinds = []
        am = [m for m in self.sp["alt_measures"]]
        af = [m for m in self.sp["alt_metrics"]]
        r = self.rng.random()
        if r < 0.4 and am:
            m = self.rng.choice(am)
            cur, alt = self.measures[m], self.sp["alt_measures"][m]
            self.measures[m] = alt if cur == self.sp["measures"][m] else self.sp["measures"][m]
            return ("measure", m)
        if r < 0.8 and af:
            m = self.rng.choice(af)
            cur, alt = self.metrics[m], self.sp["alt_metrics"][m]
            self.metrics[m] = alt if cur == self.sp["metrics"][m] else self.sp["metrics"][m]
            return ("metric", m)
        d = self.rng.choice(list(self.mapping))
        vals = sorted(self.mapping[d], key=str)
        for v in self.rng.sample(vals, min(2, len(vals))):
            self.mapping[d][v] = f"G{self.rng.randrange(5)}"
        self.mapver[d] += 1
        return ("mapping", d)


def _uses(formula, name):
    import re
    return re.search(r"(?<![A-Za-z0-9_])" + name + r"(?![A-Za-z0-9_])", formula) is not None


def eval_metric(formula, cols):
    """cols: dict measure -> float ndarray. Division by zero yields NaN (NULLIF semantics)."""
    import re
    expr = re.sub(r"[A-Za-z_][A-Za-z0-9_]*", lambda m: f"__c['{m.group(0)}']", formula)
    with np.errstate(all="ignore"):
        v = eval(expr, {"__c": cols})
    v = np.asarray(v, dtype=float)
    v[~np.isfinite(v)] = np.nan
    return v


# ------------------------------------------------------------------------------------------------ policy
class Policy:
    """Roles hold DNF row grants (equality/IN conjuncts, as produced by or/and/in combine modes) and a set of
    visible sensitive columns; users reach roles through groups.  Every change bumps `version`."""

    def __init__(self, sp, domains, rng, n_users=400, n_groups=60):
        self.sp, self.domains, self.rng = sp, domains, rng
        self.attrs = sp["policy"]
        self.roles, self.groups, self.users = {}, {}, {}
        self.version = 0
        self.gversion = 0            # bumps only when grant literals change (vocabulary may change)
        if sp.get("real_grants"):
            self._load_real(sp["real_grants"])
            return
        self._mk_roles()
        rids = list(self.roles)
        for g in range(n_groups):
            k = 1 if rng.random() < 0.7 else 2
            self.groups[g] = set(rng.sample(rids, k))
        for u in range(n_users):
            gs = {rng.randrange(n_groups)}
            if rng.random() < 0.2:
                gs.add(rng.randrange(n_groups))
            self.users[u] = {"groups": gs, "active": True}

    def _load_real(self, path):
        """Real grants (ERP): one role per distinct value set of the single policy attribute, one group per role,
        each account in the group of its role.  Column grants are not part of the extract: 20% of roles see the
        sensitive columns, drawn with the policy seed."""
        grants = json.load(open(path))
        a = self.attrs[0]
        sens = frozenset(self.sp["sensitive"])
        rid_of = {}
        for u, (acc, vals) in enumerate(sorted(grants.items())):
            key = tuple(vals)
            if key not in rid_of:
                rid = len(self.roles)
                rid_of[key] = rid
                self.roles[rid] = {"conj": [{a: frozenset(vals)}], "cols": sens if self.rng.random() < 0.2 else frozenset()}
                self.groups[rid] = {rid}
            self.users[u] = {"groups": {rid_of[key]}, "active": True}

    def _vals(self, a, k):
        dom = sorted(self.domains[a], key=str)
        return frozenset(self.rng.sample(dom, min(k, len(dom))))

    def _mk_roles(self):
        rng, sp = self.rng, self.sp
        coarse = sp.get("coarse", {})          # attr -> list of value-sets (hierarchy groups / subtrees)
        sens = frozenset(sp["sensitive"])
        rid = 0

        def add(conj, fin=False):
            nonlocal rid
            self.roles[rid] = {"conj": [dict(c) for c in conj], "cols": sens if fin else frozenset()}
            rid += 1
        add([{}], fin=True)                                   # global analyst
        add([{}], fin=False)                                  # global, no cost columns
        for a in self.attrs:
            groups = coarse.get(a) or [self._vals(a, 2) for _ in range(4)]
            for s in groups:
                add([{a: frozenset(s)}], fin=rng.random() < 0.3)
            for _ in range(6 if a in coarse else 3):
                add([{a: self._vals(a, 1)}], fin=rng.random() < 0.2)
        for _ in range(10):                                   # 'in' mode: cross product of two attributes
            a, b = rng.sample(self.attrs, 2) if len(self.attrs) > 1 else (self.attrs[0], self.attrs[0])
            sa = rng.choice(coarse.get(a) or [self._vals(a, 2)])
            add([{a: frozenset(sa), b: self._vals(b, rng.randint(1, 2))}], fin=rng.random() < 0.2)
        for _ in range(6):                                    # 'or' mode: two equality conjunctions
            conj = []
            for _ in range(2):
                a, b = rng.sample(self.attrs, 2) if len(self.attrs) > 1 else (self.attrs[0], self.attrs[0])
                conj.append({a: self._vals(a, 1), b: self._vals(b, 1)})
            add(conj, fin=False)

    # --- evaluation
    def scope(self, u):
        us = self.users[u]
        if not us["active"]:
            return None
        conj, cols, seen = [], set(), set()
        for g in us["groups"]:
            for r in self.groups.get(g, ()):
                ro = self.roles[r]
                for c in ro["conj"]:
                    k = H({a: sorted(v, key=str) for a, v in c.items()})
                    if k not in seen:
                        seen.add(k); conj.append(c)
                cols |= ro["cols"]
        if not conj:
            return None                                         # no grant -> request rejected (fail closed)
        if any(len(c) == 0 for c in conj):
            conj = [{}]
        return conj, frozenset(cols)

    @staticmethod
    def scope_key(sc):
        if sc is None:
            return "NONE"
        conj, cols = sc
        return H([sorted(H({a: sorted(v, key=str) for a, v in c.items()}) for c in conj), sorted(cols)])

    @staticmethod
    def scope_sql(conj):
        parts = []
        for c in conj:
            if not c:
                return "TRUE"
            parts.append("(" + " AND ".join(in_sql(a, v) for a, v in sorted(c.items())) + ")")
        return "(" + " OR ".join(parts) + ")"

    def vocabulary(self):
        """Per attribute: list of value-sets used by any current literal -> class map."""
        sets = {a: set() for a in self.attrs}
        for ro in self.roles.values():
            for c in ro["conj"]:
                for a, v in c.items():
                    sets[a].add(frozenset(v))
        voc = {}
        for a in self.attrs:
            sl = sorted(sets[a], key=lambda s: sorted(map(str, s)))
            sig2cls, vmap = {}, {}
            for v in sorted(self.domains[a], key=str):
                sig = tuple(v in s for s in sl)
                vmap[v] = sig2cls.setdefault(sig, len(sig2cls))
            voc[a] = vmap
        return voc

    # --- events
    def event(self, kind):
        rng = self.rng
        self.version += 1
        if kind == "member_move":
            u = rng.choice(list(self.users)); g = rng.choice(list(self.groups))
            self.users[u]["groups"] = {g}
            return [u]
        if kind == "revoke":
            u = rng.choice([u for u in self.users if self.users[u]["active"]])
            gs = self.users[u]["groups"]
            if len(gs) > 1:
                gs.discard(rng.choice(sorted(gs)))
            else:
                self.users[u]["active"] = False
            return [u]
        if kind == "reactivate":
            cand = [u for u in self.users if not self.users[u]["active"]]
            if not cand:
                return []
            u = rng.choice(cand); self.users[u]["active"] = True
            return [u]
        if kind == "grant_edit":
            self.gversion += 1
            r = rng.choice([r for r in self.roles if self.roles[r]["conj"] != [{}]])
            c = rng.choice(self.roles[r]["conj"]); a = rng.choice(sorted(c))
            dom = sorted(self.domains[a], key=str)
            if len(c[a]) > 1 and rng.random() < 0.5:
                c[a] = frozenset(c[a] - {rng.choice(sorted(c[a], key=str))})       # shrink = revocation
            else:
                c[a] = frozenset(c[a] | {rng.choice(dom)})                          # widen (new literal)
            return self.users_of_role(r)
        if kind == "col_edit":
            r = rng.choice(list(self.roles))
            ro = self.roles[r]
            ro["cols"] = frozenset() if ro["cols"] else frozenset(self.sp["sensitive"])
            return self.users_of_role(r)
        raise KeyError(kind)

    def users_of_role(self, r):
        gs = {g for g, rs in self.groups.items() if r in rs}
        return [u for u, us in self.users.items() if us["groups"] & gs]


def classify(conj, voc, cls_sets, blocks):
    """Return the set of block ids fully inside scope, or None if some present block is split.
    blocks: iterable of (block_id, tuple of class ids per attr)."""
    attrs = list(voc)
    allowed = set()
    for bid, cl in blocks:
        inside, split = False, False
        for c in conj:
            cover, disjoint = True, False
            for i, a in enumerate(attrs):
                if a not in c:
                    continue
                cs = cls_sets[a][cl[i]]
                if not cs <= c[a]:
                    cover = False
                    if not (cs & c[a]):
                        disjoint = True
            if cover:
                inside = True; break
            if not disjoint:
                split = True
        if inside:
            allowed.add(bid)
        elif split:
            return None
    return allowed


# ------------------------------------------------------------------------------------------------ queries
class Query:
    __slots__ = ("metrics", "group", "filters", "months")

    def __init__(self, metrics, group, filters, months):
        self.metrics = tuple(metrics); self.group = tuple(group)
        self.filters = tuple(sorted((c, tuple(sorted(v, key=str))) for c, v in filters))
        self.months = tuple(months)

    def key(self):
        return (self.metrics, self.group, self.filters, self.months)


class Env:
    """One setup: DuckDB connection, domains, semantic layer, policy."""

    def __init__(self, name, seed=0, n_users=400):
        self.name, self.sp = name, spec(name)
        self.con = duckdb.connect(self.sp.get("db", DB), read_only=True)
        # DuckDB threads (default 4, so that two runs leave room on a shared 10-core machine); counts do not depend on it
        self.con.execute(f"SET threads TO {int(os.environ.get('SC_THREADS', '4'))}")
        self.con.execute("SET threads=8")
        self.t = self.sp["table"]
        cols = set(self.sp["dims"]) | set(self.sp["policy"])
        self.domains = {c: [r[0] for r in self.con.execute(f"SELECT DISTINCT {c} FROM {self.t} WHERE {c} IS NOT NULL").fetchall()]
                        for c in cols}
        self.months = sorted(r[0] for r in self.con.execute(f"SELECT DISTINCT month FROM {self.t}").fetchall())
        self.month_rows = dict(self.con.execute(f"SELECT month, COUNT(*) FROM {self.t} GROUP BY month").fetchall())
        self.rng = random.Random(seed)
        self._coarse()
        self.sem = Semantic(self.sp, self.domains, random.Random(seed + 1))
        self.pol = Policy(self.sp, self.domains, random.Random(seed + 2), n_users=n_users)
        combos = self.con.execute(f"SELECT DISTINCT {','.join(self.sp['policy'])} FROM {self.t}").fetchall()
        self.combos = pd.DataFrame(combos, columns=self.sp["policy"])

    def rows_in(self, months):
        """Rows of the fact table in a month window: the deterministic re-computation cost used for eviction."""
        return float(sum(n for m, n in self.month_rows.items() if months[0] <= m <= months[1])) if months else float(sum(self.month_rows.values()))

    def _coarse(self):
        sp = self.sp; sp.setdefault("coarse", {})
        for a, ca in sp["hier"].items():
            rows = self.con.execute(f"SELECT DISTINCT {ca}, {a} FROM {self.t}").fetchall()
            g = defaultdict(set)
            for x, y in rows:
                g[x].add(y)
            sp["coarse"][a] = [frozenset(v) for _, v in sorted(g.items())]
        if self.name == "ent":                                  # DEPT_AND_CHILD scopes = subtrees of the org tree
            tree = pd.read_csv(DB.replace("scopecache.duckdb", "ent_org_tree.csv"))
            kids = defaultdict(list)
            for d, p in zip(tree.dept, tree.parent):
                if isinstance(p, str):
                    kids[p].append(d)
            def sub(d):
                out, st = set(), [d]
                while st:
                    x = st.pop(); out.add(x); st += kids[x]
                return out
            present = set(self.domains["dept"])
            cand = [d for d, dep in zip(tree.dept, tree.depth) if 1 <= dep <= 3]
            r = random.Random(5)
            subs = [frozenset(sub(d) & present) for d in r.sample(cand, 60)]
            sp["coarse"]["dept"] = [s for s in subs if s]

    # --- SQL
    def gexpr(self, g):
        if g in self.sem.mapping:
            src = self.sp["mapped"][g][0]
            whens = " ".join(f"WHEN {lit(k)} THEN {lit(v)}" for k, v in self.sem.mapping[g].items())
            return f"CASE {src} {whens} ELSE 'other' END", f"{g}@{self.sem.mapver[g]}"
        return g, g

    def measure_sql(self, ms):
        out = ["COUNT(*) AS _n"]
        for m in ms:
            agg, expr, _ = self.sem.measures[m]
            out.append(AGG_SQL[agg].format(expr) + f" AS m_{m}")
        return out

    def run(self, sql):
        t0 = time.perf_counter()
        df = self.con.execute(sql).df()
        return df, time.perf_counter() - t0


# ------------------------------------------------------------------------------------------------ answers
def needed_cols(env, q):
    return {c for m in q.metrics for c in env.sem.cols_of(m)}


def answer_from(env, q, df, gcols):
    """df has group columns gcols (aligned to q.group), _n, m_* and optionally d_* columns."""
    df = df[df["_n"] > 0]
    cols = {m: df[f"m_{m}"].to_numpy(dtype=float) for m in env.sem.measures if f"m_{m}" in df}
    vals = []
    for m in q.metrics:
        f = env.sem.metrics[m]
        if f.startswith("DISTINCT:"):
            vals.append(df["d_" + f.split(":", 1)[1]].to_numpy(dtype=float))
        else:
            vals.append(eval_metric(f, cols))
    def norm(v):                              # NULL group keys: DuckDB yields None, pandas group-by yields NaN
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else v
    keys = list(zip(*[[norm(v) for v in df[c].tolist()] for c in gcols])) if gcols else [()] * len(df)
    return {k: tuple(float(v[i]) for v in vals) for i, k in enumerate(keys)}


def same(a, b):
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    if a.keys() != b.keys():
        return False
    for k in a:
        for x, y in zip(a[k], b[k]):
            if math.isnan(x) and math.isnan(y):
                continue
            if math.isnan(x) or math.isnan(y) or abs(x - y) > 1e-6 * max(1.0, abs(x), abs(y)):
                return False
    return True


def fresh(env, u, q):
    """Oracle: execute q under the current policy and semantic layer (what the tool does without a cache).
    Returns (answer, partial_df, seconds, sql)."""
    sc = env.pol.scope(u)
    if sc is None:
        return "NOGRANT", None, 0.0, None
    conj, cols = sc
    if (needed_cols(env, q) & set(env.sp["sensitive"])) - cols:
        return "DENY", None, 0.0, None
    ms = sorted({p for m in q.metrics for p in env.sem.parts(m)})
    ds = sorted({env.sem.metrics[m].split(":", 1)[1] for m in q.metrics if env.sem.metrics[m].startswith("DISTINCT:")})
    ge = [env.gexpr(g) for g in q.group]
    sel = [f"{e} AS \"{a}\"" for e, a in ge] + env.measure_sql(ms) + [f"COUNT(DISTINCT {d}) AS d_{d}" for d in ds]
    where = [f"month BETWEEN {q.months[0]} AND {q.months[1]}"] + [in_sql(c, v) for c, v in q.filters] + [Policy.scope_sql(conj)]
    sql = f"SELECT {', '.join(sel)} FROM {env.t} WHERE {' AND '.join(where)}"
    if ge:
        sql += " GROUP BY " + ", ".join(str(i + 1) for i in range(len(ge)))
    df, sec = env.run(sql)
    ans = answer_from(env, q, df, [a for _, a in ge])
    return ans, df, sec, sql


# ------------------------------------------------------------------------------------------------ workload
def gen_workload(env, n_calls, seed, ev_rate=1.0, replay=0.5, drift=0, crn=False):
    """Agent sessions (overview -> breakdown -> drill -> swap/compare/scalar/retry) interleaved with permission
    and semantic-layer events.  Returns a list of ('call', u, Query) | ('event', kind)."""
    rng = random.Random(seed)
    # crn: events draw from their own stream, so runs at different event rates issue the same calls
    # (common random numbers) and the events at a higher rate are a superset of those at a lower rate
    erng = random.Random(seed * 7919 + 17) if crn else rng
    sp = env.sp
    mets = list(sp["metrics"])
    mw = np.array([1.0 / (i + 1) ** 0.9 for i in range(len(mets))])
    dims = sp["dims"] + list(sp["mapped"])
    dw = np.array([1.0 / (i + 1) ** 0.7 for i in range(len(dims))])
    users = list(env.pol.users)
    uw = np.array([1.0 / (i + 1) ** 0.8 for i in range(len(users))])
    nrng = np.random.default_rng(seed)
    last_m = env.months[-1]
    mi = {m: i for i, m in enumerate(env.months)}
    rates = {"member_move": 4e-3, "revoke": 2e-3, "reactivate": 1e-3, "grant_edit": 2e-3, "col_edit": 1e-3, "republish": 1e-3}
    out, last_q = [], {}

    def window():
        end = max(0, len(env.months) - 1 - int(nrng.geometric(0.35)) + 1)
        L = rng.choice([1, 3, 3, 6, 12])
        return (env.months[max(0, end - L + 1)], env.months[end])

    def pick_filter_val(u, d):
        sc = env.pol.scope(u)
        if sc and d in sp["policy"]:
            for c in sc[0]:
                if d in c and rng.random() < 0.9:
                    return rng.choice(sorted(c[d], key=str))
        return rng.choice(sorted(env.domains[d], key=str)[:12])

    nsess = 0
    ncall = lambda: sum(1 for it in out if it[0] == "call") if crn else len(out)
    while ncall() < n_calls:
        nsess += 1
        if drift and nsess % drift == 0:          # interest drift: re-rank metric and dimension popularity
            rng.shuffle(mets); rng.shuffle(dims)
        u = users[int(nrng.choice(len(users), p=uw / uw.sum()))]
        M = [mets[int(nrng.choice(len(mets), p=mw / mw.sum()))]]
        if rng.random() < 0.4:
            M.append(mets[int(nrng.choice(len(mets), p=mw / mw.sum()))])
        M = list(dict.fromkeys(M))
        win = window()
        q = Query(M, ["month"], [], win)
        seq = [q]
        bd = None
        for _ in range(rng.randint(2, 8)):
            mv = rng.choices(["breakdown", "drill", "swap", "compare", "scalar", "retry"], [3, 3, 1.5, 1, 1, 1])[0]
            if mv == "breakdown" or bd is None:
                bd = dims[int(nrng.choice(len(dims), p=dw / dw.sum()))]
                q = Query(M, [bd], [], win)
            elif mv == "drill" and bd not in sp["mapped"]:
                d2 = rng.choice([d for d in dims if d != bd])
                q = Query(M, [d2], [(bd, [pick_filter_val(u, bd)])], win)
            elif mv == "swap":
                M = [rng.choice(mets)]
                q = Query(M, q.group, q.filters, q.months)
            elif mv == "compare":
                a, b = mi[q.months[0]], mi[q.months[1]]
                if a >= 12:
                    q = Query(M, q.group, q.filters, (env.months[a - 12], env.months[b - 12]))
            elif mv == "scalar":
                q = Query(M, [], q.filters, q.months)
            seq.append(q)
        for q in seq:
            for kind, p in rates.items():
                if erng.random() < p * ev_rate:
                    out.append(("event", kind))
                    if kind != "republish" and replay and erng.random() < replay:
                        out.append(("replay", None))
            out.append(("call", u, q))
    if crn:          # the same n_calls calls at every event rate; events and the replays they trigger come on top
        res, c = [], 0
        for it in out:
            if it[0] == "call":
                if c >= n_calls:
                    break
                c += 1
            res.append(it)
        return res
    return out[:n_calls]
