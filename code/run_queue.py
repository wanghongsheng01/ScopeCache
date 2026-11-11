"""Run the shell commands of a queue file with N workers, in file order; one log per job.  Line format:
    <done-file>|<log name>|<shell command>
A job whose done-file exists is skipped, so the queue resumes after a reboot (every job writes its result file last)."""
import sys, os, subprocess
from concurrent.futures import ThreadPoolExecutor
queue, workers, logdir = sys.argv[1], int(sys.argv[2]), sys.argv[3]
here = os.path.dirname(os.path.abspath(__file__))
jobs = [l.rstrip("\n").split("|", 2) for l in open(queue) if l.strip() and not l.startswith("#")]


def run(job):
    done, name, cmd = job
    if os.path.exists(os.path.join(here, done)):
        return "skip"
    with open(os.path.join(logdir, name + ".log"), "w") as f:
        return subprocess.call(["nice", "-n", "10", "sh", "-c", cmd], cwd=here, stdout=f, stderr=subprocess.STDOUT)


with ThreadPoolExecutor(workers) as ex:
    codes = list(ex.map(run, jobs))
print("exit codes:", codes, flush=True)
