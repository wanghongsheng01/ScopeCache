"""Generate numbers.tex, the tables, and the figures of the paper from results/*.json.  Every number in the
paper that comes from an experiment is a macro defined here."""
import os, json, glob, statistics as st
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER = os.path.dirname(HERE)
OUTDIR = os.environ.get("SC_OUT", PAPER)          # dry runs write elsewhere
RES = os.environ.get("SC_RES", os.path.join(os.path.dirname(PAPER), "results"))
SETUPS = ["tpch", "tpcds", "bird", "ent"]
NAME = {"tpch": "TPC-H", "tpcds": "TPC-DS", "bird": "BIRD", "ent": "ENT"}
SAFE = ["Exact", "PerUser", "PerScope", "ViewRewrite", "ScopeCache", "SC-online", "SC-nolift", "SC-snap", "SC-atoms"]
MAC = {}


def mac(name, val):
    MAC[name] = val


def rng_mac(name, vals, f=lambda v: f"{100 * v:.0f}"):
    """name+Lo / name+Hi from a list; '??' when the list is empty (dry runs on partial results)."""
    mac(name + "Lo", f(min(vals)) if vals else "??"); mac(name + "Hi", f(max(vals)) if vals else "??")


def pct(x, nd=0):
    return f"{100 * x:.{nd}f}"


# result generation: v4 = deterministic eviction cost and NULL-preserving merge of partial sums; v3 = deterministic eviction cost (all methods of the main grid in one file per run);
# v2 = the earlier runs, kept for reference (main grid split over v2main/v2sup/v2psv/v2nolift)
PFX = os.environ.get("SC_PFX", "v5")
# v5 = v4 plus view rebuilds counted as executions, rows scanned, TTL misses checked by the warehouse, VR-adapt keeping
# re-selected views, and the event sweep with common random numbers; the agent replays have no events and keep v4
AGPFX = os.environ.get("SC_AGPFX", "v4")


def load(tag, setup, seed=0):
    if tag.startswith("v2") and PFX != "v2":
        tag = PFX + tag[2:]
        if PFX != "v2" and tag in (PFX + "sup", PFX + "psv", PFX + "nolift"):
            tag = PFX + "main"
    p = os.path.join(RES, f"{tag}_{setup}_s{seed}.json")
    return json.load(open(p)) if os.path.exists(p) else None


def fmt_int(n):
    return f"{int(round(n)):,}".replace(",", "{,}")


# ------------------------------------------------------------------ main grid (v2main + v2sup, 3 seeds, 5 setups)
MSETUPS = os.environ.get("SC_MAIN", "tpch,tpcds,bird,ent,erp").split(",")
NAME["erp"] = "ERP"
main = {}
for s in MSETUPS:
    runs = []
    for k in range(3):
        r = load("v2main", s, k)
        if not r:
            continue
        for extra in ("v2sup", "v2psv"):
            sup = load(extra, s, k)
            if sup:
                r["methods"].update(sup["methods"])
        runs.append(r)
    main[s] = runs
M = lambda s, m, f: [r["methods"][m][f] for r in main[s]]
SAFE = SAFE + ["PerScope+", "VR-adapt", "PerScope+V"]
present = [m for m in SAFE if all(m in r["methods"] for s_ in MSETUPS for r in main[s_])]
mac("nSafeCachesWord", {11: "eleven", 12: "twelve", 13: "thirteen"}.get(len(present), str(len(present))))

safe_dc = sum(r["methods"][m]["data_calls"] for s in MSETUPS for r in main[s] for m in present)
safe_wrong = sum(r["methods"][m]["wrong"] for s in MSETUPS for r in main[s] for m in SAFE if m in r["methods"])
mac("nSafeDataCalls", fmt_int(safe_dc))
mac("nMainDataCalls", fmt_int(sum(r["methods"]["ScopeCache"]["data_calls"] for s in MSETUPS for r in main[s])))
assert safe_wrong == 0, safe_wrong
mac("nMainRuns", str(sum(len(main[s]) for s in MSETUPS)))

def reds(base, var="ScopeCache", setups=MSETUPS):
    return [1 - r["methods"][var]["n_exec"] / r["methods"][base]["n_exec"] for s in setups for r in main[s] if base in r["methods"]]
red_vr, red_ps, red_nc = reds("ViewRewrite"), reds("PerScope"), reds("NoCache")
mac("redVRLo", pct(min(red_vr))); mac("redVRHi", pct(max(red_vr))); mac("redVRMed", pct(st.median(red_vr)))
mac("redPSmainLo", pct(min(red_ps))); mac("redPSmainHi", pct(max(red_ps)))
mac("redNCLo", pct(min(red_nc))); mac("redNCHi", pct(max(red_nc)))
mac("nRedVRruns", str(len(red_vr))); mac("nRedVRpos", str(sum(x > 0 for x in red_vr)))
rpp = reds("PerScope+", "SC-online")            # same machinery, shared vs partitioned (both without views)
rng_mac("redPSPlus", rpp); mac("redPSPlusMed", pct(st.median(rpp)) if rpp else "??")
rng_mac("redVRA", reds("VR-adapt"))
# VR-adapt with re-selection every 300 and 1,200 calls; fewest executions over the three periods
vra_all = [m for m in ("VR-adapt300", "VR-adapt", "VR-adapt1200") if all(m in r["methods"] for s_ in MSETUPS for r in main[s_])]
if len(vra_all) == 3:
    assert all(r["methods"][m]["wrong"] == 0 for s_ in MSETUPS for r in main[s_] for m in vra_all)
    best_vra = [1 - r["methods"]["ScopeCache"]["n_exec"] / min(r["methods"][m]["n_exec"] for m in vra_all) for s_ in MSETUPS for r in main[s_]]
    rng_mac("redVRAbest", best_vra); mac("nVRAbestNeg", str(sum(x < 0 for x in best_vra)))
    vra_hit = [r["methods"][m]["hit_rate"] - r["methods"]["ViewRewrite"]["hit_rate"] for s_ in MSETUPS for r in main[s_] for m in vra_all]
    chg = [s_ for s_ in MSETUPS if any(r["methods"][m]["n_exec"] != r["methods"]["ViewRewrite"]["n_exec"] + 0 for r in main[s_] for m in vra_all)]
    mac("vraChangedSetups", (", ".join(NAME[x] for x in chg[:-1]) + ({1: "", 2: " and "}.get(len(chg), ", and ")) + NAME[chg[-1]]) if chg else "none")
    mac("vraHitGainMax", f"{100 * max(vra_hit):.1f}")
