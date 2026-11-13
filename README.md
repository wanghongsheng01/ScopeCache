# ScopeCache: Safe Reuse of Query Results Across Permission Scopes

Artifact for the PVLDB Volume 20 / VLDB 2027 submission. It contains the cache implementations (including the frozen holdout-and-evidence-threshold configuration, SC-adaptP), the workload and policy generators, the recorded LLM-agent traces, the frozen result files behind every table and figure, and the scripts that regenerate the paper's numbers from those files.

This package **does not** include an enterprise authorization setup. An earlier draft used such a setup; it has been removed from the paper and from this artifact. All experiments use public datasets (TPC-H, TPC-DS, BIRD) and fully synthetic policies (ENT and SYN-FG).

## Official headline (do not replace)

The official result is the frozen method (`unpin_min = 40`) on held-out seeds **3, 4, 5**: **10 wins / 5 ties / 0 losses** versus PerScope+V, 4,512 vs 4,804 executions (6.1% fewer), all `wrong = 0`. These numbers come from `results/v7fresh_*.json`. A later pre-registered robustness grid on seeds 6–10 (`results/v8rob_*.json`, `results/v8shift_*.json`) is reported in the paper as robustness and **does not replace** the 10/5/0 headline. Do not re-run those grids as a new official evaluation; the released JSON files are the record.

## Layout

| Path | Content |
|---|---|
| `code/engine.py` | Fact tables, semantic layer, policy model, fresh-execution oracle, rule-based workload generator |
| `code/caches.py` | All caches, including ScopeCache / SC-hybrid and the scope-partitioned baselines |
| `code/adapt_select.py` | Holdout configuration selection and evidence-threshold unpinning (the frozen SC-adaptP path) |
| `code/synfg.py` | Generator for the fine-grained synthetic shop policy (SYN-FG) |
| `code/run.py`, `code/run_v8.py` | Experiment drivers; each answer is compared with a fresh execution |
| `results/v7fresh_*.json` | Official headline runs (seeds 3–5) |
| `results/v7sens*.json` | Sensitivity to `unpin_min` on the same seeds, reported as sensitivity, not as a new choice of threshold |
| `results/v8rob_*.json`, `results/v8shift_*.json` | Pre-registered robustness (seeds 6–10; default Zipf and declared flatmix) |
| `results/v5*` | Development-grid and component studies (seeds 0–2; agent traces; event, domain, and budget sweeps). Not the headline. |
| `results/agent/` | Recorded LLM-agent traces |
| `data/llm_cache.tar.gz` | Prompts and responses of those traces (if present) |
| `paper/` | PVLDB Volume 20 manuscript sources. Headline macros at the end of `numbers.tex` are frozen; do not overwrite them from the development-grid generator. |

## Requirements

Python 3.9 or newer, `pip install -r requirements.txt` (DuckDB 1.4.5). DuckDB downloads its `tpch`, `tpcds`, and `sqlite` extensions on first use. BIRD: download the BIRD dev release from https://bird-bench.github.io/ and set `BIRD_FINANCIAL=/path/to/dev_databases/financial/financial.sqlite`.

## Reproduce numbers from the released files (recommended)

The tables and macros in the paper are determined by the released JSON files. With `SC_DETCOST=1`, eviction priorities and view benefits use the number of fact-table rows a re-computation scans, so wrong-answer counts, warehouse executions, and hit rates are deterministic for a given seed. Measured times depend on the machine.

```sh
pip install -r requirements.txt
# The official 10/5/0 headline and the v8 robustness tables:
python3 code/analyze_v8.py          # or the analysis notes under results/
# Regenerating development-grid macros (does not replace the frozen headline macros):
python3 paper/tools/make_numbers.py
```

## Rebuild data and optional re-execution

```sh
export BIRD_FINANCIAL=/path/to/dev_databases/financial/financial.sqlite
sh scripts/build_data.sh          # TPC-H, TPC-DS, ENT, SYN-FG (and BIRD if configured)
sh scripts/quick_check.sh         # one setup, every method, zero wrong answers
sh scripts/reproduce_agents.sh    # replay the released traces (no LLM calls)
```

Scripts such as `scripts/run_sc_fresh.sh` and `scripts/run_sc_v8rob.sh` show how the frozen grids were obtained. They are provided for transparency. **If you re-execute them, treat the output as a check against the released JSON, not as a new official result.** The paper's claims use the released files.

To re-record agent traces, unpack the LLM cache if present (`tar xzf data/llm_cache.tar.gz -C code`) and run `scripts/record_agents.sh`; cached requests need no API key.

## License

MIT (code). TPC data are generated under the TPC EULA; BIRD is distributed under its own license.

## Changelog

- 2026-11-12 (PVLDB): SC-adaptP code, SYN-FG generator, official v7fresh results (10/5/0, `unpin_min=40`), sensitivity, and pre-registered v8 robustness; PVLDB manuscript sources; ERP setup and ERP aggregate files removed from this artifact to match the submission. Headline numbers are unchanged from the frozen evaluation.
- 2026-11-11 and earlier: previous ICDE-draft package (superseded for this submission).
