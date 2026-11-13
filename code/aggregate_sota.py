"""Recompute ScopeCache SOTA from v5 results: public setups + SYN-FG, no ERP.
Writes ../results/sota_no_erp.json and a markdown report. No fabricated numbers."""
from __future__ import annotations
import json, statistics as st, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
SETUPS = ["tpch", "tpcds", "bird", "ent", "synfg"]
NAME = {"tpch": "TPC-H", "tpcds": "TPC-DS", "bird": "BIRD", "ent": "ENT", "synfg": "SYN-FG"}
BASES = ["ViewRewrite", "PerScope", "PerScope+", "PerScope+V", "NoCache", "TTL", "Exact",
         "VR-adapt", "SC-snap", "SC-online"]
SAFE = ["Exact", "PerUser", "PerScope", "ViewRewrite", "ScopeCache", "SC-online", "SC-nolift",
        "SC-snap", "SC-atoms"]


def load(tag, setup, seed=0):
    p = RES / f"{tag}_{setup}_s{seed}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def red(sc, base):
    if base is None or base["n_exec"] == 0:
        return None
    return 1.0 - sc["n_exec"] / base["n_exec"]


def summarize():
    main = {}
    missing = []
    for s in SETUPS:
        main[s] = []
        for seed in (0, 1, 2):
            d = load("v5main", s, seed)
            if d is None:
                missing.append(f"v5main_{s}_s{seed}")
            else:
                main[s].append(d)
    report = {"missing": missing, "setups": SETUPS, "n_runs_present": sum(len(main[s]) for s in SETUPS)}
    # per-run and per-base
    runs = []
    for s in SETUPS:
        for d in main[s]:
            sc = d["methods"]["ScopeCache"]
            rec = {
                "setup": s, "seed": d["seed"],
                "sc_exec": sc["n_exec"], "sc_hit": sc["hit_rate"],
                "sc_wrong": sc["wrong"], "sc_overpriv": sc["overpriv"],
                "sc_rows": sc["rows_scanned"], "data_calls": sc["data_calls"],
            }
            for b in BASES:
                if b not in d["methods"]:
                    continue
                bm = d["methods"][b]
                r = red(sc, bm)
                rec[f"exec_{b}"] = bm["n_exec"]
                rec[f"hit_{b}"] = bm["hit_rate"]
                rec[f"red_{b}"] = r
                rec[f"cmp_{b}"] = "better" if sc["n_exec"] < bm["n_exec"] else (
                    "tie" if sc["n_exec"] == bm["n_exec"] else "worse")
            runs.append(rec)
    report["runs"] = runs

    def pack(base):
        xs = [r for r in runs if f"red_{base}" in r]
        if not xs:
            return None
        reds = [r[f"red_{base}"] for r in xs]
        return {
            "n": len(xs),
            "n_better": sum(r[f"cmp_{base}"] == "better" for r in xs),
            "n_tie": sum(r[f"cmp_{base}"] == "tie" for r in xs),
            "n_worse": sum(r[f"cmp_{base}"] == "worse" for r in xs),
            "red_min": min(reds), "red_max": max(reds), "red_median": st.median(reds),
            "red_mean": st.mean(reds),
        }

    report["vs"] = {b: pack(b) for b in BASES if pack(b)}
    hits = [r["sc_hit"] for r in runs]
    wrongs = [r["sc_wrong"] for r in runs]
    report["sc_hit_min"] = min(hits) if hits else None
    report["sc_hit_max"] = max(hits) if hits else None
    report["sc_wrong_total"] = sum(wrongs)
    # event sweep
    ev_rows = []
    for s in SETUPS:
        for ev in (0, 1, 4, 16):
            d = load(f"v5cev{ev}", s, 0)
            if d is None:
                missing.append(f"v5cev{ev}_{s}_s0")
                continue
            sc = d["methods"]["ScopeCache"]
            others = {m: d["methods"][m]["n_exec"] for m in ("PerScope", "ViewRewrite", "SC-snap", "PerScope+V")
                      if m in d["methods"]}
            best_o = min(others.values()) if others else None
            ev_rows.append({
                "setup": s, "ev": ev, "sc_exec": sc["n_exec"], "sc_hit": sc["hit_rate"],
                "sc_wrong": sc["wrong"], "others": others,
                "sc_best_or_tie": (sc["n_exec"] <= best_o) if best_o is not None else None,
            })
    report["event"] = ev_rows
    report["event_sc_best_or_tie"] = sum(1 for r in ev_rows if r["sc_best_or_tie"])
    report["event_n"] = len(ev_rows)
    return report, main


def markdown(report):
    lines = ["# ScopeCache SOTA without ERP (public setups + SYN-FG)", "",
             "All numbers from `results/v5main_*` and `results/v5cev*_*`. "
             "ERP runs are excluded. Nothing is fabricated.", ""]
    lines.append(f"Runs present: {report['n_runs_present']}. Missing: {report['missing'] or 'none'}.")
    lines.append(f"ScopeCache wrong answers (sum over present main runs): {report['sc_wrong_total']}.")
    if report["sc_hit_min"] is not None:
        lines.append(f"ScopeCache hit rate: {report['sc_hit_min']*100:.1f}--{report['sc_hit_max']*100:.1f}%.")
    lines.append("")
    lines.append("## Main grid, per run")
    lines.append("")
    lines.append("| setup | seed | SC exec | SC hit | vs VR | vs PerScope | vs PerScope+ | vs PerScope+V |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in report["runs"]:
        def cell(b):
            if f"red_{b}" not in r:
                return "—"
            return f"{r[f'red_{b}']*100:.1f}% ({r[f'cmp_{b}']})"
        lines.append(
            f"| {NAME.get(r['setup'], r['setup'])} | {r['seed']} | {r['sc_exec']} | {r['sc_hit']*100:.1f}% "
            f"| {cell('ViewRewrite')} | {cell('PerScope')} | {cell('PerScope+')} | {cell('PerScope+V')} |"
        )
    lines.append("")
    lines.append("## Counts against each baseline")
    lines.append("")
    for b, p in report["vs"].items():
        lines.append(
            f"- vs **{b}**: {p['n_better']}/{p['n']} better, {p['n_tie']} tie, {p['n_worse']} worse; "
            f"execution reduction {p['red_min']*100:.1f}--{p['red_max']*100:.1f}% "
            f"(median {p['red_median']*100:.1f}%, mean {p['red_mean']*100:.1f}%)."
        )
    if report["event"]:
        lines.append("")
        lines.append("## Event sweep (seed 0, CRN)")
        lines.append("")
        lines.append(f"ScopeCache best-or-tie in {report['event_sc_best_or_tie']}/{report['event_n']} cells.")
        for r in report["event"]:
            lines.append(
                f"- {NAME.get(r['setup'], r['setup'])} ev×{r['ev']}: SC exec={r['sc_exec']} "
                f"hit={r['sc_hit']*100:.1f}% wrong={r['sc_wrong']} others={r['others']} "
                f"best_or_tie={r['sc_best_or_tie']}"
            )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    report, _ = summarize()
    out_json = RES / "sota_no_erp.json"
    out_md = ROOT.parent / "SOTA_公开加SYNFG.md"
    # ROOT is impl/, parent is 03_方法与实验
    out_json.write_text(json.dumps(report, indent=2, default=str))
    Path(out_md).write_text(markdown(report))
    print(markdown(report))
    print(f"\nwrote {out_json} and {out_md}")
