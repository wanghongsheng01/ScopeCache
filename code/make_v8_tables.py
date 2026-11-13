"""Build markdown + LaTeX W/T/L summaries from v8rob / v8shift results."""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np

# reuse analyze
sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_v8 import load_tag, wtl, bootstrap, SETUPS, SETUP_LABEL, BOOT_SEED, B

OURS = "SC-adaptP"
HEAD = ["ScopeCache", "PerScope+V", "PerScope+", "VR-adapt", "ViewRewrite", "SC-online", "SC-atoms"]
LABEL = {"ScopeCache": "SC-hybrid", "PerScope+V": "PerScope+V", "PerScope+": "PerScope+",
         "VR-adapt": "VR-adapt", "ViewRewrite": "ViewRewrite", "SC-online": "SC-online",
         "SC-atoms": "SC-atoms"}


def marks(vals):
    """Return per-method (bold, under) flags. Lower is better. Ties share."""
    nums = [v for v in vals if v is not None]
    if not nums:
        return [(False, False)] * len(vals)
    best = min(nums)
    rest = [v for v in nums if v != best]
    second = min(rest) if rest else None
    out = []
    for v in vals:
        if v is None:
            out.append((False, False))
        elif v == best:
            out.append((True, False))
        elif second is not None and v == second:
            out.append((False, True))
        else:
            out.append((False, False))
    return out


def fmt(v, bold, under):
    s = str(int(v))
    if bold:
        return r"\textbf{" + s + "}"
    if under:
        return r"\underline{" + s + "}"
    return s


def summary(tag):
    cells = load_tag(tag)
    if not cells:
        return None
    rows = []
    by_m = {m: [] for m in [OURS] + HEAD}
    for c in cells:
        m = c["methods"]
        rec = dict(setup=c["setup"], seed=c["seed"],
                   chosen=m[OURS].get("adapt_chosen", ""),
                   ghost=m[OURS].get("stats", {}).get("ghost_hits", 0),
                   unpin=m[OURS].get("stats", {}).get("unpinned", 0),
                   wrong=sum(m[k].get("wrong", 0) for k in m),
                   execs={k: m[k]["n_exec"] for k in [OURS] + HEAD if k in m})
        rows.append(rec)
        for k in by_m:
            if k in m:
                by_m[k].append(m[k]["n_exec"])
    ours = np.array(by_m[OURS], dtype=float)
    vs = {}
    for b in HEAD:
        if len(by_m[b]) != len(ours):
            continue
        ba = np.array(by_m[b], dtype=float)
        w, t, l = wtl(ours, ba)
        boot = bootstrap(ours - ba)
        vs[b] = dict(w=w, t=t, l=l, total=int(ba.sum()),
                     ours=int(ours.sum()),
                     red=(ba.sum()-ours.sum())/ba.sum()*100,
                     ci=boot["ci_total"], p=boot["p_mean"],
                     wl_ci=boot["ci_wl"])
    return dict(tag=tag, n=len(rows), rows=rows, vs=vs, ours_total=int(ours.sum()),
                wl=cells[0].get("wl_preset"), seeds=sorted({r["seed"] for r in rows}))


def latex_wtl(s, caption, label):
    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{" + caption + "}",
        r"\label{" + label + "}",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{3.2pt}",
        r"\begin{tabular}{@{}lrrrrrrr@{}}",
        r"\toprule",
        r"vs.\ baseline & W & T & L & Ours & Base & vs.\ base & 95\% CI\\",
        r"\midrule",
    ]
    order = ["PerScope+V", "ScopeCache"] + [h for h in HEAD if h not in ("PerScope+V", "ScopeCache")]
    for b in order:
        if b not in s["vs"]:
            continue
        v = s["vs"][b]
        ci = v["ci"]
        wtl_s = f"{v['w']}--{v['t']}--{v['l']}"
        name = r"\M{" + LABEL[b] + "}"
        if b == "PerScope+V":
            wtl_s = r"\textbf{" + wtl_s + "}"
            name = r"\textbf{" + name + "}"
        lines.append(
            f"{name} & {v['w']} & {v['t']} & {v['l']} & "
            f"{s['ours_total']:,}".replace(",", "{,}") +
            f" & {v['total']:,}".replace(",", "{,}") +
            f" & {v['red']:.1f}\\% & [{ci[0]:.0f}, {ci[1]:.0f}]\\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    return "\n".join(lines)


def main():
    outdir = Path(__file__).resolve().parents[2]
    parts = []
    for tag, cap, lab in [
        ("v8rob",
         "Pre-registered robustness on unseen seeds 6--10, default Zipf workload, frozen SC-adaptP ($\\mathit{unpin\\_min}=40$). W--T--L and totals versus each baseline; 95\\% paired-bootstrap CI on the total-execution difference (seed 20261112, 10{,}000 replicates). This grid does not replace Table~\\ref{tab:main}.",
         "tab:rob"),
        ("v8shift",
         "Pre-registered shifted workload (\\texttt{flatmix}: Zipf exponents 0.2, 0.2, 0.2) on the same unseen seeds 6--10, frozen method. W--T--L versus each baseline; 95\\% CI as in Table~\\ref{tab:rob}. Declared before any shifted run.",
         "tab:shift"),
    ]:
        s = summary(tag)
        if not s:
            print(f"{tag}: no cells")
            continue
        print(f"==== {tag} n={s['n']} ours={s['ours_total']} ====")
        for b, v in s["vs"].items():
            print(f"  vs {b}: {v['w']}/{v['t']}/{v['l']}  {s['ours_total']} vs {v['total']}  "
                  f"{v['red']:+.1f}%  CI [{v['ci'][0]:.0f},{v['ci'][1]:.0f}] p={v['p']:.4f}")
        tex = latex_wtl(s, cap, lab)
        (outdir / "impl" / "results" / f"{tag}_wtl.tex").write_text(tex)
        parts.append((tag, s, tex))
    return parts

if __name__ == "__main__":
    main()
