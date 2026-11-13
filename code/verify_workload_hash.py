"""Confirm default gen_workload is bit-identical to the pre-change hashes."""
import hashlib, sys
from engine import Env, gen_workload

EXPECTED = {
    ("tpch", 3, 400): "7814f78ce9cb2c39e388e2ded63441d0f3a7908fb42ee039609ce787a06e2133",
    ("tpch", 0, 400): "c352f7feb9bec0fbaa67e6afea2e07351c24e4b418faeb466660f47204f48312",
    ("synfg", 3, 700): "a98029c6ccae3b21f1a1aa339db735f6e960119eaf2aa4c053987f01c8c07edf",
    ("synfg", 0, 700): "55250baee86d40fb96ea0f3fbefe73f039e67c9714d2d9ee2ff2581e94ab2ee5",
}

def hash_wl(setup, seed, n_calls, n_users, **kw):
    env = Env(setup, seed, n_users)
    wl = gen_workload(env, n_calls, seed, ev_rate=1.0, **kw)
    env.con.close()
    def ser(it):
        if it[0] == "call":
            u, q = it[1], it[2]
            return (
                "call", u, tuple(q.metrics), tuple(q.group),
                tuple((c, tuple(v) if isinstance(v, (list, tuple, set)) else v) for c, v in q.filters),
                tuple(q.months),
            )
        return (it[0], it[1] if len(it) > 1 else None)
    return hashlib.sha256(repr([ser(it) for it in wl]).encode()).hexdigest()

def main():
    ok = True
    for (setup, seed, users), exp in EXPECTED.items():
        h = hash_wl(setup, seed, 300, users)
        h2 = hash_wl(setup, seed, 300, users, user_exp=0.8, metric_exp=0.9, dim_exp=0.7)
        status = "OK" if h == exp and h2 == exp else "FAIL"
        print(f"{setup} seed={seed} {status} {h}")
        if h != exp or h2 != exp:
            ok = False
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
