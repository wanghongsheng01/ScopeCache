"""Aggregate results/*.json into results/summary.md (mean ± sd over seeds) and results/summary.json."""
import json, glob, os, collections
import numpy as np
R = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
rows = collections.defaultdict(lambda: collections.defaultdict(list))
meta = {}
for f in sorted(glob.glob(os.path.join(R, "*_s*.json"))):
    d = json.load(open(f)); tag = os.path.basename(f).split("_")[0]
    if "methods" not in d:
        continue
    for m, r in d["methods"].items():
        rows[(tag, d["setup"])][m].append(r)
    meta[(tag, d["setup"])] = d
KEYS = [("hit_rate", "命中率", "{:.3f}"), ("wrong", "错误答案", "{:.1f}"), ("overpriv", "越权", "{:.1f}"), ("stale", "陈旧", "{:.1f}"),
        ("n_exec", "数仓执行次数", "{:.0f}"), ("exec_s", "执行秒", "{:.1f}"), ("lat_model_mean", "建模延迟均值 s", "{:.3f}"),
        ("lat_model_p95", "建模 P95 s", "{:.3f}"), ("lat_local_p95", "本地 P95 ms", "{:.1f}"), ("peak_rows", "峰值行数", "{:.0f}")]
out, js = [], {}
for (tag, s), ms in sorted(rows.items()):
    n = len(next(iter(ms.values())))
    d = meta[(tag, s)]
    out.append(f"\n### {tag} / {s}（种子数 {n}，每种子 {d['calls']} 次调用，评测 80%；预算 {d['budget']} 行；事件倍率 {d['ev']}；漂移 {d.get('drift', 0)}）\n")
    out.append("| 方法 | " + " | ".join(k[1] for k in KEYS) + " |")
    out.append("|" + "---|" * (len(KEYS) + 1))
    js[f"{tag}/{s}"] = {}
    for m, rs in ms.items():
        cells = []
        js[f"{tag}/{s}"][m] = {}
        for k, _, fmt in KEYS:
            v = np.array([r[k] * (1000 if k == "lat_local_p95" else 1) for r in rs], dtype=float)
            js[f"{tag}/{s}"][m][k] = [float(v.mean()), float(v.std())]
            cells.append(fmt.format(v.mean()) + (f" ± {fmt.format(v.std())}" if n > 1 and k in ("hit_rate", "n_exec", "overpriv", "wrong") else ""))
        dc = np.mean([r["data_calls"] for r in rs]); js[f"{tag}/{s}"][m]["data_calls"] = float(dc)
        js[f"{tag}/{s}"][m]["stats"] = rs[0]["stats"]
        out.append(f"| {m} | " + " | ".join(cells) + " |")
open(os.path.join(R, "summary.md"), "w").write("# 结果汇总（由 aggregate.py 自动生成，请勿手改）\n" + "\n".join(out) + "\n")
json.dump(js, open(os.path.join(R, "summary.json"), "w"), indent=1)
print("\n".join(out))