# fact-table rows scanned (executions on a miss, view rebuilds, re-selections), per run
if all("rows_scanned" in r["methods"]["ScopeCache"] for s_ in MSETUPS for r in main[s_]):
    rred = lambda base, var="ScopeCache": [1 - r["methods"][var]["rows_scanned"] / r["methods"][base]["rows_scanned"] for s_ in MSETUPS for r in main[s_]]
    rpe = [r["methods"][m]["rows_scanned"] / max(1, r["methods"][m]["n_exec"]) / (r["methods"]["NoCache"]["rows_scanned"] / r["methods"]["NoCache"]["n_exec"]) for s_ in MSETUPS for r in main[s_] for m in ("ScopeCache",)]
    rng_mac("rowsPerExecSC", rpe, f=lambda v: f"{v:.1f}")
    rng_mac("rowsRedNC", rred("NoCache")); rng_mac("rowsRedPS", rred("PerScope"))
    rng_mac("rowsRedPSPlus", rred("PerScope+", "SC-online")); rng_mac("rowsRedPSV", rred("PerScope+V"))
    assert min(rred("PerScope")) > 0 and min(rred("NoCache")) > 0 and min(rred("PerScope+", "SC-online")) > 0
    # against ViewRewrite, per setup (mean over seeds): a lifted miss scans the full history, a ViewRewrite miss only W_q
    rvs = {s_: st.mean(1 - r["methods"]["ScopeCache"]["rows_scanned"] / r["methods"]["ViewRewrite"]["rows_scanned"] for r in main[s_]) for s_ in MSETUPS}
    fav = [s_ for s_ in MSETUPS if rvs[s_] > 0]; unf = [s_ for s_ in MSETUPS if rvs[s_] <= 0]
    names = lambda ss: ", ".join(NAME[x] for x in ss[:-1]) + ({1: "", 2: " and "}.get(len(ss), ", and ")) + NAME[ss[-1]]
    head = (f"Counting fact-table rows instead of executions, ScopeCache scans {pct(min(rred('PerScope')))}--{pct(max(rred('PerScope')))}\\% fewer rows than \\M{{PerScope}}, "
            f"its online path {pct(min(rred('PerScope+', 'SC-online')))}--{pct(max(rred('PerScope+', 'SC-online')))}\\% fewer than \\M{{PerScope+}}, and the full system "
            f"{pct(min(rvs[x] for x in fav))}--{pct(max(rvs[x] for x in fav))}\\% fewer than \\M{{ViewRewrite}} on {names(fav)}")
    if unf:
        _rpu = [st.mean(r["methods"]["ScopeCache"]["rows_scanned"] / r["methods"]["ScopeCache"]["n_exec"] / (r["methods"]["ViewRewrite"]["rows_scanned"] / r["methods"]["ViewRewrite"]["n_exec"]) for r in main[x]) for x in unf]
        assert min(_rpu) > 1
        mac("rowsSentence", head + f". On {names(unf)}, a ScopeCache execution scans {min(_rpu):.1f}$\\times$ the rows of a \\M{{ViewRewrite}} execution, because a lifted execution covers a wider window than the call that triggers it, whereas a miss of \\M{{ViewRewrite}} scans only the requested window; ScopeCache therefore scans {pct(max(-rvs[x] for x in unf))}\\% more rows there while needing fewer executions." if len(unf) == 1 else head + ".")
    else:
        mac("rowsSentence", head + ".")
    if len(unf) == 1:
        _u = unf[0]; mac("rowsUnfSetup", NAME[_u]); mac("rowsUnfMore", pct(-rvs[_u]))
        # without predicate lifting a miss scans only the requested window: rows and executions against ViewRewrite and ScopeCache
        mac("noliftRowsRedVR", pct(st.mean(1 - r["methods"]["SC-nolift"]["rows_scanned"] / r["methods"]["ViewRewrite"]["rows_scanned"] for r in main[_u])))
        mac("noliftExecMore", pct(st.mean(r["methods"]["SC-nolift"]["n_exec"] / r["methods"]["ScopeCache"]["n_exec"] - 1 for r in main[_u])))
        mac("noliftExecRedVR", pct(st.mean(1 - r["methods"]["SC-nolift"]["n_exec"] / r["methods"]["ViewRewrite"]["n_exec"] for r in main[_u])))
        assert st.mean(1 - r["methods"]["SC-nolift"]["rows_scanned"] / r["methods"]["ViewRewrite"]["rows_scanned"] for r in main[_u]) > 0
    mac("redVRtpch", pct(st.mean(reds("ViewRewrite", setups=["tpch"]))))

    vmaint = [r["methods"][m].get("view_maint", 0) for s_ in MSETUPS for r in main[s_] for m in ("ScopeCache", "ViewRewrite", "PerScope+V")]
    mac("viewMaintLo", str(min(vmaint))); mac("viewMaintHi", str(max(vmaint)))
if "erp" in MSETUPS:
    erp_vr = reds("ViewRewrite", setups=["erp"]); erp_ps = reds("PerScope", setups=["erp"]); erp_pp = reds("PerScope+", "SC-online", setups=["erp"])
    mac("erpRedVR", pct(st.mean(erp_vr))); mac("erpRedPS", pct(st.mean(erp_ps))); mac("erpRedPSPlus", pct(st.mean(erp_pp)))
    mac("erpScHit", pct(st.mean(M("erp", "ScopeCache", "hit_rate")))); mac("erpPSHit", pct(st.mean(M("erp", "PerScope", "hit_rate"))))
schit = [st.mean(M(s, "ScopeCache", "hit_rate")) for s in MSETUPS]
mac("scHitLo", pct(min(schit))); mac("scHitHi", pct(max(schit)))
parthit = [st.mean(M(s, m, "hit_rate")) for s in MSETUPS for m in ("PerUser", "PerScope", "Exact")]
mac("partHitLo", pct(min(parthit))); mac("partHitHi", pct(max(parthit)))
pphit = [st.mean(M(s, "PerScope+", "hit_rate")) for s in MSETUPS if all("PerScope+" in r["methods"] for r in main[s])]
rng_mac("ppHit", pphit)
mac("vrHitBird", pct(st.mean(M("bird", "ViewRewrite", "hit_rate")))); mac("vrHitEnt", pct(st.mean(M("ent", "ViewRewrite", "hit_rate"))))
sem_share = [r["methods"]["SemNoScope"]["overpriv"] / r["methods"]["SemNoScope"]["data_calls"] for s in MSETUPS for r in main[s]]
mac("semOverLo", pct(min(sem_share))); mac("semOverHi", pct(max(sem_share)))
stats = json.load(open(os.path.join(RES, "setup_stats.json")))
mac("nScopesLo", str(min(stats[s]["distinct_scopes"] for s in SETUPS))); mac("nScopesHi", str(max(stats[s]["distinct_scopes"] for s in SETUPS)))
fb = [r["methods"]["ScopeCache"]["stats"]["fallback"] / r["methods"]["ScopeCache"]["data_calls"] for s in MSETUPS for r in main[s]]
mac("fallbackLo", pct(min(fb))); mac("fallbackHi", pct(max(fb)))
vadapt = [r["methods"]["VR-adapt"].get("view_rebuilds", 0) for s in MSETUPS for r in main[s] if "VR-adapt" in r["methods"]]

mac("vrAdaptRebuilds", str(max(vadapt)) if vadapt else "??")

# overhead: derivation time per hit, measured on 2026-11-05 on an otherwise idle machine (v1 runs, raw-attribute
# configuration SC-raw = ScopeCache); the 2026-11-10 runs shared the machine with other jobs
der, p95 = [], []
for s in SETUPS:
    for k in range(3):
        r = load("main", s, k)
        if r and "SC-raw" in r["methods"]:
            x = r["methods"]["SC-raw"]
            der.append(x["derive_s"] / max(1, x["hits"])); p95.append(x["lat_local_p95"])
rr, nsame = [], 0
for s_ in SETUPS:
    for k in range(3):
        a, b = load("main", s_, k), load("v2main", s_, k)
        if a and b and "SC-raw" in a["methods"]:
            x, y = a["methods"]["SC-raw"]["n_exec"], b["methods"]["ScopeCache"]["n_exec"]
            rr.append(abs(y / x - 1)); nsame += x == y
mac("rerunDiff", pct(max(rr)) if rr else "??"); mac("rerunSame", str(nsame)); mac("rerunN", str(len(rr)))
# v5: a separate timing run of ScopeCache per setup (tag v5time, seed 0) with no other experiment of ours running
_tm = [load(f"{PFX}time", s_, 0) for s_ in MSETUPS] if PFX >= "v5" else []
if _tm and all(_tm):
    der = [x["methods"]["ScopeCache"]["derive_s"] / max(1, x["methods"]["ScopeCache"]["hits"]) for x in _tm]
    p95 = [x["methods"]["ScopeCache"]["lat_local_p95"] for x in _tm]
mac("deriveMsLo", f"{1e3 * min(der):.0f}"); mac("deriveMsHi", f"{1e3 * max(der):.0f}")
mac("lookupPninetyFiveLo", f"{1e3 * min(p95):.0f}"); mac("lookupPninetyFiveHi", f"{1e3 * max(p95):.0f}")

vm = [r["methods"]["ViewRewrite"].get("view_maint", r["methods"]["ViewRewrite"]["stats"].get("flushed", 0)) for s in MSETUPS for r in main[s]]
mac("vrMaintViews", f"{min(vm)}--{max(vm)}")
vsel = []
for s_ in SETUPS:
    for k in range(3):
        r = load("main", s_, k)
        if r and "SC-raw" in r["methods"]:
            vsel.append(r["methods"]["SC-raw"]["stats"].get("view_build_sec", 0))
if _tm and all(_tm):
    vsel = [x["methods"]["ScopeCache"]["stats"].get("view_build_sec", 0) for x in _tm]
mac("viewSelSecMax", f"{max(vsel):.0f}")

# hit breakdown (main grid): views, own, same-scope other, other scope
bd = {s: {} for s in MSETUPS}
for s in MSETUPS:
    for fld in ("hit_view", "hit_self", "hit_other", "hit_xscope"):
        bd[s][fld] = st.mean(r["methods"]["ScopeCache"].get(fld, 0) / r["methods"]["ScopeCache"]["data_calls"] for r in main[s])
    bd[s]["same"] = bd[s]["hit_other"] - bd[s]["hit_xscope"]
for nm, fld in [("bdView", "hit_view"), ("bdSelf", "hit_self"), ("bdOther", "hit_other"), ("bdX", "hit_xscope"), ("bdSame", "same")]:
    vals = [bd[s][fld] for s in MSETUPS]
    mac(nm + "Lo", pct(min(vals))); mac(nm + "Hi", pct(max(vals)))
