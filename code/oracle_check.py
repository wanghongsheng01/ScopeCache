"""Independent oracle check: recompute sampled fresh answers entirely in SQL (metric formulas evaluated by DuckDB
with NULLIF denominators, no shared pandas code) and compare them with the oracle the experiments use
(engine.fresh, which aggregates in SQL and applies formulas in numpy).  Policy and semantic-layer events are
applied in trace order, so every sampled call is checked under the policy and snapshot current at the call.
Writes results/oracle_check.json."""
import os, re, json, math, sys
from engine import Env, gen_workload, fresh, same, Policy, in_sql
from run import apply_event

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGG = {"sum": "SUM({})", "count": "COUNT({})", "max": "MAX({})", "min": "MIN({})"}


def to_sql(formula, measures):
    toks = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+\.?\d*|[()+\-*/]", formula)

    def operand(i):
        if toks[i] == "(":
            depth, j = 0, i
            while True:
                depth += toks[j] == "("; depth -= toks[j] == ")"
                if depth == 0:
                    break
                j += 1
            return "(" + expr(toks[i + 1:j]) + ")", j + 1
        return atom(toks[i]), i + 1

    def atom(t):
        if t in measures:
            agg, e, _ = measures[t]
            return "CAST(" + AGG[agg].format(e) + " AS DOUBLE)"
        return t

    def expr(ts):
        nonlocal toks
        saved, toks = toks, ts
        out, i = [], 0
        while i < len(toks):
            t = toks[i]
            if t == "/":
                o, i = operand(i + 1)
                out.append("/NULLIF(" + o + ", 0)")
            elif t == "(" or re.match(r"[A-Za-z_\d]", t):
                o, i = operand(i)
                out.append(o)
            else:
                out.append(t); i += 1
        toks = saved
        return " ".join(out)
    return expr(toks)


def independent(env, u, q):
    sc = env.pol.scope(u)
    if sc is None:
        return "NOGRANT"
    conj, cols = sc
    need = {c for m in q.metrics for c in env.sem.cols_of(m)}
    if (need & set(env.sp["sensitive"])) - cols:
        return "DENY"
    sel, keys = [], []
    for g in q.group:
        e, a = env.gexpr(g)
        sel.append(f"{e} AS \"{a}\""); keys.append(a)
    for i, m in enumerate(q.metrics):
        f = env.sem.metrics[m]
        sel.append((f"CAST(COUNT(DISTINCT {f.split(':', 1)[1]}) AS DOUBLE)" if f.startswith("DISTINCT:") else to_sql(f, env.sem.measures)) + f" AS v{i}")
    where = [f"month BETWEEN {q.months[0]} AND {q.months[1]}"] + [in_sql(c, v) for c, v in q.filters] + [Policy.scope_sql(conj)]
    sql = f"SELECT {', '.join(sel)} FROM {env.t} WHERE {' AND '.join(where)}"
    if keys:
        sql += " GROUP BY " + ", ".join(str(i + 1) for i in range(len(keys)))
    sql += " HAVING COUNT(*) > 0"
    df = env.con.execute(sql).df()
    out = {}
    for row in df.itertuples(index=False):
        k = tuple(None if (v is None or (isinstance(v, float) and math.isnan(v))) else v for v in row[:len(keys)])
        out[k] = tuple(float("nan") if v is None else float(v) for v in row[len(keys):])
    return out


if __name__ == "__main__":
    setups = sys.argv[1:] or ["tpch", "tpcds", "bird", "ent", "erp"]
    every = 10
    res = {}
    for s in setups:
        env = Env(s, 0, 400)
        wl = gen_workload(env, 3000, 0, 1.0)
        n = agree = 0
        mism = []
        ci = 0
        for it in wl:
            if it[0] == "event":
                apply_event(env, it[1])
                continue
            if it[0] != "call":
                continue
            ci += 1
            if ci % every:
                continue
            _, u, q = it
            a = fresh(env, u, q)[0]
            b = independent(env, u, q)
            n += 1
            if same(a, b):
                agree += 1
            elif len(mism) < 5:
                mism.append(str(q.key())[:200])
        res[s] = {"checked": n, "agree": agree, "mismatch_examples": mism}
        print(s, res[s], flush=True)
        env.con.close()
    json.dump(res, open(os.path.join(ROOT, "results", "oracle_check.json"), "w"), indent=1)
