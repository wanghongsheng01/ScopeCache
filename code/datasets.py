"""Build one wide 'main table' per setup (the shape a governed metric compiler queries) and describe its
semantic layer: dimensions, policy attributes, base measures, metric formulas, mapped dimensions and
sensitive columns.  Public setups: TPC-H SF1, TPC-DS SF1, BIRD financial.  ENT is an enterprise-shaped
synthetic setup whose structure (org tree, data-scope modes, eq/in grants, metric types) is reconstructed
from the console code; it contains no company data."""
import os, sys, duckdb, numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "scopecache.duckdb")
# BIRD dev release: dev_databases/financial/financial.sqlite (https://bird-bench.github.io/)
BIRD = os.environ.get("BIRD_FINANCIAL", os.path.join(ROOT, "data", "financial.sqlite"))


def build_tpch(con, sf=1, name="tpch_wide"):
    try:
        con.execute("LOAD tpch")
    except Exception:
        con.execute("INSTALL tpch; LOAD tpch")
    con.execute(f"CALL dbgen(sf={sf})")
    con.execute(f"""CREATE OR REPLACE TABLE {name} AS
      SELECT (year(o_orderdate)*100+month(o_orderdate))::INT AS month,
             r.r_name AS c_region, n.n_name AS c_nation, c_mktsegment, p_mfgr, p_brand,
             split_part(p_type,' ',1) AS p_type1, l_shipmode, l_returnflag, o_orderpriority,
             sr.r_name AS s_region, o_custkey,
             l_extendedprice::DOUBLE AS price, l_discount::DOUBLE AS disc, l_tax::DOUBLE AS tax,
             l_quantity::DOUBLE AS qty, ps_supplycost::DOUBLE AS supplycost
      FROM lineitem JOIN orders ON l_orderkey=o_orderkey JOIN customer ON o_custkey=c_custkey
      JOIN nation n ON c_nationkey=n.n_nationkey JOIN region r ON n.n_regionkey=r.r_regionkey
      JOIN part ON l_partkey=p_partkey JOIN supplier ON l_suppkey=s_suppkey
      JOIN nation sn ON s_nationkey=sn.n_nationkey JOIN region sr ON sn.n_regionkey=sr.r_regionkey
      JOIN partsupp ON ps_partkey=l_partkey AND ps_suppkey=l_suppkey""")
    for t in ["lineitem", "orders", "customer", "nation", "region", "part", "supplier", "partsupp"]:
        con.execute(f"DROP TABLE {t}")


def build_tpcds(con):
    con.execute("INSTALL tpcds; LOAD tpcds; CALL dsdgen(sf=1)")
    con.execute("""CREATE OR REPLACE TABLE tpcds_wide AS
      SELECT (d_year*100+d_moy)::INT AS month, ca_state, i_category, i_class, i_brand, s_store_id,
             cd_gender, cd_education_status, cd_marital_status, ss_customer_sk,
             ss_quantity::DOUBLE AS qty, ss_sales_price::DOUBLE AS sales_price,
             ss_ext_sales_price::DOUBLE AS ext_sales, ss_ext_discount_amt::DOUBLE AS ext_disc,
             ss_net_paid::DOUBLE AS net_paid, ss_ext_wholesale_cost::DOUBLE AS wholesale, ss_net_profit::DOUBLE AS net_profit
      FROM store_sales JOIN date_dim ON ss_sold_date_sk=d_date_sk JOIN item ON ss_item_sk=i_item_sk
      JOIN store ON ss_store_sk=s_store_sk JOIN customer ON ss_customer_sk=c_customer_sk
      JOIN customer_address ON c_current_addr_sk=ca_address_sk
      JOIN customer_demographics ON ss_cdemo_sk=cd_demo_sk
      WHERE ca_state IS NOT NULL AND i_category IS NOT NULL""")
    tabs = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    for t in tabs:
        if not t.endswith("_wide"):
            con.execute(f"DROP TABLE {t}")


