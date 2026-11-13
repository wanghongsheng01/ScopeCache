# ScopeCache analysis  (bootstrap seed 20261112, B=10000)

## v7fresh

cells=15  wl_preset=?  seeds=[3, 4, 5]  setups=['tpch', 'tpch', 'tpch']...

| setup | seed | SC-adaptP | ScopeCache | PerScope+V | chosen | ghost | unpin | wrong |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tpch | 3 | 348 | 328 | 352 | raw_hybrid | 42 | 4 | 0 |
| tpch | 4 | 264 | 312 | 328 | pop50 | 8 | 0 | 0 |
| tpch | 5 | 323 | 398 | 405 | pop50 | 12 | 0 | 0 |
| tpcds | 3 | 228 | 228 | 228 | raw_hybrid | 33 | 0 | 0 |
| tpcds | 4 | 243 | 243 | 250 | raw_hybrid | 25 | 0 | 0 |
| tpcds | 5 | 255 | 255 | 259 | raw_hybrid | 22 | 0 | 0 |
| bird | 3 | 193 | 193 | 193 | raw_hybrid | 0 | 0 | 0 |
| bird | 4 | 164 | 164 | 164 | raw_hybrid | 0 | 0 | 0 |
| bird | 5 | 223 | 223 | 223 | raw_hybrid | 0 | 0 | 0 |
| ent | 3 | 167 | 168 | 168 | atoms | 0 | 0 | 0 |
| ent | 4 | 150 | 150 | 150 | raw_hybrid | 0 | 0 | 0 |
| ent | 5 | 197 | 201 | 201 | atoms | 0 | 0 | 0 |
| synfg | 3 | 638 | 665 | 659 | pop50 | 96 | 2 | 0 |
| synfg | 4 | 541 | 635 | 605 | pop30 | 46 | 0 | 0 |
| synfg | 5 | 578 | 650 | 619 | pop30 | 59 | 0 | 0 |

ours total = 4512
vs ScopeCache: 7/7/1  ours 4512 vs 4813  (+6.3% exec)  Δtotal=-301  95% CI [-575, -61]  Δmean=-20.07 CI [-38.34, -4.07]  W−L CI [1, 10]  p=0.0100
vs PerScope+V: 10/5/0  ours 4512 vs 4804  (+6.1% exec)  Δtotal=-292  95% CI [-516, -101]  Δmean=-19.47 CI [-34.40, -6.73]  W−L CI [6, 13]  p=0.0000

