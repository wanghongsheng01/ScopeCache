"""Pre-registered v8 robustness / shifted-workload driver.

Skips complete cells. Never overwrites v5/v6/v7. Frozen SC-adaptP (unpin_min=40).
See 03_方法与实验/SC-adaptP_鲁棒性预注册_v8_20261112.md.
"""
from __future__ import annotations

import json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "code"
RESULTS = ROOT / "results"
LOGS = ROOT / "logs"
VENV_PY = ROOT / ".venv" / "bin" / "python"

METHODS = [
    "SC-adaptP", "ScopeCache", "PerScope+V", "PerScope+",
    "VR-adapt", "ViewRewrite", "SC-online", "SC-atoms",
]
SEEDS = [6, 7, 8, 9, 10]
PUBLIC = ["tpch", "tpcds", "bird", "ent"]
SETUPS = {"synfg": ("synfg", 700), **{s: (s, 400) for s in PUBLIC}}


def complete(path: Path, preset: str) -> bool:
    if not path.is_file():
        return False
    try:
        d = json.loads(path.read_text())
    except Exception:
        return False
    if not set(METHODS).issubset(d.get("methods", {})):
        return False
    if d.get("wl_preset", "default") != preset:
        return False
    if d.get("seed") is None:
        return False
    stats = d["methods"].get("SC-adaptP", {}).get("stats", {})
    try:
        umin = int(stats.get("unpin_min"))
    except (TypeError, ValueError):
        return False
    return umin == 40


def cells(which: str, part: str):
    tags = []
    if which in ("rob", "all"):
        tags.append(("v8rob", "default"))
    if which in ("shift", "all"):
        tags.append(("v8shift", "flatmix"))
    setups = []
    if part in ("synfg", "all"):
        setups.append("synfg")
    if part in ("public", "all"):
        setups.extend(PUBLIC)
    if part not in ("synfg", "public", "all"):
        # comma-separated setup names, e.g. bird,ent
        setups = [s.strip() for s in part.split(",") if s.strip()]
        unknown = [s for s in setups if s not in SETUPS]
        if unknown:
            raise SystemExit(f"unknown setups: {unknown}")
    for tag, preset in tags:
        for setup in setups:
            users = SETUPS[setup][1]
            for seed in SEEDS:
                yield tag, preset, setup, seed, users


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    part = sys.argv[2] if len(sys.argv) > 2 else "all"
    env = os.environ.copy()
    env["SC_DETCOST"] = "1"
    env["SC_THREADS"] = env.get("SC_THREADS", "2")
    env.pop("SC_UNPIN_MIN", None)
    env["PATH"] = str(ROOT / ".venv" / "bin") + os.pathsep + env.get("PATH", "")
    LOGS.mkdir(exist_ok=True)
    RESULTS.mkdir(exist_ok=True)
    todo = list(cells(which, part))
    n = len(todo)
    done = 0
    skipped = 0
    t_all = time.time()
    for i, (tag, preset, setup, seed, users) in enumerate(todo, 1):
        out = RESULTS / f"{tag}_{setup}_s{seed}.json"
        ts = time.strftime("%Y-%m-%d %H:%M:%S %Z")
        if complete(out, preset):
            print(f"===== SKIP complete {tag} {setup} seed={seed} {ts} ({i}/{n}) =====", flush=True)
            skipped += 1
            done += 1
            continue
        lock = RESULTS / f".lock_{tag}_{setup}_s{seed}"
        if lock.exists():
            try:
                lpid = int(lock.read_text().strip() or 0)
                os.kill(lpid, 0)
                print(f"===== SKIP locked by live pid {lpid}: {tag} {setup} seed={seed} {ts} =====", flush=True)
                skipped += 1
                continue
            except (ValueError, ProcessLookupError, PermissionError):
                lock.unlink(missing_ok=True)
        if out.exists():
            print(f"===== INCOMPLETE, rerun {out} {ts} =====", flush=True)
        print(f"===== {tag} {preset} {setup} seed={seed} {ts} ({i}/{n}) =====", flush=True)
        cmd = [
            str(VENV_PY), "-W", "ignore", "-u", "run.py", setup,
            "--seed", str(seed), "--calls", "3000", "--users", str(users),
            "--tag", tag, "--methods", ",".join(METHODS), "--wl-preset", preset,
        ]
        t0 = time.time()
        proc = subprocess.Popen(cmd, cwd=str(CODE), env=env)
        lock.write_text(str(proc.pid))
        rc = proc.wait()
        lock.unlink(missing_ok=True)
        r = subprocess.CompletedProcess(cmd, rc)
        if r.returncode != 0:
            print(f"FAILED rc={r.returncode} {tag} {setup} s{seed} after {time.time()-t0:.0f}s", flush=True)
            sys.exit(r.returncode)
        if not complete(out, preset):
            print(f"FAILED completeness {out}", flush=True)
            sys.exit(2)
        print(f"===== done {tag} {setup} seed={seed} wall={time.time()-t0:.0f}s =====", flush=True)
        done += 1
    print(
        f"===== v8 {which} {part} finished {time.strftime('%Y-%m-%d %H:%M:%S %Z')} "
        f"done={done}/{n} skipped={skipped} elapsed={time.time()-t_all:.0f}s =====",
        flush=True,
    )


if __name__ == "__main__":
    main()