def build_bird(con):
    con.execute("INSTALL sqlite; LOAD sqlite")
    con.execute(f"ATTACH '{BIRD}' AS bird (TYPE SQLITE, READ_ONLY)")
    con.execute("""CREATE OR REPLACE TABLE bird_wide AS
      SELECT (year(CAST(t.date AS DATE))*100+month(CAST(t.date AS DATE)))::INT AS month, d.A3 AS region, d.A2 AS district,
             a.frequency, t.type AS ttype, coalesce(t.operation,'NA') AS operation,
             coalesce(nullif(t.k_symbol,' '),'NA') AS k_symbol, t.account_id,
             t.amount::DOUBLE AS amount, t.balance::DOUBLE AS balance
      FROM bird.trans t JOIN bird.account a USING(account_id) JOIN bird.district d ON a.district_id=d.district_id""")
    con.execute("DETACH bird")


def ent_tree(n=813, seed=7):
    """Synthetic org tree with the size reported in the console docs (813 departments); depth <= 6."""
    rng = np.random.default_rng(seed)
    parent, depth = [-1], [0]
    while len(parent) < n:
        cand = [i for i in range(len(parent)) if depth[i] < 5]
        w = np.array([3.0 if depth[i] < 2 else 1.0 for i in cand])
        p = int(rng.choice(cand, p=w / w.sum()))
        parent.append(p); depth.append(depth[p] + 1)
    return parent, depth


