"""Collect setup_stats for SYN-FG (seed 0 policy) and merge into a copy of setup_stats.json.
Does not overwrite the released file; writes setup_stats_vldb.json."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import Env
from datasets import spec
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"

def stats_for(name, seed=0):
    env = Env(name, seed=seed)
    voc = env.pol.vocabulary()
    classes = {a: (max(voc[a].values()) + 1 if voc[a] else 0) for a in voc}
    # blocks: class-id tuples of present policy combos
    blocks = set()
    for _, row in env.combos.iterrows():
        try:
            blocks.add(tuple(voc[a][row[a]] for a in env.sp["policy"]))
        except KeyError:
            continue
    from synfg import policy_stats
    ps = policy_stats(env.pol) if env.sp.get("synfg") else {}
    out = {
        "rows": int(sum(env.month_rows.values())),
        "months": len(env.months),
        "policy": {a: len(env.domains[a]) for a in env.sp["policy"]},
        "dims": {d: len(env.domains[d]) for d in env.sp["dims"] if d in env.domains},
        "combos": int(len(env.combos)),
        "blocks": len(blocks),
        "classes": classes,
        "roles": len(env.pol.roles),
        "groups": len(env.pol.groups),
        "users": len(env.pol.users),
        "distinct_scopes": ps.get("distinct_scopes") or len({env.pol.scope_key(env.pol.scope(u))
            for u, us in env.pol.users.items() if us["active"]}),
        "measures": len(env.sp["measures"]),
        "metrics": len(env.sp["metrics"]),
        "sensitive": list(env.sp["sensitive"]),
        "mapped": list(env.sp.get("mapped", {})),
    }
    if ps:
        out["synfg_policy"] = {k: ps[k] for k in ps if k != "occupancy_hist"}
        out["users_per_scope_median"] = ps["users_per_scope_median"]
        out["users_per_scope_mean"] = ps["users_per_scope_mean"]
    env.con.close()
    return out

if __name__ == "__main__":
    released = json.loads((RES / "setup_stats.json").read_text())
    # drop any temptation to carry ERP
    released.pop("erp", None)
    released["synfg"] = stats_for("synfg", 0)
    out = RES / "setup_stats_vldb.json"
    out.write_text(json.dumps(released, indent=2))
    print(json.dumps(released["synfg"], indent=2))
    print("wrote", out)
