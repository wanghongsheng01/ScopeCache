"""Run the job lines of a file (arguments of run.py) with N parallel workers; one log per job."""
import sys, os, subprocess, re
from concurrent.futures import ThreadPoolExecutor
jobs, workers, logdir = sys.argv[1], int(sys.argv[2]), sys.argv[3]
PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".venv", "bin", "python")
lines = [l.split() for l in open(jobs) if l.strip()]

def run(args):
    tag = args[args.index("--tag") + 1]
    name = f"{tag}_{args[0]}_" + "_".join(a for a in args[1:args.index("--tag")] if not a.startswith("--") and a != "3000")
    with open(os.path.join(logdir, name + ".log"), "w") as f:
        return subprocess.call(["nice", PY, "-W", "ignore", "run.py"] + args, stdout=f, stderr=subprocess.STDOUT)

with ThreadPoolExecutor(workers) as ex:
    codes = list(ex.map(run, lines))
print("exit codes:", codes)
