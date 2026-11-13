"""W/T/L, totals, and paired bootstrap CIs (seed 20261112, B=10000).

Usage:
  python analyze_v8.py              # v8rob + v8shift if present; also v7fresh
  python analyze_v8.py --tag v8rob
  python analyze_v8.py --tag v7fresh --ours SC-adaptP --baselines ScopeCache,PerScope+V
"""
from __future__ import annotations

import argparse, json, math, sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
BOOT_SEED = 20261112
B = 10_000
SETUPS = ["tpch", "tpcds", "bird", "ent", "synfg"]
SETUP_LABEL = {"tpch": "TPC-H", "tpcds": "TPC-DS", "bird": "BIRD", "ent": "ENT", "synfg": "SYN-FG"}


def load_tag(tag: str):
    cells = []
    for p in sorted(RESULTS.glob(f"{tag}_*_s*.json")):
        d = json.loads(p.read_text())
        cells.append(d)
    cells.sort(key=lambda d: (SETUPS.index(d["setup"]) if d["setup"] in SETUPS else 99, d["seed"]))
    return cells


def wtl(ours, base):
    w = t = l = 0
    for a, b in zip(ours, base):
        if a < b:
            w += 1
        elif a == b:
            t += 1
        else:
            l += 1
    return w, t, l


def bootstrap(diff, seed=BOOT_SEED, b=B):
    """diff = ours - base (negative is better). Returns CI and two-sided p for mean=0."""
    rng = np.random.default_rng(seed)
    n = len(diff)
    idx = rng.integers(0, n, size=(b, n))
    # totals and means of resampled diffs
    samp = diff[idx]
    tot = samp.sum(axis=1)
    mean = samp.mean(axis=1)
    # W-L on each resample
    wl = (samp < 0).sum(axis=1) - (samp > 0).sum(axis=1)
    def ci(x):
        return float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))
    # two-sided p: twice the tail beyond 0, for the mean
    p = 2 * min((mean >= 0).mean(), (mean <= 0).mean())
    p = float(min(1.0, p))
    return dict(
        n=n,
        obs_total=float(diff.sum()),
        obs_mean=float(diff.mean()),
        ci_total=ci(tot),
        ci_mean=ci(mean),
        ci_wl=ci(wl),
        p_mean=p,
    )


def fmt_ci(pair, nd=1):
    lo, hi = pair
    return f"[{lo:.{nd}f}, {hi:.{nd}f}]"


def summarize(cells, ours_name, baselines, title):
    if not cells:
        print(f"## {title}\n(no cells)\n")
        return None
    methods_present = set()
    for c in cells:
        methods_present |= set(c["methods"])
    lines = [f"## {title}", ""]
    lines.append(f"cells={len(cells)}  wl_preset={cells[0].get('wl_preset','?')}  "
                 f"seeds={sorted({c['seed'] for c in cells})}  "
                 f"setups={[c['setup'] for c in cells][:3]}...")
    # per-cell table
    header = ["setup", "seed", ours_name] + [b for b in baselines if b in methods_present]
    # chosen, unpin for ours
    extra = ["chosen", "ghost", "unpin", "wrong"]
    rows = []
    ours_exec = []
    base_exec = {b: [] for b in header[3:]}
    for c in cells:
        m = c["methods"]
        if ours_name not in m:
            continue
        o = m[ours_name]
        row = {
            "setup": c["setup"],
            "seed": c["seed"],
            ours_name: o["n_exec"],
            "chosen": o.get("adapt_chosen", ""),
            "ghost": o.get("stats", {}).get("ghost_hits", ""),
            "unpin": o.get("stats", {}).get("unpinned", ""),
            "wrong": o.get("wrong", 0),
        }
        ours_exec.append(o["n_exec"])
        for b in header[3:]:
            row[b] = m[b]["n_exec"] if b in m else None
            if b in m:
                base_exec[b].append(m[b]["n_exec"])
        # sanity
        for name in m:
            if m[name].get("wrong", 0):
                row["wrong"] = f"{row['wrong']}/{name}:{m[name]['wrong']}"
        rows.append(row)

    lines.append("")
    cols = ["setup", "seed", ours_name] + header[3:] + extra
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")

    ours_arr = np.array(ours_exec, dtype=float)
    lines.append("")
    lines.append(f"ours total = {int(ours_arr.sum())}")
    stats_out = {"title": title, "n": len(ours_arr), "ours_total": int(ours_arr.sum()), "vs": {}}
    for b, vals in base_exec.items():
        if len(vals) != len(ours_arr):
            lines.append(f"{b}: incomplete ({len(vals)} vs {len(ours_arr)})")
            continue
        ba = np.array(vals, dtype=float)
        w, t, l = wtl(ours_arr, ba)
        diff = ours_arr - ba
        boot = bootstrap(diff)
        red = (ba.sum() - ours_arr.sum()) / ba.sum() * 100 if ba.sum() else 0
        lines.append(
            f"vs {b}: {w}/{t}/{l}  ours {int(ours_arr.sum())} vs {int(ba.sum())}  "
            f"({red:+.1f}% exec)  Δtotal={boot['obs_total']:+.0f}  "
            f"95% CI {fmt_ci(boot['ci_total'], 0)}  "
            f"Δmean={boot['obs_mean']:+.2f} CI {fmt_ci(boot['ci_mean'], 2)}  "
            f"W−L CI {fmt_ci(boot['ci_wl'], 0)}  p={boot['p_mean']:.4f}"
        )
        stats_out["vs"][b] = dict(w=w, t=t, l=l, base_total=int(ba.sum()),
                                  red_pct=red, **{k: (list(v) if isinstance(v, tuple) else v)
                                                  for k, v in boot.items()})
    text = "\n".join(lines) + "\n"
    print(text)
    return stats_out, text, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=None)
    ap.add_argument("--ours", default="SC-adaptP")
    ap.add_argument("--baselines", default="ScopeCache,PerScope+V,PerScope+,VR-adapt,ViewRewrite,SC-online,SC-atoms")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    baselines = [x for x in a.baselines.split(",") if x]
    tags = [a.tag] if a.tag else ["v7fresh", "v8rob", "v8shift"]
    all_text = [f"# ScopeCache analysis  (bootstrap seed {BOOT_SEED}, B={B})", ""]
    bundle = {}
    for tag in tags:
        cells = load_tag(tag)
        if not cells:
            all_text.append(f"## {tag}\n(no cells yet)\n")
            print(f"## {tag}\n(no cells yet)\n")
            continue
        bl = baselines
        if tag == "v7fresh":
            bl = [x for x in ("ScopeCache", "PerScope+V") if any(x in c["methods"] for c in cells)]
        res = summarize(cells, a.ours, bl, tag)
        if res:
            stats, text, rows = res
            bundle[tag] = stats
            all_text.append(text)
    if a.out:
        Path(a.out).write_text("\n".join(all_text) + "\n")
        jpath = Path(a.out).with_suffix(".json")
        # numpy types
        def conv(o):
            if isinstance(o, (np.floating,)):
                return float(o)
            if isinstance(o, (np.integer,)):
                return int(o)
            if isinstance(o, dict):
                return {k: conv(v) for k, v in o.items()}
            if isinstance(o, (list, tuple)):
                return [conv(x) for x in o]
            return o
        jpath.write_text(json.dumps(conv(bundle), indent=2))
        print(f"wrote {a.out} and {jpath}")


if __name__ == "__main__":
    main()
