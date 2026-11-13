#!/bin/sh
# Build data/scopecache.duckdb (about 190 MB): TPC-H SF1 and TPC-DS SF1 via DuckDB's generators, BIRD financial
# from the official BIRD dev release, ENT synthetic.  Set BIRD_FINANCIAL to .../dev_databases/financial/financial.sqlite
set -e
cd "$(dirname "$0")/../code"
python3 -W ignore datasets.py tpch tpcds bird ent
