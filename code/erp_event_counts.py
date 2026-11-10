"""[Enterprise data; the per-endpoint extract is not released, only its output results/erp_event_counts.json.]
Permission-management writes in the ERP access log (aggregate counts per endpoint, from the ID-free extract
_private/erp/system_endpoints.tsv: endpoint path without parameters, call count, distinct callers, first/last time).
Writes results/erp_event_counts.json."""
import os, json, csv
from datetime import datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROUPS = {
    "user": ["/system/user/updateUserInfo", "/system/user/addUserInfo", "/system/user/addBatchUserInfo", "/system/user/disableUser"],
    "role": ["/system/role/updateRole", "/system/role/addRole", "/system/role/batchAdd", "/system/role/deleteRoleById", "/system/role/batchDelete"],
    "shop_assignment": ["/system/shop/updateShop", "/system/shop/updateById"],
    "dept": ["/system/dept/unperm/addOneDept", "/system/dept/updateDept", "/system/dept/deleteDept",
             "/system/dept/saveDeptUserPermission", "/system/dept/saveDeptPermission"],
}
rows = {r["p"]: r for r in csv.DictReader(open(os.path.join(ROOT, "_private", "erp", "system_endpoints.tsv")), delimiter="\t")}
t0 = min(datetime.fromisoformat(r["t0"]) for r in rows.values()); t1 = max(datetime.fromisoformat(r["t1"]) for r in rows.values())
days = (t1 - t0).total_seconds() / 86400
out = {"days": round(days, 1), "groups": {}, "endpoints": {}}
for g, eps in GROUPS.items():
    out["groups"][g] = sum(int(rows[e]["n"]) for e in eps if e in rows)
    for e in eps:
        if e in rows:
            out["endpoints"][e] = int(rows[e]["n"])
out["total"] = sum(out["groups"].values())
out["per_day"] = round(out["total"] / days, 2)
wl = json.load(open(os.path.join(ROOT, "results", "erp_workload_stats.json")))
out["report_calls_per_day"] = wl["calls_per_day"]
out["events_per_report_call"] = out["per_day"] / wl["calls_per_day"]
out["deactivations"] = out["endpoints"].get("/system/user/disableUser", 0)
out["role_edits"] = out["endpoints"].get("/system/role/updateRole", 0)
json.dump(out, open(os.path.join(ROOT, "results", "erp_event_counts.json"), "w"), indent=1)
print(json.dumps(out, indent=1))
