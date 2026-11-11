"""Record real LLM-agent tool-call traces against a 7208-style governed query tool.

Each principal (a user from the setup's policy) is an analyst agent with a business task; the agent issues
`query` calls (metrics, dimensions, eq/in filters, time range) and sees the results under its own row scope
(row filter injected, Truman) or a rejection (hidden column / no grant).  Tasks are assigned uniformly at
random (no popularity skew), so cross-principal overlap comes only from what the agents choose to ask.
Output: results/agent/<setup>_<model>.jsonl (one line per tool call) and cost in the client's usage log."""
import os, sys, json, re, random, threading, time, argparse
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from engine import Env, Query, fresh, Policy
import llm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results", "agent")
PRICE = {"deepseek-chat": (0.27, 0.07, 1.10), "glm-4.5-flash": (0.0, 0.0, 0.0), "kimi-k2.6": (0.95, 0.16, 4.00),
         "gpt-6-sol": (5.0, 0.5, 20.0), "claude-opus-5-5": (5.0, 0.5, 25.0)}   # conservative placeholders for the spend guard  # $/M in-miss, in-hit, out (conservative)
CAP = {"deepseek": 4.0, "glm": 0.0, "kimi": 5.0, "gpt6": 60.0, "claude": 60.0}          # per-run spend guard in $, far below the $20/day/model limit

TASKS = {
 "tpch": ["How did revenue develop month by month over the last year, and which customer region drove the change?",
          "Which market segment has the highest discount rate this year, and is it rising?",
          "Compare gross sales by part manufacturer for the latest quarter against the same quarter last year.",
          "Which ship modes carry the most order lines, and how does average quantity differ across them?",
          "What is our margin rate by customer region over the last 6 months?",
          "Find the brand groups with the largest revenue in the last 3 months and break the top one down by nation.",
          "How does the returned-flag mix of order lines look by customer region this year?",
          "Which order priority levels generate the most revenue and the highest tax amounts?",
          "Which nations grew revenue the most comparing the last 6 months with the 6 months before?",
          "What is the maximum line price we saw per part type in the last year?",
          "Give a monthly trend of order lines and average quantity for the AUTOMOBILE segment.",
          "Which supplier regions contribute most to revenue for customers in EUROPE?",
          "What share of revenue comes from each part manufacturer, and which brands lead within the top manufacturer?",
          "Is the discount rate different across ship modes for the last quarter?",
          "Show revenue and margin by brand group for the last 12 months.",
          "Which customer nations have the highest average quantity per line this year?",
          "How many distinct customers bought from us each month in the last half year?",
          "Compare tax amounts across customer regions for the last two quarters.",
          "Which market segments in ASIA have the highest revenue in the last year?",
          "What were total gross sales and revenue last month, and how do they compare with a year earlier?"],
 "bird": ["How did total transaction volume develop month by month over the last year, and which region drove it?",
          "Which districts have the highest average transaction amount this year?",
          "Compare the credit share of transactions by region for the last quarter and the same quarter a year earlier.",
          "Which transaction operations account for the most transactions, and what is their average amount?",
          "What is the average balance by account statement frequency over the last 6 months?",
          "Which symbol groups dominate transaction volume in the last 3 months?",
          "Find the largest single transaction amount per region in the last year.",
          "How many distinct accounts were active each month in the last half year?",
          "Which k_symbol categories have the highest volume in the region with the most transactions?",
          "Compare transaction counts by transaction type across regions this year.",
          "Which districts grew transaction volume most comparing the last 6 months with the 6 months before?",
          "What is the monthly trend of credit share for monthly-statement accounts?",
          "Show volume and transactions by operation for the last 12 months.",
          "Which regions have the lowest minimum transaction amount, and is that driven by a particular operation?",
          "What were total volume and transaction count last month compared with a year earlier?",
          "Which districts in north Moravia have the highest volume this year?",
          "Break down average amount by transaction type and statement frequency for the last quarter.",
          "Which symbol groups have the highest average balance?",
          "How does volume per region compare between the first and second half of the last year?",
          "Which operations are most common for weekly-statement accounts?"],
 "ent": ["How did sales develop month by month over the last year, and which brand drove the change?",
         "Which channels have the highest refund rate this year, and is it rising?",
         "Compare gross margin by product line for the latest quarter against the same quarter last year.",
         "Which countries generate the most orders, and how does average order value differ across them?",
         "What is our gross profit by brand over the last 6 months?",
         "Find the categories with the largest sales in the last 3 months and break the top one down by channel.",
         "Which departments sold the most units this year?",
         "Which brands have the highest average order value in the top country?",
         "Which countries grew sales the most comparing the last 6 months with the 6 months before?",
         "What is the largest single order amount per channel in the last year?",
         "Give a monthly trend of orders and units for our biggest channel.",
         "How many distinct buyers did we have each month in the last half year?",
         "What share of sales comes from each product line, and which categories lead within the top line?",
         "Is the refund rate different across countries for the last quarter?",
         "Show sales and gross margin by brand for the last 12 months.",
         "Which departments have the best gross margin this year?",
         "Compare units sold by channel for the last two quarters.",
         "Which categories have the highest refund rate in the last 6 months?",
         "What were total sales and orders last month, and how do they compare with a year earlier?",
         "Which brands are growing fastest in units over the last quarter?"],
 "tpcds": ["How did net sales develop month by month over the last year, and which item category drove the change?",
           "Which states have the highest discount rate this year, and is it rising?",
           "Compare profit by item category for the latest quarter against the same quarter last year.",
           "Which stores sell the most units, and how do average units per line differ across them?",
           "What is our profit rate by item category over the last 6 months?",
           "Find the item classes with the largest net sales in the last 3 months and break the top one down by state.",
           "How does net sales split by customer gender and marital status this year?",
           "Which education levels generate the most gross sales and the highest profit?",
           "Which states grew net sales the most comparing the last 6 months with the 6 months before?",
           "What is the maximum sales price we saw per item category in the last year?",
           "Give a monthly trend of units and average units per line for the largest category.",
           "How many distinct customers bought from us each month in the last half year?",
           "What share of net sales comes from each category, and which classes lead within the top category?",
           "Is the markup different across stores for the last quarter?",
           "Show net sales and profit by item category for the last 12 months.",
           "Which states have the highest average units per line this year?",
           "Compare discount rates across education levels for the last two quarters.",
           "Which item classes have the highest profit rate in the last 6 months?",
           "What were total net sales and units last month, and how do they compare with a year earlier?",
           "Which stores are growing fastest in net sales over the last quarter?"],
}

