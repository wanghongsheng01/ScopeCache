"""SYN-FG: fully synthetic fine-grained permission policy on a public TPC-H SF1 fact table.

Targets (generator constraints, not copied from any production grant file):
  - about 700 principals, about 60 shared groups;
  - 250-350 distinct scopes;
  - median 1 principal per scope, mean about 2-3;
  - role types: hierarchical (region / nation shop-trees), two-value, single-value, IN-list, OR;
  - 20-30% of roles see the sensitive columns.

Actual counts are whatever a fixed seed produces; they are measured and reported, never padded.
The shop identifiers (SH000..) are generated here and are not recoded enterprise IDs.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict

# Deterministic occupancy: 240 singleton scopes + 60 shared groups = 300 scopes, 700 principals.
# 240*1 + 20*2 + 12*3 + 8*5 + 6*8 + 5*12 + 4*18 + 3*28 + 2*40
#   = 240 + 40 + 36 + 40 + 48 + 60 + 72 + 84 + 80 = 700.
N_USERS = 700
N_SHARED_GROUPS = 60
N_SINGLETONS = 240
N_SHOPS = 300
FACT_SEED = 41  # shop assignment; independent of the experiment policy seed
MULTI_OCC = (40, 40, 28, 28, 28, 18, 18, 18, 18, 12, 12, 12, 12, 12,
             8, 8, 8, 8, 8, 8, 5, 5, 5, 5, 5, 5, 5, 5,
             3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3,
             2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2)
assert len(MULTI_OCC) == N_SHARED_GROUPS and sum(MULTI_OCC) == N_USERS - N_SINGLETONS
assert N_SINGLETONS * 2 > N_SINGLETONS + N_SHARED_GROUPS  # majority of scopes are singletons => median 1
assert 250 <= N_SINGLETONS + N_SHARED_GROUPS <= 350
assert 2.0 <= N_USERS / (N_SINGLETONS + N_SHARED_GROUPS) <= 3.0


def occupancy():
    return [1] * N_SINGLETONS + list(MULTI_OCC)


def policy_stats(pol):
    """Distinct scopes = unique Policy.scope_key among active principals (same definition as setup_stats)."""
    sizes_map = Counter()
    kinds = Counter(ro.get("kind", "?") for ro in pol.roles.values())
    for u, us in pol.users.items():
        if not us["active"]:
            continue
        sizes_map[pol.scope_key(pol.scope(u))] += 1
    sizes = list(sizes_map.values())
    return {
        "n_users": sum(1 for us in pol.users.values() if us["active"]),
        "n_users_all": len(pol.users),
        "n_roles": len(pol.roles),
        "n_groups": len(pol.groups),
        "n_shared_groups": N_SHARED_GROUPS,
        "n_singleton_groups": N_SINGLETONS,
        "distinct_scopes": len(sizes),
        "users_per_scope_median": statistics.median(sizes) if sizes else None,
        "users_per_scope_mean": (sum(sizes) / len(sizes)) if sizes else None,
        "users_per_scope_max": max(sizes) if sizes else 0,
        "n_singleton_scopes": sum(1 for x in sizes if x == 1),
        "n_roles_sensitive": sum(1 for ro in pol.roles.values() if ro["cols"]),
        "frac_roles_sensitive": (sum(1 for ro in pol.roles.values() if ro["cols"]) / len(pol.roles)) if pol.roles else 0,
        "kind_counts": dict(kinds),
        "occupancy_hist": dict(sorted(Counter(sizes).items())),
        "in_target": bool(
            sizes
            and 250 <= len(sizes) <= 350
            and statistics.median(sizes) == 1
            and 2.0 <= (sum(sizes) / len(sizes)) <= 3.0
        ),
    }


def _unique(conj, used):
    key = tuple(sorted(
        (tuple(sorted((a, tuple(sorted(map(str, v)))) for a, v in c.items())) for c in conj)
    ))
    if key in used:
        return False
    used.add(key)
    return True


def fill_synfg(pol, n_users=N_USERS, n_shared=N_SHARED_GROUPS):
    """Populate pol.roles / groups / users.  `pol` is a Policy with domains and coarse sets already set."""
    rng = pol.rng
    shop_a = "shop"
    shops = sorted(pol.domains[shop_a], key=str)
    if len(shops) < N_SINGLETONS:
        raise RuntimeError(f"SYN-FG needs at least {N_SINGLETONS} shops, got {len(shops)}")
    nation_sets = sorted(pol.sp.get("coarse", {}).get("shop", []),
                         key=lambda s: (-len(s), tuple(sorted(map(str, s)))))
    region_sets = sorted(pol.sp.get("coarse", {}).get("shop_region", []),
                         key=lambda s: (-len(s), tuple(sorted(map(str, s)))))
    sens = frozenset(pol.sp["sensitive"])
    segs = sorted(pol.domains.get("c_mktsegment", []), key=str)
    used = set()
    specs = []  # (conj, kind) for the 60 shared roles, largest occupancy first

    def take(conj, kind):
        if _unique(conj, used):
            specs.append((conj, kind))
            return True
        return False

    for s in region_sets:
        take([{shop_a: frozenset(s)}], "hier_region")
    for s in nation_sets:
        take([{shop_a: frozenset(s)}], "hier_nation")

    # Two-value, IN-list, OR, until 60 unique shared roles.
    # Draw from a long deterministic stream of candidates.
    i = 0
    while len(specs) < n_shared:
        i += 1
        if i > 20_000:
            raise RuntimeError(f"could not build {n_shared} unique shared roles (have {len(specs)})")
        mode = i % 3
        if mode == 0 and len(shops) >= 2:
            a, b = rng.sample(shops, 2)
            take([{shop_a: frozenset([a, b])}], "two")
        elif mode == 1:
            k = 3 + (i % 6)  # 3..8
            if k <= len(shops):
                take([{shop_a: frozenset(rng.sample(shops, k))}], "in")
        else:
            s1 = frozenset(rng.sample(shops, 1 + (i % 3)))
            s2 = frozenset(rng.sample(shops, 1 + ((i + 1) % 3)))
            if segs and (i % 5 == 0):
                take([{shop_a: s1, "c_mktsegment": frozenset([rng.choice(segs)])},
                      {shop_a: s2}], "or")
            else:
                take([{shop_a: s1}, {shop_a: s2}], "or")
    specs = specs[:n_shared]

    # 240 unique single-shop roles for singleton principals (shops are SH000..; disjoint from nothing required).
    singles = shops[:N_SINGLETONS]
    if len(singles) < N_SINGLETONS:
        raise RuntimeError(f"not enough shops for singleton roles ({len(singles)})")

    # ~25% of all 300 roles see sensitive columns: 75 of 300.
    n_roles_total = n_shared + N_SINGLETONS
    n_sens = int(round(0.25 * n_roles_total))
    fin_flags = [True] * n_sens + [False] * (n_roles_total - n_sens)
    rng.shuffle(fin_flags)

    def add(conj, kind, fin):
        rid = len(pol.roles)
        pol.roles[rid] = {"conj": [dict(c) for c in conj], "cols": (sens if fin else frozenset()), "kind": kind}
        return rid

    shared_rids = []
    for j, (conj, kind) in enumerate(specs):
        shared_rids.append(add(conj, kind, fin_flags[j]))
    single_rids = []
    for j, sh in enumerate(singles):
        single_rids.append(add([{shop_a: frozenset([sh])}], "single", fin_flags[n_shared + j]))

    # Groups: 60 shared (group i -> {shared_rids[i]}), 240 singleton groups.
    for i, rid in enumerate(shared_rids):
        pol.groups[i] = {rid}
    for j, rid in enumerate(single_rids):
        pol.groups[n_shared + j] = {rid}

    # Assign principals: first 460 fill shared groups by MULTI_OCC; last 240 get singleton groups.
    uid = 0
    for i, occ in enumerate(MULTI_OCC):
        for _ in range(occ):
            pol.users[uid] = {"groups": {i}, "active": True}
            uid += 1
    for j in range(N_SINGLETONS):
        pol.users[uid] = {"groups": {n_shared + j}, "active": True}
        uid += 1
    assert uid == n_users == len(pol.users)
    return pol