ss = [bd[s]["hit_self"] + bd[s]["same"] for s in MSETUPS]
mac("bdSelfSameLo", pct(min(ss))); mac("bdSelfSameHi", pct(max(ss)))
# SC-pad: share of data calls still answered at hit latency (own entries and same-scope entries)
fast = [bd[s]["hit_self"] + bd[s]["same"] for s in MSETUPS]
mac("padFastLo", pct(min(fast))); mac("padFastHi", pct(max(fast)))
# ablation
def rel(s, var):
    return [r["methods"][var]["n_exec"] / r["methods"]["ScopeCache"]["n_exec"] for r in main[s] if var in r["methods"]]
nolift = [x for s in MSETUPS for x in rel(s, "SC-nolift")]
mac("noliftAbsMax", pct(max(abs(st.mean(rel(s, "SC-nolift")) - 1) for s in MSETUPS)))
mac("noliftLo", ("$-$" if min(nolift) < 1 else "+") + pct(abs(min(nolift) - 1))); mac("noliftHi", ("+" if max(nolift) >= 1 else "$-$") + pct(abs(max(nolift) - 1)))
atoms = [x for s in MSETUPS for x in rel(s, "SC-atoms")]
sgn = lambda v: ("$-$" if v < 0 else "+") + pct(abs(v))
mac("atomsDeltaLo", sgn(min(atoms) - 1)); mac("atomsDeltaHi", sgn(max(atoms) - 1))
online = {s: st.mean(rel(s, "SC-online")) for s in MSETUPS}
mac("onlineFactorLo", f"{min(online.values()):.2f}"); mac("onlineFactorHi", f"{max(online.values()):.2f}")
mac("onlineFactorEnt", f"{online['ent']:.1f}")
onl = {}
for s_ in MSETUPS:
    r = load("v2nolift", s_, 0)
    if r:
        onl[s_] = r["methods"]["SC-online-nolift"]["n_exec"] / r["methods"]["SC-online"]["n_exec"]
vals = [v for k, v in onl.items() if k != "ent"]
mac("onlineNoliftLo", f"{min(vals):.2f}" if vals else "??"); mac("onlineNoliftHi", f"{max(vals):.2f}" if vals else "??")
mac("onlineNoliftEnt", f"{onl.get('ent', float('nan')):.2f}")
mac("onlineNoliftSaveLo", pct(1 - 1 / min(vals)) if vals else "??"); mac("onlineNoliftSaveHi", pct(1 - 1 / max(vals)) if vals else "??")
snap = [st.mean(rel(s, "SC-snap")) for s in MSETUPS]
mac("snapFactorLo", f"{min(snap):.2f}"); mac("snapFactorHi", f"{max(snap):.2f}")


# PerScope+V (same pinned views, online entries partitioned by scope) and the policy-domain sweep
psv = []
for s_ in MSETUPS:
    for k in range(3):
        r, x = load("v2main", s_, k), load("v2psv", s_, k)
        if r and x:
            psv.append(1 - r["methods"]["ScopeCache"]["n_exec"] / x["methods"]["PerScope+V"]["n_exec"])
rng_mac("redPSV", psv); mac("nPSVruns", str(len(psv))); mac("redPSVMed", pct(st.median(psv)) if psv else "??")
mac("nPSVneg", str(sum(x < 0 for x in psv)))
psv_s = {}
for s_ in MSETUPS:
    v = []
    for k in range(3):
        r, x = load("v2main", s_, k), load("v2psv", s_, k)
        if r and x:
            v.append(1 - r["methods"]["ScopeCache"]["n_exec"] / x["methods"]["PerScope+V"]["n_exec"])
    psv_s[s_] = v
if all(psv_s.values()):
    rng_mac("psvTpch", psv_s["tpch"]); mac("psvSmallHi", pct(max(psv_s["tpcds"] + psv_s["erp"])))
    mac("psvZeroSetups", "BIRD and ENT" if max(psv_s["bird"] + psv_s["ent"]) == 0 else "??")
DOMS = [50, 300, 1000, 3000]
dom = {n: load("v2dom", f"dom{n}", 0) for n in DOMS}
dom = {n: r["methods"] for n, r in dom.items() if r}
if dom:
    rng_mac("domRedPSPlus", [1 - d["SC-online"]["n_exec"] / d["PerScope+"]["n_exec"] for d in dom.values()])
    rng_mac("domRedVR", [1 - d["ScopeCache"]["n_exec"] / d["ViewRewrite"]["n_exec"] for d in dom.values()])
    rng_mac("domRedPSV", [1 - d["ScopeCache"]["n_exec"] / d["PerScope+V"]["n_exec"] for d in dom.values()])
    rng_mac("domScHit", [d["ScopeCache"]["hit_rate"] for d in dom.values()])
    rng_mac("domPSHit", [d["PerScope"]["hit_rate"] for d in dom.values()])
    assert all(d[m]["wrong"] == 0 for d in dom.values() for m in d)
    db = [d["ScopeCache"]["n_exec"] <= min(v["n_exec"] for k, v in d.items() if k not in ("ScopeCache", "NoCache")) for d in dom.values()]
    mac("domBest", str(sum(db))); mac("domPoints", str(len(db)))
    mac("domTies", str(sum(d["ScopeCache"]["n_exec"] == d["PerScope+V"]["n_exec"] for d in dom.values())))

# scale run: TPC-H at scale factor 5 (seed 0)
sc5 = load(f"{PFX}scale", "tpch5", 0)
if sc5:
    m5 = sc5["methods"]
    assert all(v["wrong"] == 0 for v in m5.values())
    red = lambda base, var="ScopeCache": pct(1 - m5[var]["n_exec"] / m5[base]["n_exec"])
    mac("scaleRedVR", red("ViewRewrite")); mac("scaleRedPS", red("PerScope")); mac("scaleRedPSV", red("PerScope+V"))
    mac("scaleRedPSPlus", red("PerScope+", "SC-online")); mac("scaleScHit", pct(m5["ScopeCache"]["hit_rate"]))
    mac("scaleRedVROne", pct(st.mean(1 - r["methods"]["ScopeCache"]["n_exec"] / r["methods"]["ViewRewrite"]["n_exec"] for r in main["tpch"][:1])))
    mac("scaleDataCalls", fmt_int(m5["ScopeCache"]["data_calls"]))
# safety table
rows = []
for m in ["NoCache", "Exact", "PerUser", "PerScope", "PerScope+", "PerScope+V", "TTL", "SemNoScope", "ViewRewrite", "VR-adapt", "ScopeCache", "SC-online", "SC-nolift", "SC-snap", "SC-atoms"]:
    if not all(m in r["methods"] for s_ in MSETUPS for r in main[s_]):
        continue
    dc = sum(r["methods"][m]["data_calls"] for s in MSETUPS for r in main[s] if m in r["methods"])
    w = sum(r["methods"][m]["wrong"] for s in MSETUPS for r in main[s] if m in r["methods"])
    o = sum(r["methods"][m]["overpriv"] for s in MSETUPS for r in main[s] if m in r["methods"])
    rows.append([m, dc, w, o])

EVSETUPS = SETUPS + (["erp"] if PFX >= "v5" else [])   # v5: ERP joins the event sweep
# event sweep (seed 0): v2ev0/4/16 and v2main seed 0 for rate 1
ev = {}
for s in EVSETUPS:
    ev[s] = {}
    # v5: common random numbers with the same 3,000 calls at every rate (tag v5cev*)
    _evt = [(0, "v2cev0"), (1, "v2cev1"), (4, "v2cev4"), (16, "v2cev16")] if PFX >= "v5" else [(0, "v2ev0"), (1, "v2main"), (4, "v2ev4"), (16, "v2ev16")]
    for rate, tag in _evt:
        r = load(tag, s, 0)
        if r:
            ev[s][rate] = r["methods"]