SYS = """You are an analytics agent answering a business question for one employee over a governed data warehouse.
You can only access data through these tools; the warehouse applies the employee's row permissions silently and
rejects queries that use columns the employee may not see.

Tools (reply with exactly ONE JSON object per turn, nothing else):
1. {{"tool": "list_dimension_values", "args": {{"dimension": "<name>"}}}}  -> up to 30 values of a dimension
2. {{"tool": "query", "args": {{"metrics": [...], "dimensions": [...], "filters": [{{"field": "<dim>", "op": "in", "values": [...]}}], "time_range": {{"start": "YYYY-MM", "end": "YYYY-MM"}}}}}}
   - metrics: 1-3 names from the catalog; dimensions: 0-2 names (use "month" for a monthly series)
   - filters: optional, op is "eq" or "in"
3. {{"answer": "<final answer in 1-3 sentences>"}}  -> finish

Catalog
Metrics: {metrics}
Dimensions: {dims}
Data covers {m0} to {m1}; "now" is {m1}.
Use at most 6 tool calls. Return JSON only."""


def catalog(env):
    sp = env.sp
    mets = "; ".join(f"{m} = {('COUNT DISTINCT ' + f.split(':')[1]) if f.startswith('DISTINCT:') else f}" for m, f in sp["metrics"].items())
    dims = []
    for d in sp["dims"]:
        dims.append(f"{d} ({len(env.domains[d])} values)")
    for d, (src, _) in sp["mapped"].items():
        dims.append(f"{d} (groups of {src})")
    dims.append("month")
    return mets, ", ".join(dims)


def ym(m):
    return f"{m // 100:04d}-{m % 100:02d}"


def parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*", "", text).rstrip("`").strip()
    i = text.find("{")
    if i < 0:
        return None
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[i:j + 1])
                except Exception:
                    return None
    return None


class Runner:
    def __init__(self, setup, model, n_users, tasks_per_user, seed, workers):
        self.env = Env(setup, seed, 400)
        self.setup, self.model, self.seed, self.workers = setup, model, seed, workers
        self.lock = threading.Lock()
        self.rng = random.Random(seed)
        users = [u for u in self.env.pol.users if self.env.pol.scope(u) is not None]
        self.users = self.rng.sample(users, n_users)
        self.episodes = [(u, t) for u in self.users for t in self.rng.sample(range(len(TASKS[setup])), tasks_per_user)]
        self.rng.shuffle(self.episodes)
        mets, dims = catalog(self.env)
        self.sys = SYS.format(metrics=mets, dims=dims, m0=ym(self.env.months[0]), m1=ym(self.env.months[-1]))
        self.cost = 0.0
        self.calls = []

    def spend(self, r):
        name = r["model"]; u = r.get("usage", {})
        pin, phit, pout = PRICE.get(name, (1.0, 1.0, 4.0))
        hit = u.get("prompt_cache_hit_tokens", u.get("prompt_tokens_details", {}).get("cached_tokens", 0) or 0)
        miss = u.get("prompt_tokens", 0) - hit
        return (miss * pin + hit * phit + u.get("completion_tokens", 0) * pout) / 1e6

    def to_query(self, a):
        sp, env = self.env.sp, self.env
        mets = a.get("metrics") or []
        if isinstance(mets, str):
            mets = [mets]
        if not mets or any(m not in sp["metrics"] for m in mets):
            return None, f"unknown metric; choose from {list(sp['metrics'])}"
        dims = a.get("dimensions") or []
        if isinstance(dims, str):
            dims = [dims]
        ok = set(sp["dims"]) | set(sp["mapped"]) | {"month"}
        if any(d not in ok for d in dims) or len(dims) > 2:
            return None, f"unknown dimension; choose up to 2 from {sorted(ok)}"
        filters = []
        for f in a.get("filters") or []:
            fld = f.get("field"); vals = f.get("values", f.get("value"))
            if not isinstance(vals, list):
                vals = [vals]
            if fld not in sp["dims"]:
                return None, f"filter field must be one of {sp['dims']}"
            dom = {str(v): v for v in env.domains[fld]}
            vv = [dom[str(v)] for v in vals if str(v) in dom]
            if not vv:
                return None, f"no valid values for {fld}; use list_dimension_values"
            filters.append((fld, vv))
        tr = a.get("time_range") or {}
        def mm(s, default):
            try:
                y, m = str(s)[:7].split("-"); return int(y) * 100 + int(m)
            except Exception:
                return default
        m1 = mm(tr.get("end"), env.months[-1]); m0 = mm(tr.get("start"), env.months[max(0, len(env.months) - 12)])
        m0 = min(max(m0, env.months[0]), env.months[-1]); m1 = min(max(m1, env.months[0]), env.months[-1])
        if m0 > m1:
            m0, m1 = m1, m0
        m0 = min(m for m in env.months if m >= m0); m1 = max(m for m in env.months if m <= m1)
        return Query(list(dict.fromkeys(mets)), list(dict.fromkeys(dims)), filters, (m0, m1)), None

    def episode(self, ep_id):
        u, t = self.episodes[ep_id]
        if self.cost >= CAP[self.model] and CAP[self.model] > 0:
            return
        msgs = [{"role": "system", "content": self.sys}, {"role": "user", "content": TASKS[self.setup][t]}]
        for step in range(8):
            try:
                r = llm.chat(self.model, msgs, temperature=0.0, max_tokens=400)
            except Exception as e:
                return
            with self.lock:
                self.cost += self.spend(r)
            act = parse_json(r["text"])
            msgs.append({"role": "assistant", "content": r["text"][:2000]})
            if not act or "answer" in act or "tool" not in act:
                return
            a = act.get("args") or {}
            if act["tool"] == "list_dimension_values":
                d = a.get("dimension")
                res = {"values": [str(v) for v in sorted(self.env.domains[d], key=str)[:30]]} if d in self.env.domains else {"error": "unknown dimension"}
            elif act["tool"] == "query":
                q, err = self.to_query(a)
                if err:
                    res = {"error": err}
                else:
                    with self.lock:
                        ans, df, sec, sql = fresh(self.env, u, q)
                        self.calls.append({"ep": ep_id, "step": step, "user": u, "task": t, "metrics": list(q.metrics), "group": list(q.group),
                                           "filters": [[c, list(v)] for c, v in q.filters], "months": list(q.months),
                                           "result": ans if isinstance(ans, str) else "rows", "n_rows": 0 if isinstance(ans, str) else len(ans)})
                    if isinstance(ans, str):
                        res = {"error": {"DENY": "permission denied: a requested metric uses a column you may not see",
                                         "NOGRANT": "no data permission"}[ans]}
                    else:
                        items = sorted(ans.items(), key=lambda kv: -(kv[1][0] if kv[1][0] == kv[1][0] else -1e300))[:20]
                        res = {"columns": list(q.group) + list(q.metrics),
                               "rows": [[*map(str, k), *[round(x, 2) if x == x else None for x in v]] for k, v in items], "total_rows": len(ans)}
            else:
                res = {"error": "unknown tool"}
            msgs.append({"role": "user", "content": "TOOL RESULT: " + json.dumps(res, default=str)[:3000]})

    def run(self):
        with ThreadPoolExecutor(self.workers) as ex:
            list(ex.map(self.episode, range(len(self.episodes))))
        os.makedirs(OUT, exist_ok=True)
        path = os.path.join(OUT, f"{self.setup}_{self.model}" + (f"_s{self.seed}" if self.seed else "") + ".jsonl")
        with open(path, "w") as f:
            for c in sorted(self.calls, key=lambda c: (self.episodes.index((c["user"], c["task"])), c["step"])):
                f.write(json.dumps(c) + "\n")
        return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("setup"); ap.add_argument("model"); ap.add_argument("--users", type=int, default=30)
    ap.add_argument("--tasks", type=int, default=5); ap.add_argument("--seed", type=int, default=0); ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    t0 = time.time()
    R = Runner(a.setup, a.model, a.users, a.tasks, a.seed, a.workers)
    p = R.run()
    print(json.dumps({"setup": a.setup, "model": a.model, "episodes": len(R.episodes), "tool_calls": len(R.calls),
                      "cost_usd_est": round(R.cost, 3), "minutes": round((time.time() - t0) / 60, 1), "out": p}))
