"""Build references.bib from Crossref (DOIs) and the arXiv API (eprints); nothing is typed from memory."""
import json, re, time, sys, os, urllib.request, urllib.parse, xml.etree.ElementTree as ET
HERE = os.path.dirname(os.path.abspath(__file__))
REFS = [
 ("levy95", "10.1145/212433.220198"), ("halevy01", "10.1007/s007780100054"), ("chaudhuri95", "10.1109/ICDE.1995.380392"),
 ("goldstein01", "10.1145/375663.375706"), ("keller96", "10.1007/s007780050014"), ("deshpande98", "10.1145/276304.276328"),
 ("kalnis01", "10.1145/375663.375712"), ("bindschaedler26", "arXiv:2602.19811"),
 ("stonebraker74", "10.1145/800182.810400"), ("rizvi04", "10.1145/1007568.1007631"), ("zhang05", "10.1007/978-3-540-30570-5_18"),
 ("chaudhuri07", "10.1109/icde.2007.368976"), ("kabra06", "10.1145/1142473.1142489"), ("lefevre04", "10.1016/b978-012088469-8.50013-9"),
 ("guarnieri16", "10.1109/eurosp.2016.23"), ("sieve20", "10.14778/3407790.3407835"), ("shakya25", "arXiv:2511.14629"),
 ("dataguard26", "10.1109/icde65706.2026.00099"),
 ("hru96", "10.1145/233269.233333"), ("ivanova09", "10.1145/1559845.1559879"), ("nagel13", "10.1109/icde.2013.6544837"),
 ("dursun17", "10.1145/3035918.3035957"), ("snowflake16", "10.1145/2882903.2903741"), ("cloudviews18", "10.1145/3183713.3190656"),
 ("crystal21", "10.14778/3476249.3476292"), ("predcache24", "10.1145/3626246.3653395"), ("dynmv07", "10.1109/icde.2007.367898"),
 ("mistry01", "10.1145/375663.375703"), ("lbsc24", "10.1109/icde60146.2024.00373"), ("mvgpt26", "10.1109/icde65706.2026.00019"),
 ("gptcache23", "10.18653/v1/2023.nlposs-1.24"), ("meancache24", "arXiv:2403.02694"), ("vcache25", "arXiv:2502.03771"),
 ("plancache25", "arXiv:2506.14852"), ("gu25", "arXiv:2502.07776"), ("song24", "arXiv:2409.20002"), ("keycoll26", "arXiv:2601.23088"),
 ("agentfirst25", "arXiv:2509.00997"), ("wadlom26", "arXiv:2603.16104"), ("revocation26", "arXiv:2610.15991"),
 ("matoi26", "arXiv:2610.21394"), ("notrace26", "arXiv:2610.09286"), ("mcpgw26", "arXiv:2607.15593"), ("honeybee25", "arXiv:2505.01538"),
 ("rbact2s26", "arXiv:2607.22115"), ("rolerefusal25", "arXiv:2510.07642"), ("authzarch26", "arXiv:2609.15906"),
 ("plaintext26", "arXiv:2608.11730"), ("bird23", "arXiv:2305.03111"), ("duckdb19", "10.1145/3299869.3320212"),
 ("tpcds02", "10.1145/564691.564759"), ("kmn99", "10.1016/S0020-0190(99)00031-9"), ("celf07", "10.1145/1281192.1281239"),
 ("young94", "10.1007/BF01189992"),
]
MONTH = {}
# Crossref typesetting artefacts corrected by hand (the record itself is correct otherwise)
FIX = {"young94": "The k-server dual and loose competitiveness for paging"}
# venue/year corrections where the Crossref container is the series, not the proceedings
OVERRIDE = {"zhang05": {"booktitle": "Database Theory -- ICDT 2005, LNCS 3363", "year": "2005"},
            "keller96": {"journal": "The VLDB Journal"}}

def get(url):
    for i in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "scopecache-bib/1.0 (mailto:wanghongsheng@zju.edu.cn)"}), timeout=40) as r:
                return r.read()
        except Exception as e:
            err = e; time.sleep(2 + 2 * i)
    raise RuntimeError(f"{url}: {err}")

ACC = {"\u0301": "\\'", "\u0300": "\\`", "\u0308": '\\"', "\u0302": "\\^", "\u0303": "\\~", "\u030c": "\\v",
       "\u0327": "\\c", "\u0304": "\\=", "\u0306": "\\u", "\u030a": "\\r", "\u0328": "\\k", "\u030b": "\\H"}
SPECIAL = {"Å": "{\\AA}", "å": "{\\aa}", "Ø": "{\\O}", "ø": "{\\o}", "ß": "{\\ss}", "Đ": "{\\DJ}", "đ": "{\\dj}",
           "Ł": "{\\L}", "ł": "{\\l}", "Æ": "{\\AE}", "æ": "{\\ae}", "ı": "{\\i}"}


def latexify(s):
    """Non-ASCII letters to LaTeX accent commands (BibTeX abbreviates first names byte-wise)."""
    import unicodedata
    out = []
    for ch in s:
        if ord(ch) < 128:
            out.append(ch)
        elif ch in SPECIAL:
            out.append(SPECIAL[ch])
        else:
            d = unicodedata.normalize("NFD", ch)
            base, marks = d[0], d[1:]
            r = base
            for mk in marks:
                r = "{" + ACC[mk] + "{" + r + "}}" if mk in ACC else r
            out.append(r if ord(base) < 128 else "?")
    return "".join(out)