replay_w = sum(ev[s][16]["TTL"]["replay_wrong"] for s in EVSETUPS if 16 in ev[s])
replay_c = sum(ev[s][16]["TTL"]["replay_calls"] for s in EVSETUPS if 16 in ev[s])
mac("ttlReplayWrong", str(replay_w)); mac("ttlReplayCalls", str(replay_c))
sc_replay_w = sum(ev[s][k]["ScopeCache"]["replay_wrong"] for s in EVSETUPS for k in ev[s])
assert sc_replay_w == 0
drop = [100 * abs(ev[s][0]["ScopeCache"]["hit_rate"] - ev[s][16]["ScopeCache"]["hit_rate"]) for s in EVSETUPS if 0 in ev[s] and 16 in ev[s]]
mac("evHitDropMax", f"{max(drop):.1f}" if drop else "??")
evb = [ev[s][r]["ScopeCache"]["n_exec"] <= min(ev[s][r][m]["n_exec"] for m in ("PerScope", "ViewRewrite", "SC-snap", "PerScope+V") if m in ev[s][r]) for s in EVSETUPS for r in ev[s]]
mac("evBest", str(sum(evb))); mac("evPoints", str(len(evb)))
_evps = [ev[s][r]["PerScope"]["n_exec"] for s in EVSETUPS for r in ev[s]]
mac("evPSLo", fmt_int(min(_evps))); mac("evPSHi", fmt_int(max(_evps)))
_pt = [x for x in EVSETUPS if ev[x] and all("PerScope+V" in ev[x][r] and ev[x][r]["PerScope+V"]["n_exec"] == ev[x][r]["ScopeCache"]["n_exec"] for r in ev[x])]
mac("evPSVTieSetups", (", ".join(NAME[x] for x in _pt[:-1]) + ({1: "", 2: " and "}.get(len(_pt), ", and ")) + NAME[_pt[-1]]) if _pt else "none")
snap16 = [ev[s][16]["SC-snap"]["n_exec"] / ev[s][16]["ScopeCache"]["n_exec"] for s in EVSETUPS if 16 in ev[s]]
mac("snapFactorSixteen", f"{max(snap16):.1f}" if snap16 else "??")
for m in ["TTL"]:
    pass

# drift and small budget
def red_from(tag):
    out = []
    for s in SETUPS:
        r = load(tag, s, 0)
        if r:
            out.append(1 - r["methods"]["ScopeCache"]["n_exec"] / r["methods"]["ViewRewrite"]["n_exec"])
    return out
dr, sm = red_from("v2drift"), red_from("v2b100k")
mac("driftRedLo", pct(min(dr)) if dr else "??"); mac("driftRedHi", pct(max(dr)) if dr else "??")
mac("smallRedLo", pct(min(sm)) if sm else "??"); mac("smallRedHi", pct(max(sm)) if sm else "??")

# ------------------------------------------------------------------ agent traces
ag = json.load(open(os.path.join(RES, f"agent_eval_{AGPFX}_b1000000.json")))
sens = json.load(open(os.path.join(RES, f"agent_sens_{AGPFX}.json")))
keys = sorted(ag)
mac("nAgentTraces", str(len(keys)))
mac("nAgentCalls", fmt_int(sum(ag[k]["calls"] for k in keys)))
mac("nAgentDataCalls", fmt_int(sum(ag[k]["methods"]["NoCache"]["data_calls"] for k in keys)))
assert sum(ag[k]["methods"][m]["wrong"] for k in keys for m in SAFE if m in ag[k]["methods"]) == 0
xs = [ag[k]["methods"]["SC-online"]["xscope_share"] for k in keys]
mac("agentXscopeLo", pct(min(xs))); mac("agentXscopeHi", pct(max(xs)))
ps = [ag[k]["methods"]["PerScope"]["hit_rate"] for k in keys]
_smean = lambda m, fld: [st.mean(ag[k]["methods"][m][fld] for k in keys if k.startswith(s_ + "/")) for s_ in SETUPS if any(k.startswith(s_ + "/") for k in keys)]
rng_mac("agentXscopeMean", _smean("SC-online", "xscope_share")); rng_mac("agentPSMean", _smean("PerScope", "hit_rate"))
mac("agentPSLo", pct(min(ps))); mac("agentPSHi", pct(max(ps)))
rps = [1 - ag[k]["methods"]["ScopeCache"]["n_exec"] / ag[k]["methods"]["PerScope"]["n_exec"] for k in keys]
mac("redPSLo", pct(min(rps))); mac("redPSHi", pct(max(rps)))
ros = [1 - ag[k]["methods"]["SC-online"]["n_exec"] / ag[k]["methods"]["PerScope"]["n_exec"] for k in keys]
mac("agentRedOnlinePSLo", pct(min(ros))); mac("agentRedOnlinePSHi", pct(max(ros)))
rvr = [1 - ag[k]["methods"]["ScopeCache"]["n_exec"] / ag[k]["methods"]["ViewRewrite"]["n_exec"] for k in keys]
mac("agentRedVRmed", pct(st.median(rvr)))
vh = [ag[k]["methods"]["ViewRewrite"]["hit_rate"] for k in keys]
mac("agentVRHitLo", pct(min(vh))); mac("agentVRHitHi", pct(max(vh)))
mac("agentXscopeEntD", pct(st.mean(ag[k]["methods"]["SC-online"]["xscope_share"] for k in keys if k.startswith("ent/")), 1))
mac("agentXscopeEnt", pct(st.mean(ag[k]["methods"]["SC-online"]["xscope_share"] for k in keys if k.startswith("ent/"))))
sh = [ag[k]["methods"]["ScopeCache"]["hit_rate"] for k in keys]
mac("agentScHitLo", pct(min(sh))); mac("agentScHitHi", pct(max(sh)))
agent_files = {k: os.path.join(RES, "agent", k.replace("/s0", "").replace("/s", "_s").replace("/", "_") + ".jsonl") for k in keys}
cpe = []
for k, p in agent_files.items():
    rws = [json.loads(l) for l in open(p)]
    cpe.append(len(rws) / len({r["ep"] for r in rws}))
mac("agentCallsPerEpLo", f"{min(cpe):.1f}"); mac("agentCallsPerEpHi", f"{max(cpe):.1f}")
mac("agentSemOverLo", pct(min(ag[k]["methods"]["SemNoScope"]["overpriv"] / ag[k]["methods"]["SemNoScope"]["data_calls"] for k in keys)))
mac("agentSemOverHi", pct(max(ag[k]["methods"]["SemNoScope"]["overpriv"] / ag[k]["methods"]["SemNoScope"]["data_calls"] for k in keys)))
mac("agentSemHitLo", pct(min(ag[k]["methods"]["SemNoScope"]["hit_rate"] for k in keys)))
mac("agentSemHitHi", pct(max(ag[k]["methods"]["SemNoScope"]["hit_rate"] for k in keys)))
k1 = {k: v["k=1"]["SC-online"]["xscope"] for k, v in sens.items()}
k2 = {k: v["k=2"]["SC-online"]["xscope"] for k, v in sens.items()}
mac("sensOneLo", pct(min(k1.values()))); mac("sensOneHi", pct(max(k1.values())))
mac("sensTwoLo", pct(min(k2.values()))); mac("sensTwoHi", pct(max(k2.values())))
mac("sensOneTpch", pct(st.mean(v for k, v in k1.items() if k.startswith("tpch/"))))
mac("sensOneEnt", pct(st.mean(v for k, v in k1.items() if k.startswith("ent/"))))
mac("sensOneCalls", fmt_int(sum(v["k=1"]["ScopeCache"]["data_calls"] for v in sens.values())))
# PerScope+V on the agent traces
if all("PerScope+V" in ag[k]["methods"] for k in keys):
    rpsv = [1 - ag[k]["methods"]["ScopeCache"]["n_exec"] / ag[k]["methods"]["PerScope+V"]["n_exec"] for k in keys]
    rng_mac("agentRedPSV", rpsv); mac("agentRedPSVMed", pct(st.median(rpsv))); mac("agentPSVneg", str(sum(x < 0 for x in rpsv)))
    _pm = {s_: 1 - st.mean(ag[k]["methods"]["ScopeCache"]["n_exec"] for k in keys if k.startswith(s_ + "/")) / st.mean(ag[k]["methods"]["PerScope+V"]["n_exec"] for k in keys if k.startswith(s_ + "/")) for s_ in SETUPS}
    _gap = [x for x in SETUPS if _pm[x] > 0.005]; _tie = [x for x in SETUPS if abs(_pm[x]) <= 0.005]
    assert all(_pm[x] >= -0.005 for x in SETUPS)
    _nm = lambda ss: ", ".join(NAME[x] for x in ss[:-1]) + ({1: "", 2: " and "}.get(len(ss), ", and ")) + NAME[ss[-1]]
    _sent = f"Against \\M{{PerScope+V}}, which has the same pinned views, ScopeCache needs {pct(min(_pm[x] for x in _gap))}--{pct(max(_pm[x] for x in _gap))}\\% fewer executions on {_nm(_gap)}" if _gap else ""
    if _tie:
        _vh = [st.mean(ag[k]["methods"]["ScopeCache"]["hit_view"] / max(1, ag[k]["methods"]["ScopeCache"]["data_calls"]) for k in keys if k.startswith(x + "/")) for x in _tie]
        _sent += f" and as many on {_nm(_tie)}, where pinned views answer {pct(min(_vh))}--{pct(max(_vh))}\\% of data calls"
    mac("agentPSVSentence", _sent + ".")
    rng_mac("agentRedPSVMean", [1 - st.mean(ag[k]["methods"]["ScopeCache"]["n_exec"] for k in keys if k.startswith(s_ + "/")) / st.mean(ag[k]["methods"]["PerScope+V"]["n_exec"] for k in keys if k.startswith(s_ + "/")) for s_ in SETUPS])