def build_ent(con, rows=2_000_000, seed=11):
    rng = np.random.default_rng(seed)
    parent, depth = ent_tree()
    n = len(parent)
    kids = {i: [] for i in range(n)}
    for i, p in enumerate(parent):
        if p >= 0: kids[p].append(i)
    leaves = [i for i in range(n) if not kids[i]]
    # departments that own sales are leaves; activity is skewed
    w = rng.zipf(1.6, len(leaves)).astype(float); w /= w.sum()
    dept = rng.choice(leaves, size=rows, p=w)
    brand = rng.choice(12, size=rows, p=np.r_[np.full(4, .15), np.full(8, .05)])
    channel = rng.choice(6, size=rows, p=[.35, .25, .15, .1, .1, .05])
    country = rng.choice(20, size=rows, p=(lambda x: x / x.sum())(rng.zipf(1.8, 20).astype(float)))
    cat = rng.choice(30, size=rows)
    mi = rng.integers(0, 36, size=rows)
    month = (2024 + mi // 12) * 100 + mi % 12 + 1
    qty = rng.integers(1, 20, size=rows).astype(float)
    price = np.round(rng.lognormal(4.0, 0.6, size=rows), 2)
    amount = np.round(qty * price, 2)
    cost = np.round(amount * rng.uniform(0.45, 0.75, size=rows), 2)
    refund = np.where(rng.random(rows) < 0.06, amount, 0.0)
    buyer = rng.integers(0, 120_000, size=rows)
    df = pd.DataFrame({"month": month.astype(np.int32), "dept": [f"D{d:03d}" for d in dept],
                       "brand": [f"B{b:02d}" for b in brand], "channel": [f"CH{c}" for c in channel],
                       "country": [f"C{c:02d}" for c in country], "category": [f"K{c:02d}" for c in cat],
                       "buyer": buyer, "qty": qty, "amount": amount, "cost": cost, "refund": refund})
    con.register("ent_df", df)
    con.execute("CREATE OR REPLACE TABLE ent_wide AS SELECT * FROM ent_df")
    con.unregister("ent_df")
    pd.DataFrame({"dept": [f"D{i:03d}" for i in range(n)], "parent": [f"D{p:03d}" if p >= 0 else None for p in parent],
                  "depth": depth}).to_csv(os.path.join(ROOT, "data", "ent_org_tree.csv"), index=False)


def build_synfg(con, n_shops=300, seed=41):
    """TPC-H SF1 with a fully synthetic shop dimension (SH000..).  Shops sit inside the customer's
    nation, about `n_shops` of them, with Zipf activity within each nation.  No enterprise IDs."""
    from synfg import N_SHOPS, FACT_SEED
    n_shops = n_shops or N_SHOPS
    seed = FACT_SEED if seed is None else seed
    build_tpch(con, sf=1, name="tpch_wide")
    cust = con.execute("SELECT DISTINCT o_custkey AS custkey, c_nation AS nation, c_region AS region FROM tpch_wide").df()
    rng = np.random.default_rng(seed)
    nat_info = cust.groupby(["nation", "region"], as_index=False).size().rename(columns={"size": "n"})
    n_nat = len(nat_info)
    if n_shops < n_nat:
        raise ValueError(f"n_shops={n_shops} < number of nations {n_nat}")
    raw = nat_info["n"].to_numpy(dtype=float)
    raw = raw / raw.sum() * (n_shops - n_nat)
    extra = np.floor(raw).astype(int)
    rem = int(n_shops - n_nat - extra.sum())
    frac = raw - extra
    order = np.argsort(-frac)
    extra[order[:rem]] += 1
    n_per = extra + 1
    shops = []
    k = 0
    for i, row in nat_info.iterrows():
        for _ in range(int(n_per[i])):
            shops.append((f"SH{k:03d}", row["nation"], row["region"]))
            k += 1
    if k != n_shops:
        raise RuntimeError(f"allocated {k} shops, wanted {n_shops}")
    shops_by_nat = {}
    for sh, nat, _reg in shops:
        shops_by_nat.setdefault(nat, []).append(sh)
    shop_of = {}
    for nat, g in cust.groupby("nation"):
        sl = shops_by_nat[nat]
        w = 1.0 / np.arange(1, len(sl) + 1)
        rng.shuffle(w)
        w /= w.sum()
        assigned = rng.choice(sl, size=len(g), p=w)
        for ck, sh in zip(g["custkey"].to_numpy(), assigned):
            shop_of[int(ck)] = sh
    map_df = pd.DataFrame({"custkey": list(shop_of.keys()), "shop": [shop_of[c] for c in shop_of]})
    shop_meta = pd.DataFrame(shops, columns=["shop", "shop_nation", "shop_region"])
    map_df = map_df.merge(shop_meta, on="shop")
    con.register("shop_map", map_df)
    con.execute("""CREATE OR REPLACE TABLE synfg_wide AS
      SELECT t.*, m.shop, m.shop_nation, m.shop_region
      FROM tpch_wide t JOIN shop_map m ON t.o_custkey = m.custkey""")
    con.unregister("shop_map")
    con.execute("DROP TABLE tpch_wide")
    out_csv = os.path.join(ROOT, "data", "synfg_shop_tree.csv")
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    shop_meta.to_csv(out_csv, index=False)


ERP_DIR = os.path.join(ROOT, "_private", "erp")          # read-only ID extract of the ERP grant tables (not released)
ERP_GRANTS = os.path.join(ERP_DIR, "erp_grants_coded.json")


def build_erp(con, rows=2_000_000, seed=13):
    """ERP setup: the real account->shop grants of the company's ERP system (active accounts, IDs recoded to
    S###/A####), over a synthetic sales fact table on the same shops.  No business data is read."""
    acc = pd.read_csv(os.path.join(ERP_DIR, "account.tsv"), sep="\t")
    active = set(acc[acc.deleted == 0].id)
    sh = pd.read_csv(os.path.join(ERP_DIR, "account_shop.tsv"), sep="\t")
    sh = sh[sh.account_id.isin(active)]
    shops = sorted(sh.shop_id.unique())
    scode = {s: f"S{i:03d}" for i, s in enumerate(shops)}
    accs = sorted(sh.account_id.unique())
    grants = {f"A{i:04d}": sorted({scode[x] for x in sh[sh.account_id == a].shop_id}) for i, a in enumerate(accs)}
    import json
    with open(ERP_GRANTS, "w") as f:
        json.dump(grants, f)
    os.chmod(ERP_GRANTS, 0o600)
    rng = np.random.default_rng(seed)
    w = 1.0 / np.arange(1, len(shops) + 1); rng.shuffle(w); w /= w.sum()      # Zipf(1) shop activity, every shop sells
    shop = rng.choice(len(shops), size=rows, p=w)
    channel = rng.choice(6, size=rows, p=[.35, .25, .15, .1, .1, .05])
    country = rng.choice(20, size=rows, p=(lambda x: x / x.sum())(rng.zipf(1.8, 20).astype(float)))
    cat = rng.choice(30, size=rows)
    mi = rng.integers(0, 36, size=rows)
    month = (2024 + mi // 12) * 100 + mi % 12 + 1
    qty = rng.integers(1, 20, size=rows).astype(float)
    price = np.round(rng.lognormal(4.0, 0.6, size=rows), 2)
    amount = np.round(qty * price, 2)
    cost = np.round(amount * rng.uniform(0.45, 0.75, size=rows), 2)
    refund = np.where(rng.random(rows) < 0.06, amount, 0.0)
    buyer = rng.integers(0, 120_000, size=rows)
    df = pd.DataFrame({"month": month.astype(np.int32), "shop": [f"S{x:03d}" for x in shop], "channel": [f"CH{c}" for c in channel],
                       "country": [f"C{c:02d}" for c in country], "category": [f"K{c:02d}" for c in cat],
                       "buyer": buyer, "qty": qty, "amount": amount, "cost": cost, "refund": refund})
    con.register("erp_df", df)
    con.execute("CREATE OR REPLACE TABLE erp_wide AS SELECT * FROM erp_df")
    con.unregister("erp_df")


def dom_grants_path(n):
    return os.path.join(ROOT, "data", f"dom{n}_grants.json")


def build_dom(con, n, rows=1_000_000, seed=17, n_users=400):
    """Policy-domain sweep: one policy attribute 'unit' with n values (synthetic), 400 principals whose scopes are
    random value sets with ERP-like relative sizes (median about 5% of the domain, heavy tail)."""
    import json
    rng = np.random.default_rng(seed + n)
    w = 1.0 / np.arange(1, n + 1); rng.shuffle(w); w /= w.sum()
    unit = rng.choice(n, size=rows, p=w)
    channel = rng.choice(6, size=rows, p=[.35, .25, .15, .1, .1, .05])
    country = rng.choice(20, size=rows, p=(lambda x: x / x.sum())(rng.zipf(1.8, 20).astype(float)))
    cat = rng.choice(30, size=rows)
    mi = rng.integers(0, 36, size=rows)
    month = (2024 + mi // 12) * 100 + mi % 12 + 1
    qty = rng.integers(1, 20, size=rows).astype(float)
    price = np.round(rng.lognormal(4.0, 0.6, size=rows), 2)
    amount = np.round(qty * price, 2)
    cost = np.round(amount * rng.uniform(0.45, 0.75, size=rows), 2)
    refund = np.where(rng.random(rows) < 0.06, amount, 0.0)
    buyer = rng.integers(0, 120_000, size=rows)
    df = pd.DataFrame({"month": month.astype(np.int32), "unit": [f"U{x:04d}" for x in unit], "channel": [f"CH{c}" for c in channel],
                       "country": [f"C{c:02d}" for c in country], "category": [f"K{c:02d}" for c in cat],
                       "buyer": buyer, "qty": qty, "amount": amount, "cost": cost, "refund": refund})
    con.register("dom_df", df)
    con.execute(f"CREATE OR REPLACE TABLE dom{n}_wide AS SELECT * FROM dom_df")
    con.unregister("dom_df")
    vals = [f"U{x:04d}" for x in range(n)]
    grants = {}
    for u in range(n_users):
        k = int(min(n, max(1, round(n * min(1.0, rng.lognormal(np.log(0.05), 1.2))))))
        grants[f"P{u:04d}"] = sorted(rng.choice(vals, size=k, replace=False).tolist())
    with open(dom_grants_path(n), "w") as f:
        json.dump(grants, f)


# ---------------------------------------------------------------------------------------------------------
# Semantic layers.  measures: name -> (agg, sql_expr, columns).  metrics: name -> formula over measures
# (or "DISTINCT:col" for non-decomposable).  mapped: dim -> (source column, {value: group}).
# hier: policy attribute -> (coarse attribute) used to phrase region-level grants.

def spec(name):
    if name.startswith("tpch") and name[4:].isdigit():          # scale run: TPC-H at scale factor N
        sp = spec("tpch")
        sp.update(table=f"{name}_wide", db=DB.replace("scopecache.duckdb", f"scopecache_{name}.duckdb"))
        return sp
    if name == "tpch":
        brands = [f"Brand#{a}{b}" for a in range(1, 6) for b in range(1, 6)]
        return dict(table="tpch_wide", policy=["c_nation", "c_mktsegment", "p_mfgr"],
                    hier={"c_nation": "c_region"},
                    dims=["c_region", "c_nation", "c_mktsegment", "p_mfgr", "p_brand", "p_type1", "l_shipmode",
                          "l_returnflag", "o_orderpriority", "s_region"],
                    measures={"revenue": ("sum", "price*(1-disc)", ["price", "disc"]),
                              "gross": ("sum", "price", ["price"]),
                              "disc_amt": ("sum", "price*disc", ["price", "disc"]),
                              "tax_amt": ("sum", "price*(1-disc)*tax", ["price", "disc", "tax"]),
                              "qty": ("sum", "qty", ["qty"]), "lines": ("count", "*", []),
                              "max_price": ("max", "price", ["price"]),
                              "cost": ("sum", "supplycost*qty", ["supplycost", "qty"])},
                    metrics={"revenue": "revenue", "gross_sales": "gross", "discount_rate": "disc_amt/gross",
                             "avg_qty": "qty/lines", "order_lines": "lines", "max_price": "max_price",
                             "tax": "tax_amt", "margin": "revenue-cost", "margin_rate": "(revenue-cost)/revenue",
                             "customers": "DISTINCT:o_custkey"},
                    sensitive=["supplycost"],
                    mapped={"brand_group": ("p_brand", {b: f"G{i % 5}" for i, b in enumerate(brands)})},
                    alt_measures={"revenue": ("sum", "price*(1-disc)*(1+tax)", ["price", "disc", "tax"]),
                                  "gross": ("sum", "price*(1+tax)", ["price", "tax"]),
                                  "cost": ("sum", "supplycost*qty*1.05", ["supplycost", "qty"])},
                    alt_metrics={"discount_rate": "disc_amt/(gross+tax_amt)", "avg_qty": "qty/(lines+0.0)",
                                 "margin_rate": "(revenue-cost)/gross"})
    if name == "tpcds":
        return dict(table="tpcds_wide", policy=["ca_state", "i_category"], hier={},
                    dims=["ca_state", "i_category", "i_class", "s_store_id", "cd_gender", "cd_education_status",
                          "cd_marital_status"],
                    measures={"net_paid": ("sum", "net_paid", ["net_paid"]), "ext_sales": ("sum", "ext_sales", ["ext_sales"]),
                              "ext_disc": ("sum", "ext_disc", ["ext_disc"]), "qty": ("sum", "qty", ["qty"]),
                              "lines": ("count", "*", []), "max_price": ("max", "sales_price", ["sales_price"]),
                              "wholesale": ("sum", "wholesale", ["wholesale"]), "profit": ("sum", "net_profit", ["net_profit"])},
                    metrics={"net_sales": "net_paid", "gross_sales": "ext_sales", "discount_rate": "ext_disc/ext_sales",
                             "units": "qty", "avg_units": "qty/lines", "max_price": "max_price", "profit": "profit",
                             "profit_rate": "profit/net_paid", "markup": "(ext_sales-wholesale)/wholesale",
                             "customers": "DISTINCT:ss_customer_sk"},
                    sensitive=["wholesale", "net_profit"],
                    mapped={"division": ("i_category", None)},
                    alt_measures={"net_paid": ("sum", "net_paid-ext_disc*0", ["net_paid", "ext_disc"]),
                                  "ext_sales": ("sum", "ext_sales-ext_disc", ["ext_sales", "ext_disc"]),
                                  "profit": ("sum", "net_profit+0.5*ext_disc", ["net_profit", "ext_disc"])},
                    alt_metrics={"discount_rate": "ext_disc/(ext_sales+ext_disc)", "profit_rate": "profit/ext_sales",
                                 "avg_units": "qty/(lines+0.0)"})
    if name == "bird":
        return dict(table="bird_wide", policy=["district", "frequency"], hier={"district": "region"},
                    dims=["region", "district", "frequency", "ttype", "operation", "k_symbol"],
                    measures={"amount": ("sum", "amount", ["amount"]), "tx": ("count", "*", []),
                              "max_amount": ("max", "amount", ["amount"]), "min_amount": ("min", "amount", ["amount"]),
                              "balance": ("sum", "balance", ["balance"]),
                              "credit": ("sum", "CASE WHEN ttype='PRIJEM' THEN amount ELSE 0 END", ["amount", "ttype"])},
                    metrics={"volume": "amount", "transactions": "tx", "avg_amount": "amount/tx",
                             "max_amount": "max_amount", "min_amount": "min_amount", "avg_balance": "balance/tx",
                             "credit_share": "credit/amount", "accounts": "DISTINCT:account_id"},
                    sensitive=["balance"],
                    mapped={"symbol_group": ("k_symbol", None)},
                    alt_measures={"amount": ("sum", "abs(amount)", ["amount"]),
                                  "credit": ("sum", "CASE WHEN ttype IN ('PRIJEM') AND operation<>'NA' THEN amount ELSE 0 END",
                                             ["amount", "ttype", "operation"])},
                    alt_metrics={"avg_amount": "amount/(tx+0.0)", "credit_share": "credit/(amount+1)"})
    if name == "ent":
        return dict(table="ent_wide", policy=["dept", "brand", "channel"], hier={},
                    dims=["dept", "brand", "channel", "country", "category"],
                    measures={"amount": ("sum", "amount", ["amount"]), "qty": ("sum", "qty", ["qty"]),
                              "orders": ("count", "*", []), "refund": ("sum", "refund", ["refund"]),
                              "cost": ("sum", "cost", ["cost"]), "max_amount": ("max", "amount", ["amount"])},
                    metrics={"sales": "amount", "units": "qty", "orders": "orders", "aov": "amount/orders",
                             "refund_rate": "refund/amount", "gross_margin": "(amount-cost)/amount",
                             "gross_profit": "amount-cost", "max_order": "max_amount", "buyers": "DISTINCT:buyer"},
                    sensitive=["cost"],
                    mapped={"product_line": ("category", None)},
                    alt_measures={"amount": ("sum", "amount-refund", ["amount", "refund"]),
                                  "cost": ("sum", "cost*1.02", ["cost"])},
                    alt_metrics={"aov": "amount/(orders+0.0)", "refund_rate": "refund/(amount+refund)",
                                 "gross_margin": "(amount-cost-refund)/amount"})
    if name == "erp":
        return dict(table="erp_wide", policy=["shop"], hier={}, real_grants=ERP_GRANTS, db=DB.replace("scopecache.duckdb", "scopecache_erp.duckdb"),
                    dims=["shop", "channel", "country", "category"],
                    measures={"amount": ("sum", "amount", ["amount"]), "qty": ("sum", "qty", ["qty"]),
                              "orders": ("count", "*", []), "refund": ("sum", "refund", ["refund"]),
                              "cost": ("sum", "cost", ["cost"]), "max_amount": ("max", "amount", ["amount"])},
                    metrics={"sales": "amount", "units": "qty", "orders": "orders", "aov": "amount/orders",
                             "refund_rate": "refund/amount", "gross_margin": "(amount-cost)/amount",
                             "gross_profit": "amount-cost", "max_order": "max_amount", "buyers": "DISTINCT:buyer"},
                    sensitive=["cost"],
                    mapped={"product_line": ("category", None)},
                    alt_measures={"amount": ("sum", "amount-refund", ["amount", "refund"]),
                                  "cost": ("sum", "cost*1.02", ["cost"])},
                    alt_metrics={"aov": "amount/(orders+0.0)", "refund_rate": "refund/(amount+refund)",
                                 "gross_margin": "(amount-cost-refund)/amount"})
    if name == "synfg":
        brands = [f"Brand#{a}{b}" for a in range(1, 6) for b in range(1, 6)]
        return dict(table="synfg_wide", policy=["shop", "c_mktsegment"], hier={"shop": "c_nation"},
                    synfg=True, n_users=700, n_groups=60,
                    db=DB.replace("scopecache.duckdb", "scopecache_synfg.duckdb"),
                    dims=["c_region", "c_nation", "c_mktsegment", "p_mfgr", "p_brand", "p_type1", "l_shipmode",
                          "l_returnflag", "o_orderpriority", "s_region", "shop"],
                    measures={"revenue": ("sum", "price*(1-disc)", ["price", "disc"]),
                              "gross": ("sum", "price", ["price"]),
                              "disc_amt": ("sum", "price*disc", ["price", "disc"]),
                              "tax_amt": ("sum", "price*(1-disc)*tax", ["price", "disc", "tax"]),
                              "qty": ("sum", "qty", ["qty"]), "lines": ("count", "*", []),
                              "max_price": ("max", "price", ["price"]),
                              "cost": ("sum", "supplycost*qty", ["supplycost", "qty"])},
                    metrics={"revenue": "revenue", "gross_sales": "gross", "discount_rate": "disc_amt/gross",
                             "avg_qty": "qty/lines", "order_lines": "lines", "max_price": "max_price",
                             "tax": "tax_amt", "margin": "revenue-cost", "margin_rate": "(revenue-cost)/revenue",
                             "customers": "DISTINCT:o_custkey"},
                    sensitive=["supplycost"],
                    mapped={"brand_group": ("p_brand", {b: f"G{i % 5}" for i, b in enumerate(brands)})},
                    alt_measures={"revenue": ("sum", "price*(1-disc)*(1+tax)", ["price", "disc", "tax"]),
                                  "gross": ("sum", "price*(1+tax)", ["price", "tax"]),
                                  "cost": ("sum", "supplycost*qty*1.05", ["supplycost", "qty"])},
                    alt_metrics={"discount_rate": "disc_amt/(gross+tax_amt)", "avg_qty": "qty/(lines+0.0)",
                                 "margin_rate": "(revenue-cost)/gross"})
    if name.startswith("dom"):
        n = int(name[3:])
        return dict(table=f"dom{n}_wide", policy=["unit"], hier={}, real_grants=dom_grants_path(n),
                    db=DB.replace("scopecache.duckdb", f"scopecache_dom{n}.duckdb"),
                    dims=["unit", "channel", "country", "category"],
                    measures={"amount": ("sum", "amount", ["amount"]), "qty": ("sum", "qty", ["qty"]),
                              "orders": ("count", "*", []), "refund": ("sum", "refund", ["refund"]),
                              "cost": ("sum", "cost", ["cost"]), "max_amount": ("max", "amount", ["amount"])},
                    metrics={"sales": "amount", "units": "qty", "orders": "orders", "aov": "amount/orders",
                             "refund_rate": "refund/amount", "gross_margin": "(amount-cost)/amount",
                             "gross_profit": "amount-cost", "max_order": "max_amount", "buyers": "DISTINCT:buyer"},
                    sensitive=["cost"],
                    mapped={"product_line": ("category", None)},
                    alt_measures={"amount": ("sum", "amount-refund", ["amount", "refund"]),
                                  "cost": ("sum", "cost*1.02", ["cost"])},
                    alt_metrics={"aov": "amount/(orders+0.0)", "refund_rate": "refund/(amount+refund)",
                                 "gross_margin": "(amount-cost-refund)/amount"})
    raise KeyError(name)


if __name__ == "__main__":
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    which = sys.argv[1:] or ["tpch", "tpcds", "bird", "ent"]
    for w in which:
        mem = duckdb.connect()  # generate in memory so dropped base tables never touch the disk file
        if (w.startswith("tpch") and w[4:].isdigit()) or w == "synfg":
            mem.execute("SET memory_limit='5GB'; SET threads=4; SET preserve_insertion_order=false")
            mem.execute(f"SET temp_directory='{os.path.join(ROOT, 'data', 'tmp_build')}'")
        (lambda c: build_dom(c, int(w[3:])))(mem) if w.startswith("dom") else \
        (lambda c: build_tpch(c, int(w[4:]), f"{w}_wide"))(mem) if (w.startswith("tpch") and w[4:].isdigit()) else \
            {"tpch": build_tpch, "tpcds": build_tpcds, "bird": build_bird, "ent": build_ent, "erp": build_erp, "synfg": build_synfg}[w](mem)
        mem.execute(f"ATTACH '{spec(w).get('db', DB)}' AS out")
        mem.execute(f"CREATE OR REPLACE TABLE out.{w}_wide AS SELECT * FROM {w}_wide ORDER BY month")
        print(w, mem.execute(f"SELECT count(*) FROM out.{w}_wide").fetchone(), flush=True)
        mem.execute("DETACH out"); mem.close()