def tex(s):
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&amp;", "&").replace("&", "\\&").replace("%", "\\%").replace("_", "\\_").replace("#", "\\#")
    return re.sub(r"\s+", " ", s).strip()

PROPER = {"Snowflake", "Microsoft", "Hippocratic", "Sieve", "Crystal", "Matoi", "Zanzibar", "Truman", "Text-to-SQL", "Text-to-SQLs"}


def protect(title):
    # keep acronyms, mixed-case words and proper nouns as written under IEEEtran's title casing
    out = []
    for w in title.split(" "):
        core = re.sub(r"[^A-Za-z\-]", "", w)
        if (re.search(r"[A-Z].*[A-Z]|\d", w[1:] if len(w) > 1 else "") or re.match(r"^[A-Z]{2,}", w)
                or re.search(r"[a-z][A-Z]", w) or core in PROPER):
            out.append("{" + w + "}")
        else:
            out.append(w)
    return " ".join(out)

def crossref(key, doi):
    m = json.loads(get("https://api.crossref.org/works/" + urllib.parse.quote(doi)))["message"]
    typ = m["type"]
    authors = latexify(" and ".join(f"{a.get('family','')}, {a.get('given','')}".strip(", ") for a in m.get("author", [])))
    title = latexify(tex(m["title"][0])); venue = latexify(tex((m.get("container-title") or [""])[0])); year = m["issued"]["date-parts"][0][0]
    if m.get("subtitle"):
        title += ": " + tex(m["subtitle"][0])
    if year is None:   # some ICDE 1995 records carry no issued date; the venue string holds the year
        acr = (m.get("event") or {}).get("acronym", "")   # e.g. "ICDE-95"
        yy = re.search(r"-(\d\d)$", acr); year = (1900 + int(yy.group(1)) if int(yy.group(1)) > 50 else 2000 + int(yy.group(1))) if yy else ""
    title = FIX.get(key, title)
    pages = m.get("page", "").replace("-", "--")
    f = {"author": authors, "title": "{" + protect(title) + "}", "year": str(year), "doi": doi}
    if pages: f["pages"] = pages
    if typ == "journal-article":
        kind = "article"; f["journal"] = venue
        if m.get("volume"): f["volume"] = m["volume"]
        if m.get("issue"): f["number"] = m["issue"]
    elif typ in ("proceedings-article", "book-chapter"):
        kind = "inproceedings"; f["booktitle"] = venue or tex((m.get("publisher") or ""))
    else:
        kind = "misc"; f["howpublished"] = venue
    return kind, f

def arxiv(key, aid):
    x = get("http://export.arxiv.org/api/query?id_list=" + aid)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    e = ET.fromstring(x).find("a:entry", ns)
    title = re.sub(r"\s*\[[^\]]*[Rr]eport\]\s*$", "", tex(e.find("a:title", ns).text)); year = e.find("a:published", ns).text[:4]
    authors = latexify(" and ".join(a.find("a:name", ns).text for a in e.findall("a:author", ns)))
    return "misc", {"author": authors, "title": "{" + protect(title) + "}", "year": year,
                    "howpublished": f"arXiv:{aid}", "eprint": aid, "archivePrefix": "arXiv"}

out, log = [], []
for key, ident in REFS:
    kind, f = arxiv(key, ident[6:]) if ident.startswith("arXiv:") else crossref(key, ident)
    log.append((key, ident, f["title"][:80], f["year"]))
    f.update(OVERRIDE.get(key, {}))
    out.append(f"@{kind}{{{key},\n" + ",\n".join(f"  {k} = {v}" if k == "title" else f"  {k} = {{{v}}}" for k, v in f.items()) + "\n}\n")
    time.sleep(0.4)
extra = """@IEEEtranBSTCTL{IEEEexample:BSTcontrol,
  CTLuse_forced_etal = "yes",
  CTLmax_names_forced_etal = "6",
  CTLnames_show_etal = "3",
  CTLdash_repeated_names = "no"
}

@misc{tpch,
  author = {{Transaction Processing Performance Council}},
  title = {{TPC} Benchmark {H} Standard Specification, Revision 3.0.1},
  year = {2022},
  howpublished = {\\url{https://www.tpc.org/tpch/}}
}

@misc{cubepreagg,
  author = {{Cube Dev, Inc.}},
  title = {Using Pre-Aggregations},
  year = {2026},
  howpublished = {Cube documentation, \\href{https://docs.cube.dev/docs/pre-aggregations/using-pre-aggregations}{\\nolinkurl{docs.cube.dev/docs/pre-aggregations/using-pre-aggregations}}}
}

@misc{powerbiagg,
  author = {{Microsoft}},
  title = {User-Defined Aggregations in {Power BI}},
  year = {2026},
  howpublished = {Microsoft Learn, \\href{https://learn.microsoft.com/en-us/power-bi/transform-model/aggregations-advanced}{\\nolinkurl{learn.microsoft.com/en-us/power-bi/transform-model/aggregations-advanced}}}
}

@misc{snowflakerap,
  author = {{Snowflake Inc.}},
  title = {Understanding Row Access Policies},
  year = {2026},
  howpublished = {Snowflake documentation, \\href{https://docs.snowflake.com/en/user-guide/security-row-intro}{\\nolinkurl{docs.snowflake.com/en/user-guide/security-row-intro}}}
}
"""
open(os.path.join(HERE, "..", "references.bib"), "w").write("\n".join(out) + "\n" + extra)
json.dump(log, open(os.path.join(HERE, "bib_log.json"), "w"), indent=1)
print(len(out), "entries")
for l in log: print(l)