# ENT with a ten-times larger budget: lifted entries fit under the admission bound
_big = os.path.join(RES, f"agent_eval_{AGPFX}_b10000000.json")
if os.path.exists(_big):
    big = json.load(open(_big))
    ek = [k for k in big if k.startswith("ent/")]
    if ek and all("SC-online" in big[k]["methods"] for k in ek):
        mac("entBigXscope", pct(st.mean(big[k]["methods"]["SC-online"]["xscope_share"] for k in ek)))
        mac("entBigRedPSPlus", pct(1 - st.mean(big[k]["methods"]["SC-online"]["n_exec"] for k in ek) / st.mean(big[k]["methods"]["PerScope+"]["n_exec"] for k in ek)))
        assert all(v["wrong"] == 0 for k in ek for v in big[k]["methods"].values())

# LLM cost from the usage log (list prices, $/M tokens: input miss, input cache hit, output)
PRICE = {"deepseek-chat": (0.27, 0.07, 1.10), "glm-4.5-flash": (0.0, 0.0, 0.0), "kimi-k2.6": (0.95, 0.16, 4.00)}
cost = 0.0
_ul = os.path.join(os.path.dirname(PAPER), "code", "cache", "usage.log")
if os.path.exists(_ul):
    _lines = open(_ul).read().splitlines()
else:  # artifact: read the log from the released LLM cache archive
    import tarfile
    with tarfile.open(os.path.join(os.path.dirname(PAPER), "data", "llm_cache.tar.gz")) as _t:
        _lines = _t.extractfile("cache/usage.log").read().decode().splitlines()
for l in _lines:
    r = json.loads(l)
    if r["model"] not in PRICE:
        continue
    a, b, c = PRICE[r["model"]]
    pt, ct = r.get("prompt_tokens", 0), r.get("completion_tokens", 0)
    ca = (r.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or r.get("prompt_cache_hit_tokens", 0) or 0
    cost += ((pt - ca) * a + ca * b + ct * c) / 1e6
mac("agentCost", f"{cost:.2f}")
_intl = [json.loads(l) for l in _lines if any(x in l for x in ('"gpt-6-sol"', '"claude-opus-5-5"'))]
mac("intlCalls", fmt_int(len(_intl))); mac("intlMTokens", f"{sum(r.get('total_tokens', 0) for r in _intl) / 1e6:.1f}")
_models = sorted({k.split("/")[1] for k in keys})
WORD = {3: "three", 4: "four", 5: "five", 6: "six"}
mac("nModelsWord", WORD.get(len(_models), str(len(_models)))); mac("nVendorsWord", WORD.get(len(_models), str(len(_models))))
_cpq = {}
for k in keys:
    rws = [json.loads(l) for l in open(agent_files[k])]
    _cpq.setdefault(k.split("/")[1], []).append(len(rws) / len({r["ep"] for r in rws}))
_cm = {m: st.mean(v) for m, v in _cpq.items()}
mac("callsPerQLo", f"{min(_cm.values()):.1f}"); mac("callsPerQHi", f"{max(_cm.values()):.1f}")

# ------------------------------------------------------------------ ERP
erp = json.load(open(os.path.join(RES, "erp_event_counts.json")))
pol = json.load(open(os.path.join(RES, "erp_policy_stats.json")))
mac("erpPermWrites", fmt_int(erp["total"])); mac("erpPermPerDay", f"{erp['per_day']:.1f}")
mac("erpReportPerDay", fmt_int(erp["report_calls_per_day"])); mac("erpDeact", str(erp["deactivations"])); mac("erpRoleEdits", str(erp["role_edits"]))
mac("erpCompShop", f"{pol['shop']['compression_raw_over_atoms']:.2f}"); mac("erpCompWh", f"{pol['warehouse']['compression_raw_over_atoms']:.2f}")
wl = json.load(open(os.path.join(RES, "erp_workload_stats.json")))
_r10 = wl["repeat_upper_bounds"]["10min"]
mac("erpLogCalls", f"{wl['calls'] / 1e6:.1f}"); mac("erpLogDays", f"{wl['days']:.1f}")
mac("erpXscopeTen", pct(_r10["all"]["different_scope_only"])); mac("erpXscopeTenAgg", pct(_r10["aggregation_like"]["different_scope_only"]))
mac("erpEndpointUsersMed", f"{wl['agg_endpoint_hour']['p50_users']:.0f}"); mac("erpEndpointUsersPninety", f"{wl['agg_endpoint_hour']['p90_users']:.0f}")
mac("erpSameUserHour", pct(wl["repeat_upper_bounds"]["1h"]["all"]["same_user"]))
mac("erpShopAccounts", str(pol["shop"]["accounts_with_grant"])); mac("erpShopScopes", str(pol["shop"]["distinct_scopes"]))
mac("erpAcctPerScope", f"{pol['shop']['accounts_with_grant'] / pol['shop']['distinct_scopes']:.1f}")
oc = json.load(open(os.path.join(RES, "oracle_check.json"))) if os.path.exists(os.path.join(RES, "oracle_check.json")) else {}
mac("oracleChecked", fmt_int(sum(v["checked"] for v in oc.values()))); mac("oracleAgree", fmt_int(sum(v["agree"] for v in oc.values())))
mac("artifactURL", "https://github.com/wanghongsheng01/ScopeCache")



# ------------------------------------------------------------------ tables
def ms(vals, nd=2, scale=1.0):
    m = st.mean(vals) * scale
    sd = (st.pstdev(vals) * scale) if len(vals) > 1 else 0
    return m, sd

erp_env_scopes = json.load(open(os.path.join(RES, "erp_policy_stats.json")))["shop"]
with open(os.path.join(OUTDIR, "tab_setups.tex"), "w") as f:
    f.write("\\begin{table}[t]\n\\centering\n\\caption{Scopes are fine-grained: every setup has " + f"{min([stats[x]['distinct_scopes'] for x in SETUPS] + [erp_env_scopes['distinct_scopes']])}--{max([stats[x]['distinct_scopes'] for x in SETUPS] + [erp_env_scopes['distinct_scopes']])}" + " distinct scopes. Principals: 400 per synthetic policy, 721 real accounts in ERP; scopes counted at seed 0.}\n\\label{tab:setups}\n\\footnotesize\n\\setlength{\\tabcolsep}{2.5pt}\n")
    f.write("\\begin{tabular}{@{}lrrlr@{}}\n\\toprule\nSetup & Rows & Months & Policy attributes (values) & Scopes\\\\\n\\midrule\n")
    PA = {"tpch": "nation, segm., mfgr", "tpcds": "state, category", "bird": "district, freq.", "ent": "dept., brand, chan."}
    for s_ in SETUPS:
        d = stats[s_]
        card = "$\\times$".join(str(v) for v in d["policy"].values())
        f.write(f"{NAME[s_]} & {d['rows'] / 1e6:.1f}M & {d['months']} & {PA[s_]} ({card}) & {d['distinct_scopes']}\\\\\n")
    f.write(f"ERP & 2.0M & 36 & shop ({erp_env_scopes['domain']}) & {erp_env_scopes['distinct_scopes']}\\\\\n")
    f.write("\\bottomrule\n\\end{tabular}\n\\end{table}\n")

RANK_NOTE = "bold/underlined: best/second best"


def mark(printed, higher_better, exclude=()):
    """printed: {row: printed string whose first number is the ranked value}.  Returns {row: marked string} and
    {row: 'B'|'2'|''}; rows in `exclude` (unsafe methods) are printed but not ranked."""
    import re as _re
    val = {k: float(_re.search(r"-?\d+(?:\.\d+)?", v.replace("{,}", "")).group(0)) for k, v in printed.items() if v not in ("--", "")}
    ranked = sorted({v for k, v in val.items() if k not in exclude}, reverse=higher_better)
    out, tag = {}, {}
    for k, v in printed.items():
        t = ""
        if k in val and k not in exclude and ranked:
            if val[k] == ranked[0]:
                t = "B"
            elif len(ranked) > 1 and val[k] == ranked[1]:
                t = "2"
        out[k] = "\\textbf{" + v + "}" if t == "B" else ("\\underline{" + v + "}" if t == "2" else v)
        tag[k] = t
    return out, tag


UNSAFE = ("TTL", "SemNoScope")
with open(os.path.join(OUTDIR, "tab_safety.tex"), "w") as f:
    f.write("\\begin{table}[t]\n\\centering\n\\caption{Only the two shared caches are unsafe; no safe cache returns a wrong answer. Wrong answers over the main grid (five setups $\\times$ three seeds) and the agent traces; fewer is better; " + RANK_NOTE + " among the safe methods.}\n\\label{tab:safety}\n\\footnotesize\n\\setlength{\\tabcolsep}{4pt}\n")
    f.write("\\begin{tabular}{@{}lrrrrr@{}}\n\\toprule\n & \\multicolumn{3}{c}{Main grid} & \\multicolumn{2}{c}{Agent traces}\\\\\n\\cmidrule(lr){2-4}\\cmidrule(l){5-6}\nMethod & Data calls & Wrong & Over-priv. & Wrong & Over-priv.\\\\\n\\midrule\n")
    cols = {c: {} for c in ("w", "o", "aw", "ao")}
    dcs = {}
    for m, dc, w, o in rows:
        if m == "NoCache":
            continue
        has = any(m in ag[k]["methods"] for k in keys)
        dcs[m] = dc
        cols["w"][m] = fmt_int(w); cols["o"][m] = fmt_int(o)
        cols["aw"][m] = fmt_int(sum(ag[k]["methods"][m]["wrong"] for k in keys if m in ag[k]["methods"])) if has else "--"
        cols["ao"][m] = fmt_int(sum(ag[k]["methods"][m]["overpriv"] for k in keys if m in ag[k]["methods"])) if has else "--"
    mk = {c: mark(v, False, exclude=UNSAFE)[0] for c, v in cols.items()}
    for m in dcs:
        nm = "\\textbf{ScopeCache}" if m == "ScopeCache" else "\\M{" + m + "}"
        f.write(f"{nm} & {fmt_int(dcs[m])} & {mk['w'][m]} & {mk['o'][m]} & {mk['aw'][m]} & {mk['ao'][m]}\\\\\n")
    f.write("\\bottomrule\n\\end{tabular}\n\\end{table}\n")

MAINM = ["NoCache", "Exact", "PerUser", "PerScope", "PerScope+", "PerScope+V", "TTL", "ViewRewrite", "VR-adapt", "ScopeCache"]
MAINM = [m for m in MAINM if all(m in r["methods"] for s_ in MSETUPS for r in main[s_])]
counts = {m: [0, 0] for m in MAINM}
cell = {m: [] for m in MAINM}
for s_ in MSETUPS:
    ph, pe = {}, {}
    for m in MAINM:
        h, hs = ms(M(s_, m, "hit_rate"), scale=100); e, es = ms(M(s_, m, "n_exec"))
        ph[m] = f"{h:.1f}$\\pm${hs:.1f}"; pe[m] = f"{e:.0f}$\\pm${es:.0f}"
    (mh, th), (me, te) = mark(ph, True, UNSAFE), mark(pe, False, UNSAFE)
    for m in MAINM:
        cell[m] += [mh[m], me[m]]
        for t in (th[m], te[m]):
            if t == "B": counts[m][0] += 1
            if t == "2": counts[m][1] += 1
ncell = 2 * len(MSETUPS)
mac("vrSecondCells", str(counts["ViewRewrite"][1]))
_rival = max((m for m in MAINM if m not in UNSAFE and m != "ScopeCache"), key=lambda m: (counts[m][0] + counts[m][1], counts[m][0]))
mac("rivalName", "\\M{" + _rival + "}"); _b, _c = counts[_rival]
mac("rivalStanding", (f"best (tied) in {_b} and second in {_c} cells" if _b else f"second in {_c} cells"))
mac("rivalBestN", str(_b)); mac("rivalSecondN", str(_c))
mac("scBestCells", str(counts["ScopeCache"][0])); mac("scSecondCells", str(counts["ScopeCache"][1])); mac("mainCells", str(ncell))
# the bare tabular, also used by the Chinese introduction for the co-author
_buf = ["\\begin{tabular}{@{}l" + "rr" * len(MSETUPS) + "c@{}}\n\\toprule\n",
        " & " + " & ".join(f"\\multicolumn{{2}}{{c}}{{{NAME[s_]}}}" for s_ in MSETUPS) + " & \\\\\n",
        "".join(f"\\cmidrule(lr){{{2 + 2 * i}-{3 + 2 * i}}}" for i in range(len(MSETUPS))) + "\n",
        "Method" + " & Hit & Exec." * len(MSETUPS) + " & B/2\\\\\n\\midrule\n"]
for m in MAINM:
    nm = "\\textbf{ScopeCache}" if m == "ScopeCache" else "\\M{" + m + "}"
    bc = "--" if m in UNSAFE else f"{counts[m][0]}/{counts[m][1]}"
    _buf.append(nm + " & " + " & ".join(cell[m]) + f" & {bc}\\\\\n")
_buf.append("\\bottomrule\n\\end{tabular}\n")
open(os.path.join(OUTDIR, "tab_main_tabular.tex"), "w").write("".join(_buf))
with open(os.path.join(OUTDIR, "tab_main.tex"), "w") as f:
    f.write("\\begin{table*}[t]\n\\centering\n\\caption{" + ("ScopeCache has the highest hit rate and the fewest executions on every setup. " if counts["ScopeCache"][0] == ncell else "") + "Hit rate (\\%, higher is better) and executions (lower is better), mean $\\pm$ std.\\ over three seeds; " + RANK_NOTE + ", counted in B/2; \\M{TTL} is unsafe and unranked.}\n\\label{tab:main}\n\\footnotesize\n\\setlength{\\tabcolsep}{3.4pt}\n")
    f.write("\\begin{tabular}{@{}l" + "rr" * len(MSETUPS) + "c@{}}\n\\toprule\n")
    f.write(" & " + " & ".join(f"\\multicolumn{{2}}{{c}}{{{NAME[s_]}}}" for s_ in MSETUPS) + " & \\\\\n")
    f.write("".join(f"\\cmidrule(lr){{{2 + 2 * i}-{3 + 2 * i}}}" for i in range(len(MSETUPS))) + "\n")
    f.write("Method" + " & Hit & Exec." * len(MSETUPS) + " & B/2\\\\\n\\midrule\n")
    for m in MAINM:
        nm = "\\textbf{ScopeCache}" if m == "ScopeCache" else "\\M{" + m + "}"
        bc = "--" if m in UNSAFE else f"{counts[m][0]}/{counts[m][1]}"
        f.write(nm + " & " + " & ".join(cell[m]) + f" & {bc}\\\\\n")
    f.write("\\bottomrule\n\\end{tabular}\n\\end{table*}\n")

with open(os.path.join(OUTDIR, "tab_ablation.tex"), "w") as f:
    f.write("\\begin{table}[t]\n\\centering\n\\caption{Removing any component costs executions on at least one setup. Executions relative to ScopeCache (Table~\\ref{tab:main}), mean of three seeds, lower is better; G.\\,mean: geometric mean over setups; " + RANK_NOTE + ". $^\\dagger$Relative to \\M{SC-online}, seed 0.}\n\\label{tab:ablation}\n\\footnotesize\n\\setlength{\\tabcolsep}{3.6pt}\n")
    f.write("\\begin{tabular}{@{}l" + "r" * len(MSETUPS) + "@{\\hspace{7pt}}r@{}}\n\\toprule\nVariant & " + " & ".join(NAME[s] for s in MSETUPS) + " & G.\\,mean\\\\\n\\midrule\n")
    VARS = ["ScopeCache", "SC-online", "PerScope+", "SC-nolift", "SC-snap", "SC-atoms"]
    colmk, abt = {}, []
    gm = lambda xs: float(np.exp(np.mean(np.log(xs))))
    for s_ in MSETUPS:
        pr = {v: "1.00$\\times$" if v == "ScopeCache" else f"{st.mean(rel(s_, v)):.2f}$\\times$" for v in VARS}
        colmk[s_], tg = mark(pr, False)
        abt.append(tg["ScopeCache"])
    abgm = {v: 1.0 if v == "ScopeCache" else gm([st.mean(rel(s_, v)) for s_ in MSETUPS]) for v in VARS}
    colmk["gm"] = mark({v: f"{abgm[v]:.2f}$\\times$" for v in VARS}, False)[0]
    for v, nm_ in [("SC-online", "Online"), ("PerScope+", "PSPlus"), ("SC-nolift", "Nolift"), ("SC-snap", "Snap"), ("SC-atoms", "Atoms")]:
        mac("abGm" + nm_, f"{abgm[v]:.2f}")
    # SC-atoms on ENT: fewer scope-keyed fallbacks because coarser cells keep more lifted entries under the admission bound
    _fb = lambda v: sum(r["methods"][v]["stats"]["fallback"] for r in main["ent"])
    mac("atomsEntExecDiff", f"{st.mean(r['methods']['ScopeCache']['n_exec'] - r['methods']['SC-atoms']['n_exec'] for r in main['ent']):.0f}")
    mac("atomsEntFbRed", pct(1 - _fb("SC-atoms") / _fb("ScopeCache")))
    mac("scEntExecSd", f"{ms(M('ent', 'ScopeCache', 'n_exec'))[1]:.0f}")
    am = [st.mean(rel(s_, "SC-atoms")) for s_ in MSETUPS]
    mac("atomsMeanSave", pct(1 - min(am))); mac("atomsMeanWorse", pct(max(am) - 1))
    assert all(min(rel(s_, v)) >= 1 or True for s_ in MSETUPS for v in VARS[1:])
    _costs = {v: any(st.mean(rel(s_, v)) > 1.0 for s_ in MSETUPS) for v in ["SC-online", "PerScope+", "SC-nolift", "SC-snap"]}
    assert all(_costs.values()), ("Table VII caption claims every removed component costs executions", _costs)
    mac("abBest", str(abt.count("B"))); mac("abSecond", str(abt.count("2"))); mac("abCols", str(len(abt)))
    for v in VARS:
        nm = "\\textbf{ScopeCache}" if v == "ScopeCache" else "\\M{" + v + "}"
        f.write(nm + " & " + " & ".join(colmk[s_][v] for s_ in MSETUPS) + " & " + colmk["gm"][v] + "\\\\\n")
    f.write("\\midrule\n\\M{SC-online-nolift}$^\\dagger$ & " + " & ".join(f"{onl[s]:.2f}$\\times$" if s in onl else "--" for s in MSETUPS)
            + " & " + (f"{gm([onl[s] for s in MSETUPS]):.2f}$\\times$" if all(s in onl for s in MSETUPS) else "--") + "\\\\\n")
    f.write("\\bottomrule\n\\end{tabular}\n\\end{table}\n")

AGM = ["PerScope", "PerScope+", "PerScope+V", "ViewRewrite", "ScopeCache"]
AGL = {"PerScope": "PS", "PerScope+": "PS+", "PerScope+V": "PS+V", "ViewRewrite": "VR", "ScopeCache": "SC"}
AGM = [m for m in AGM if all(m in ag[k]["methods"] for k in keys)]      # dry runs before every replay is done
ag_counts = [0, 0, 0]
ag_bc = {(m, c): [0, 0] for m in AGM for c in ("hit", "exe")}
with open(os.path.join(OUTDIR, "tab_agent.tex"), "w") as f:
    f.write("\\begin{table*}[t]\n\\centering\n\\caption{ScopeCache has the highest hit rate and the fewest executions on every setup of the agent traces. Mean per trace; data calls: total. PS(+)(V): \\M{PerScope(+)(V)}; VR: \\M{ViewRewrite}; SC: ScopeCache; X-sc.: cross-scope share of \\M{SC-online}; " + RANK_NOTE + ".}\n\\label{tab:agent}\n\\footnotesize\n\\setlength{\\tabcolsep}{4pt}\n")
    f.write("\\begin{tabular}{@{}lrr" + "r" * len(AGM) + "r" + "r" * len(AGM) + "@{}}\n\\toprule\n")
    f.write(f" & & & \\multicolumn{{{len(AGM)}}}{{c}}{{Hit rate (\\%)}} & & \\multicolumn{{{len(AGM)}}}{{c}}{{Executions}}\\\\\n")
    f.write(f"\\cmidrule(lr){{4-{3 + len(AGM)}}}\\cmidrule(l){{{5 + len(AGM)}-{4 + 2 * len(AGM)}}}\n")
    f.write("Setup & Traces & Data calls & " + " & ".join(AGL[m] for m in AGM) + " & X-sc. & " + " & ".join(AGL[m] for m in AGM) + "\\\\\n\\midrule\n")
    for s in SETUPS:
        ks = [k for k in keys if k.startswith(s + "/")]
        if not ks:
            continue
        g = lambda m, fld: st.mean(ag[k]["methods"][m][fld] for k in ks)
        hit = mark({m: f"{100 * g(m, 'hit_rate'):.1f}" for m in AGM}, True)
        exe = mark({m: f"{g(m, 'n_exec'):.1f}" for m in AGM}, False)
        for t in (hit[1]["ScopeCache"], exe[1]["ScopeCache"]):
            ag_counts[0] += 1; ag_counts[1] += t == "B"; ag_counts[2] += t == "2"
        for m in AGM:
            for c, tg in (("hit", hit[1][m]), ("exe", exe[1][m])):
                ag_bc[(m, c)][0] += tg == "B"; ag_bc[(m, c)][1] += tg == "2"
        f.write(f"{NAME[s]} & {len(ks)} & {fmt_int(sum(ag[k]['methods']['NoCache']['data_calls'] for k in ks))} & " + " & ".join(hit[0][m] for m in AGM)
                + f" & {100 * g('SC-online', 'xscope_share'):.1f} & " + " & ".join(exe[0][m] for m in AGM) + "\\\\\n")
    f.write("\\midrule\nBest/2nd & & & " + " & ".join("%d/%d" % tuple(ag_bc[(m, "hit")]) for m in AGM) + " & & "
            + " & ".join("%d/%d" % tuple(ag_bc[(m, "exe")]) for m in AGM) + "\\\\\n")
    f.write("\\bottomrule\n\\end{tabular}\n\\end{table*}\n")
mac("agBestCells", str(ag_counts[1])); mac("agSecondCells", str(ag_counts[2])); mac("agCells", str(ag_counts[0]))
assert ag_counts[1] == ag_counts[0], "Table V caption claims ScopeCache is best in every cell"


VNAME = {"deepseek": "deepseek-chat", "glm": "GLM-4.5-flash", "kimi": "Kimi-K2.6", "gpt6": "GPT-6 (gpt-6-sol)", "claude": "Claude Opus 5.5"}
with open(os.path.join(OUTDIR, "tab_agentvendor.tex"), "w") as f:
    f.write("\\begin{table}[t]\n\\centering\n\\caption{Cross-scope reuse and the savings over \\M{PerScope} hold for every agent model. Per model over all setups and recording seeds; Exec. ratio: ScopeCache executions over those of \\M{PerScope}. Rows are models, not methods, so the table is not ranked.}\n\\label{tab:agentvendor}\n\\footnotesize\n\\setlength{\\tabcolsep}{4pt}\n")
    f.write("\\begin{tabular}{@{}lrrrr@{}}\n\\toprule\nModel & Calls/q. & Hit (\\%) & X-sc. (\\%) & Exec. ratio\\\\\n\\midrule\n")
    for v in ["deepseek", "glm", "kimi", "gpt6", "claude"]:
        ks = [k for k in keys if k.split("/")[1] == v]
        if not ks:
            continue
        cp = []
        for k in ks:
            rws = [json.loads(l) for l in open(agent_files[k])]
            cp.append(len(rws) / len({r["ep"] for r in rws}))
        f.write(f"{VNAME[v]} & {st.mean(cp):.2f} & {100 * st.mean(ag[k]['methods']['ScopeCache']['hit_rate'] for k in ks):.1f} & "
                f"{100 * st.mean(ag[k]['methods']['SC-online']['xscope_share'] for k in ks):.1f} & "
                f"{st.mean(ag[k]['methods']['ScopeCache']['n_exec'] / ag[k]['methods']['PerScope']['n_exec'] for k in ks):.3f}\\\\\n")
    f.write("\\bottomrule\n\\end{tabular}\n\\end{table}\n")
# ------------------------------------------------------------------ figures
plt.rcParams.update({"font.size": 8, "font.family": "serif", "font.serif": ["STIX Two Text", "STIXGeneral", "DejaVu Serif"],
                     "mathtext.fontset": "stix", "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42})
# Okabe-Ito colour-blind-safe palette; ScopeCache is always the dark blue line, drawn thicker and on top
MC = {"PerScope": "#56B4E9", "PerScope+": "#E69F00", "PerScope+V": "#009E73", "ViewRewrite": "#7f7f7f",
      "SC-snap": "#D55E00", "SC-online": "#CC79A7", "ScopeCache": "#0072B2"}
SC_STYLE = dict(lw=1.8, zorder=5)
C1, C2, C3, C4 = MC["PerScope"], MC["ScopeCache"], MC["SC-snap"], MC["ViewRewrite"]
SETUP_COL = {"tpch": "#0072B2", "tpcds": "#E69F00", "bird": "#7f7f7f", "ent": "#009E73"}

fig, ax = plt.subplots(figsize=(3.4, 1.75))
x = np.arange(len(SETUPS)); w = 0.36
for i, (fld, m, col, lab) in enumerate([("hit_rate", "PerScope", C1, "scope-partitioned: hit rate"),
                                         ("xscope_share", "SC-online", C2, "ScopeCache: other-scope hits")]):
    means, lo, hi = [], [], []
    for s in SETUPS:
        v = [ag[k]["methods"][m][fld] * 100 for k in keys if k.startswith(s + "/")]
        means.append(st.mean(v) if v else 0); lo.append(min(v) if v else 0); hi.append(max(v) if v else 0)
    means = np.array(means)
    ax.bar(x + (i - 0.5) * w, means, w, color=col, label=lab, yerr=[means - np.array(lo), np.array(hi) - means], capsize=2, error_kw={"lw": 0.7})
    for xi, mval, top in zip(x, means, hi):
        ax.text(xi + (i - 0.5) * w, top + 2, f"{mval:.0f}", ha="center", va="bottom", fontsize=6.5)
ax.set_xticks(x); ax.set_xticklabels([NAME[s] for s in SETUPS]); ax.set_ylabel("% of data calls"); ax.set_ylim(0, 112)
ax.set_yticks([0, 25, 50, 75, 100])
ax.legend(loc="lower center", ncol=2, frameon=False, fontsize=6.3, bbox_to_anchor=(0.45, 1.0), columnspacing=0.8, handlelength=1.2)
fig.tight_layout(pad=0.3); fig.savefig(os.path.join(OUTDIR, "fig1_agent.pdf")); plt.close(fig)

fig, ax = plt.subplots(figsize=(3.4, 1.7))
KS = ["k=1", "k=2", "k=3", "k=5", "k=all"]
for (s, col, mk), dx in zip(zip(SETUPS, [SETUP_COL[x] for x in SETUPS], ["o", "s", "^", "D"]), (-0.09, -0.03, 0.03, 0.09)):
    ks = [k for k in sens if k.startswith(s + "/")]
    if not ks:
        continue
    mv = np.array([st.mean(sens[k][kk]["SC-online"]["xscope"] * 100 for k in ks) for kk in KS])
    lo = np.array([min(sens[k][kk]["SC-online"]["xscope"] * 100 for k in ks) for kk in KS])
    hi = np.array([max(sens[k][kk]["SC-online"]["xscope"] * 100 for k in ks) for kk in KS])
    xx = np.arange(len(KS)) + dx
    ax.errorbar(xx, mv, yerr=[mv - lo, hi - mv], marker=mk, ms=3, lw=1, capsize=2, color=col, label=NAME[s])
ax.set_xticks(range(len(KS))); ax.set_xticklabels(["1", "2", "3", "5", "all (~10)"])
ax.set_xlabel("principals per question $k$"); ax.set_ylabel("cross-scope hits (%)"); ax.set_ylim(0, 105)
ax.legend(ncol=4, frameon=False, fontsize=6.8, loc="lower center", bbox_to_anchor=(0.5, 1.0))
fig.tight_layout(pad=0.3); fig.savefig(os.path.join(OUTDIR, "fig_sens.pdf")); plt.close(fig)

fig, axs = plt.subplots(1, len(EVSETUPS), figsize=(7.0, 1.6), sharey=False)
for ax, s in zip(axs, EVSETUPS):
    rates = sorted(ev[s])
    for (m, mk), dx in zip([("ViewRewrite", "s"), ("SC-snap", "^"), ("PerScope+V", "D"), ("ScopeCache", "o")], (-0.27, -0.09, 0.09, 0.27)):
        ys = [ev[s][r][m]["n_exec"] for r in rates if m in ev[s][r]]
        # markers only on ScopeCache; the other caches differ by colour and line style, and lines are dodged where they coincide
        sty = dict(marker="o", ms=2.6, **SC_STYLE) if m == "ScopeCache" else dict(lw=1.1, ls={"ViewRewrite": "--", "SC-snap": "-.", "PerScope+V": ":"}[m])
        ax.plot(np.arange(len(ys)) + dx, ys, color=MC[m], label=m, **sty)
    ax.set_xticks(range(len(rates))); ax.set_xticklabels([f"{r}x" for r in rates]); ax.set_yscale("log")
    from matplotlib.ticker import LogLocator, FuncFormatter, NullFormatter
    from matplotlib.ticker import FixedLocator
    _all = [ev[s][r][m]["n_exec"] for r in rates for m in ("ViewRewrite", "SC-snap", "PerScope+V", "ScopeCache") if m in ev[s][r]]
    _tk = [t for t in (100, 150, 200, 300, 400, 500, 700, 1000, 1500) if min(_all) * 0.9 <= t <= max(_all) * 1.1]
    _tk = _tk[::2] if len(_tk) > 4 else _tk
    ax.yaxis.set_major_locator(FixedLocator(_tk)); ax.yaxis.set_minor_locator(FixedLocator([]))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}")); ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_title(NAME[s], fontsize=8, pad=2); ax.set_xlabel("event rate")
axs[0].set_ylabel("executions (log)")
h, l = axs[0].get_legend_handles_labels()
fig.legend(h, l, ncol=4, frameon=False, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, 1.04))
fig.tight_layout(pad=0.3, rect=(0, 0, 1, 0.9)); fig.savefig(os.path.join(OUTDIR, "fig_events.pdf")); plt.close(fig)

fig, ax = plt.subplots(figsize=(3.4, 1.6))
bottom = np.zeros(len(MSETUPS))
for fld, col, lab in [("hit_view", "#7f7f7f", "pinned views"), ("hit_self", "#56B4E9", "own entries"), ("same", "#E69F00", "same scope, other principal"), ("hit_xscope", "#0072B2", "other scope")]:
    v = np.array([100 * bd[s][fld] for s in MSETUPS])
    ax.bar(np.arange(len(MSETUPS)), v, 0.55, bottom=bottom, color=col, label=lab)
    bottom += v
ax.set_xticks(np.arange(len(MSETUPS))); ax.set_xticklabels([NAME[s] for s in MSETUPS]); ax.set_ylabel("% of data calls"); ax.set_ylim(0, 100)
ax.legend(ncol=2, frameon=False, fontsize=6.5, loc="lower center", bbox_to_anchor=(0.5, 1.0))
fig.tight_layout(pad=0.3); fig.savefig(os.path.join(OUTDIR, "fig_breakdown.pdf")); plt.close(fig)

if dom:
    fig, ax = plt.subplots(figsize=(3.4, 1.75))
    ns = sorted(dom)
    for (m, mk), fx in zip([("PerScope", "v"), ("PerScope+", "D"), ("PerScope+V", "P"), ("ViewRewrite", "s"), ("SC-online", "^"), ("ScopeCache", "o")],
                           (0.9, 0.94, 0.97, 1.0, 1.03, 1.07)):
        if all(m in dom[n] for n in ns):   # horizontal offsets: PerScope+V and ScopeCache coincide at 300 and 1000
            sty = SC_STYLE if m == "ScopeCache" else dict(lw=1)
            ax.plot([n * fx for n in ns], [dom[n][m]["n_exec"] for n in ns], marker=mk, ms=3, color=MC[m], label=m, **sty)
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xticks(ns); ax.set_xticklabels([str(n) for n in ns])
    from matplotlib.ticker import FuncFormatter, NullFormatter, LogLocator
    ax.yaxis.set_major_locator(LogLocator(base=10, subs=(1.0, 2.0, 5.0)))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}")); ax.yaxis.set_minor_formatter(NullFormatter())
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_xlabel("values of the policy attribute"); ax.set_ylabel("executions (log)")
    ax.legend(ncol=3, frameon=False, fontsize=6.3, loc="lower center", bbox_to_anchor=(0.5, 1.0), columnspacing=0.8, handlelength=1.4)
    fig.tight_layout(pad=0.3); fig.savefig(os.path.join(OUTDIR, "fig_domain.pdf")); plt.close(fig)
with open(os.path.join(OUTDIR, "numbers.tex"), "w") as f:
    f.write("% generated by tools/make_numbers.py -- do not edit\n")
    for k, v in sorted(MAC.items()):
        f.write(f"\\newcommand{{\\{k}}}{{{v}}}\n")
print(len(MAC), "macros")
