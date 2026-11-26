#!/usr/bin/env python3
"""PhageFeed - local service that collects new bacteriophage / bacterial-immunity
papers from PubMed (selected journals) and bioRxiv, summarizes them, and serves a
small web UI at http://127.0.0.1:<PORT>.

Standard library only (Python >= 3.8). Data lives in
~/Library/Application Support/PhageFeed (override with PHAGEFEED_HOME).
"""
import datetime as dt
import json
import os
import re
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402

HOME = os.environ.get("PHAGEFEED_HOME") or os.path.expanduser("~/Library/Application Support/PhageFeed")
os.makedirs(HOME, exist_ok=True)
DB_PATH = os.path.join(HOME, "papers.db")
SETTINGS_PATH = os.path.join(HOME, "settings.json")
STATIC = os.path.join(HERE, "static")
UA = "PhageFeed/1.0 (personal literature monitor)"

INCLUDE_RE = [re.compile(p, re.I) for p in C.INCLUDE_PATTERNS]
DISPLAY_RE = [re.compile(p, re.I) for p in C.DISPLAY_PATTERNS]
BIOLOGY_RE = [re.compile(p, re.I) for p in C.BIOLOGY_PATTERNS]
EXCL_TITLE_RE = [re.compile(p, re.I) for p in C.EXCLUDE_TITLE_PATTERNS]
TOOL_RE = [re.compile(p, re.I) for p in getattr(C, "TOOL_PATTERNS", [])]
HL_RE = [(h["name"], re.compile(h["pattern"])) for h in C.HIGHLIGHTS]  # case-sensitive genus names


def log(*a):
    print(dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


# ===================================================================== HTTP
def http(url, data=None, headers=None, timeout=60, method=None, retries=3):
    """GET/POST with retries (exponential backoff on timeouts / 5xx / 429)."""
    for attempt in range(retries):
        try:
            return _http_once(url, data, headers, timeout, method)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if attempt == retries - 1:
                raise
        time.sleep(5 * 2 ** attempt)


def _http_once(url, data=None, headers=None, timeout=60, method=None):
    """GET/POST returning bytes. Falls back to /usr/bin/curl when Python's SSL
    store is missing certificates (common with python.org installers)."""
    h = {"User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), ssl.SSLError) and os.path.exists("/usr/bin/curl"):
            cmd = ["/usr/bin/curl", "-sSfL", "--max-time", str(timeout), url]
            for k, v in h.items():
                cmd += ["-H", "%s: %s" % (k, v)]
            if data is not None:
                cmd += ["--data-binary", "@-"]
            return subprocess.run(cmd, input=data, capture_output=True, check=True).stdout
        raise


def http_json(url, **kw):
    return json.loads(http(url, **kw).decode("utf-8"))


# ===================================================================== DB
_db_lock = threading.Lock()


def db():
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with _db_lock, db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS papers(
            id TEXT PRIMARY KEY, source TEXT, title TEXT, journal TEXT, journal_abbr TEXT,
            first_author TEXT, last_author TEXT, n_authors INTEGER, date TEXT, added_at TEXT,
            abstract TEXT, doi TEXT, pmid TEXT, pmcid TEXT, article_url TEXT, pdf_url TEXT,
            is_oa INTEGER DEFAULT 0, highlights TEXT DEFAULT '[]', highlight_where TEXT DEFAULT '{}',
            fulltext_checked INTEGER DEFAULT 0, summary TEXT, summary_kind TEXT, category TEXT);
        CREATE TABLE IF NOT EXISTS state(k TEXT PRIMARY KEY, v TEXT);
        CREATE INDEX IF NOT EXISTS idx_date ON papers(date DESC);
        """)


def get_state(k, default=None):
    with db() as con:
        r = con.execute("SELECT v FROM state WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def set_state(k, v):
    with _db_lock, db() as con:
        con.execute("INSERT OR REPLACE INTO state(k,v) VALUES(?,?)", (k, str(v)))


def load_settings():
    s = dict(C.DEFAULT_SETTINGS)
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH) as f:
                s.update(json.load(f))
        except Exception:
            pass
    if not s.get("anthropic_api_key") and os.environ.get("ANTHROPIC_API_KEY"):
        s["anthropic_api_key"] = os.environ["ANTHROPIC_API_KEY"]
    return s


def save_settings(new):
    s = load_settings()
    for k in C.DEFAULT_SETTINGS:
        if k in new:
            s[k] = new[k]
    with open(SETTINGS_PATH, "w") as f:
        json.dump(s, f, indent=2)
    os.chmod(SETTINGS_PATH, 0o600)
    return s


# ===================================================================== text helpers
def any_match(res, text):
    return any(r.search(text) for r in res)


def strip_tools(text):
    for r in TOOL_RE:
        text = r.sub(" ", text)
    return text


def is_display_only(text):
    return any_match(DISPLAY_RE, text) and not any_match(BIOLOGY_RE, text)


def excluded_title(title):
    t = (title or "").strip()
    return any(r.search(t) for r in EXCL_TITLE_RE)


def find_highlights(text):
    return [name for name, r in HL_RE if r.search(text or "")]


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


# ===================================================================== PubMed
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"


def pubmed_term():
    jq = " OR ".join('"%s"[ta]' % j for j in C.JOURNALS)
    return "(%s) AND (%s)" % (C.PUBMED_TOPIC, jq)


def fetch_pubmed():
    params = dict(db="pubmed", term=pubmed_term(), reldate=C.LOOKBACK_DAYS,
                  datetype="edat", retmax=500, retmode="json", tool="phagefeed")
    r = http_json(EUTILS + "esearch.fcgi", data=urllib.parse.urlencode(params).encode())
    ids = r["esearchresult"]["idlist"]
    with db() as con:
        have = {row[0] for row in con.execute("SELECT pmid FROM papers WHERE pmid IS NOT NULL")}
    rejected = set(json.loads(get_state("pubmed_rejected", "[]")))
    new = [i for i in ids if i not in have and i not in rejected]
    log("PubMed: %d hits, %d new" % (len(ids), len(new)))
    out = []
    for k in range(0, len(new), 100):
        chunk = new[k:k + 100]
        xml = http(EUTILS + "efetch.fcgi", data=urllib.parse.urlencode(
            dict(db="pubmed", id=",".join(chunk), retmode="xml", tool="phagefeed")).encode())
        root = ET.fromstring(xml)
        kept = set()
        for art in root.findall("PubmedArticle"):
            p = parse_pubmed_article(art)
            if p:
                out.append(p)
                kept.add(p["pmid"])
        rejected |= set(chunk) - kept
        time.sleep(0.4)
    set_state("pubmed_rejected", json.dumps(sorted(rejected & set(ids))))
    return out


def _author_name(a):
    if a is None:
        return ""
    coll = a.findtext("CollectiveName")
    if coll:
        return coll
    last = a.findtext("LastName") or ""
    ini = a.findtext("Initials") or (a.findtext("ForeName") or "")[:1]
    return ("%s %s" % (last, ini)).strip()


def parse_pubmed_article(art):
    mc = art.find("MedlineCitation")
    pmid = mc.findtext("PMID")
    a = mc.find("Article")
    title = clean("".join(a.find("ArticleTitle").itertext())) if a.find("ArticleTitle") is not None else ""
    ptypes = [clean(x.text) for x in a.findall("PublicationTypeList/PublicationType")]
    if excluded_title(title) or any(t in ("Published Erratum", "Retraction Notice", "Expression of Concern")
                                    for t in ptypes):
        return None
    parts = []
    for ab in a.findall("Abstract/AbstractText"):
        lab = ab.get("Label")
        txt = clean("".join(ab.itertext()))
        parts.append(("%s: %s" % (lab, txt)) if lab and lab.upper() not in ("UNLABELLED",) else txt)
    abstract = " ".join(parts)
    if is_display_only(title + " " + abstract):
        return None
    abbr = mc.findtext("MedlineJournalInfo/MedlineTA") or a.findtext("Journal/ISOAbbreviation") or ""
    journal = C.JOURNALS.get(abbr, a.findtext("Journal/Title") or abbr)
    authors = a.findall("AuthorList/Author")
    doi = pmcid = None
    for aid in art.findall("PubmedData/ArticleIdList/ArticleId"):
        if aid.get("IdType") == "doi":
            doi = aid.text
        elif aid.get("IdType") == "pmc":
            pmcid = aid.text
    if not doi:
        for el in a.findall("ELocationID"):
            if el.get("EIdType") == "doi":
                doi = el.text
    date = None
    for d in art.findall("PubmedData/History/PubMedPubDate"):
        if d.get("PubStatus") in ("entrez", "pubmed") and d.findtext("Year"):
            date = "%04d-%02d-%02d" % (int(d.findtext("Year")), int(d.findtext("Month") or 1), int(d.findtext("Day") or 1))
            if d.get("PubStatus") == "entrez":
                break
    return dict(id="pmid:" + pmid, source="pubmed", title=title, journal=journal, journal_abbr=abbr,
                first_author=_author_name(authors[0]) if authors else "",
                last_author=_author_name(authors[-1]) if len(authors) > 1 else "",
                n_authors=len(authors), date=date or dt.date.today().isoformat(), abstract=abstract,
                doi=doi, pmid=pmid, pmcid=pmcid,
                article_url=("https://doi.org/" + doi) if doi else "https://pubmed.ncbi.nlm.nih.gov/%s/" % pmid,
                pdf_url=None, is_oa=0, category=None)


# ===================================================================== bioRxiv
def _biorxiv_record(r):
    title, abstract = clean(r.get("title")), clean(r.get("abstract"))
    text = title + " " + abstract
    if not any_match(INCLUDE_RE, strip_tools(text)) or is_display_only(text) or excluded_title(title):
        return None
    au = [x.strip() for x in (r.get("authors") or "").split(";") if x.strip()]
    def fmt(name):  # "Cress, B. F." -> "Cress BF"
        last, _, first = name.partition(",")
        ini = re.sub(r"[^A-Za-z\-]", "", first.title() if first.isupper() else first)
        ini = "".join(c for c in ini if c.isupper() or c == "-")
        return ("%s %s" % (last.strip(), ini)).strip()
    v = r.get("version", 1)
    return dict(id="biorxiv:" + r["doi"], source="biorxiv", title=title, journal="bioRxiv", journal_abbr="bioRxiv",
                first_author=fmt(au[0]) if au else "", last_author=fmt(au[-1]) if len(au) > 1 else "",
                n_authors=len(au), date=r.get("date"), abstract=abstract, doi=r["doi"], pmid=None, pmcid=None,
                article_url="https://www.biorxiv.org/content/%sv%s" % (r["doi"], v),
                pdf_url="https://www.biorxiv.org/content/%sv%s.full.pdf" % (r["doi"], v),
                is_oa=1, category=r.get("category"))


def fetch_biorxiv_day(day):
    """All preprints posted on one day -> list of matching records."""
    out, cursor, scanned = [], 0, 0
    while True:
        d = http_json("https://api.biorxiv.org/details/biorxiv/%s/%s/%d" % (day, day, cursor), timeout=90)
        msg = (d.get("messages") or [{}])[0]
        coll = d.get("collection") or []
        total = int(msg.get("total", 0) or 0)
        for r in coll:
            scanned += 1
            if not C.BIORXIV_NEW_VERSIONS and str(r.get("version")) != "1":
                continue
            rec = _biorxiv_record(r)
            if rec:
                out.append(rec)
        cursor += len(coll)
        if not coll or cursor >= total:
            break
        time.sleep(0.2)
    return out, scanned


def fetch_biorxiv():
    """Scan bioRxiv day by day, newest first. Completed days older than the
    rescan window are remembered, so a 60-day backfill is done once and resumes
    if interrupted; hourly refreshes only re-read the last few days."""
    today = dt.date.today()
    done = set(json.loads(get_state("biorxiv_days_done", "[]")))
    days = [today - dt.timedelta(days=i) for i in range(C.BIORXIV_LOOKBACK_DAYS + 1)]
    todo = [d for d in days if d.isoformat() not in done]
    n_new = scanned = 0
    failed = []
    k = max(1, C.BIORXIV_PARALLEL_DAYS)
    with ThreadPoolExecutor(max_workers=k) as ex:
        for i in range(0, len(todo), k):           # newest days first, k at a time
            batch = todo[i:i + k]
            STATUS["phase"] = "scanning bioRxiv %s (%d/%d days)" % (batch[0].isoformat(), i + len(batch), len(todo))
            futs = {day: ex.submit(fetch_biorxiv_day, day.isoformat()) for day in batch}
            for day, f in futs.items():
                try:
                    recs, n = f.result()
                except Exception as e:
                    failed.append(day.isoformat())
                    log("bioRxiv day %s failed (%s); will retry next refresh" % (day, e))
                    continue
                scanned += n
                if recs:
                    enrich_highlights_and_store(recs)
                    n_new += STATUS.get("_last_store", 0)
                if (today - day).days > C.BIORXIV_RESCAN_DAYS:
                    done.add(day.isoformat())
            set_state("biorxiv_days_done", json.dumps(sorted(d for d in done if d >= days[-1].isoformat())))
    log("bioRxiv: scanned %d preprints over %d days, %d new matches" % (scanned, len(todo), n_new))
    if failed:
        STATUS["_biorxiv_failed"] = failed
        if len(failed) == len(todo):
            raise RuntimeError("bioRxiv API unreachable")
    return n_new


# ===================================================================== open-access links
def enrich_oa(papers):
    """Fill pdf_url / pmcid for PubMed papers using Europe PMC (+ Unpaywall if an email is set)."""
    pm = [p for p in papers if p["source"] == "pubmed"]
    for k in range(0, len(pm), 50):
        chunk = pm[k:k + 50]
        q = "(" + " OR ".join("EXT_ID:%s" % p["pmid"] for p in chunk) + ") AND SRC:MED"
        try:
            d = http_json("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(
                dict(query=q, resultType="core", format="json", pageSize=100)))
        except Exception as e:
            log("Europe PMC lookup failed:", e)
            continue
        by = {r.get("pmid"): r for r in d.get("resultList", {}).get("result", [])}
        for p in chunk:
            r = by.get(p["pmid"])
            if not r:
                continue
            p["pmcid"] = p["pmcid"] or r.get("pmcid")
            oa = r.get("isOpenAccess") == "Y"
            pdf = None
            for u in r.get("fullTextUrlList", {}).get("fullTextUrl", []):
                if u.get("documentStyle") == "pdf" and u.get("availabilityCode") in ("OA", "F"):
                    pdf = u.get("url")
                    break
            if not pdf and p["pmcid"] and r.get("inPMC") == "Y" and oa:
                pdf = "https://pmc.ncbi.nlm.nih.gov/articles/%s/pdf/" % p["pmcid"]
            if pdf:
                p["pdf_url"], p["is_oa"] = pdf, 1
            elif oa:
                p["is_oa"] = 1
    # Publisher-pattern PDFs for fully open-access journals
    for p in pm:
        if p["pdf_url"] or not p.get("doi"):
            continue
        doi = p["doi"]
        if p["journal_abbr"] == "Nat Commun" and doi.lower().startswith("10.1038/"):
            p["pdf_url"], p["is_oa"] = "https://www.nature.com/articles/%s.pdf" % doi.split("/", 1)[1], 1
        elif p["journal_abbr"].startswith("PLoS "):
            slug = {"PLoS Biol": "plosbiology", "PLoS Pathog": "plospathogens", "PLoS Genet": "plosgenetics"}.get(p["journal_abbr"], "plosone")
            p["pdf_url"], p["is_oa"] = "https://journals.plos.org/%s/article/file?id=%s&type=printable" % (slug, doi), 1
    email = load_settings().get("unpaywall_email")
    if email:
        for p in pm:
            if p["pdf_url"] or not p.get("doi"):
                continue
            try:
                d = http_json("https://api.unpaywall.org/v2/%s?email=%s" % (urllib.parse.quote(p["doi"]), urllib.parse.quote(email)), timeout=20)
                loc = d.get("best_oa_location") or {}
                if loc.get("url_for_pdf"):
                    p["pdf_url"], p["is_oa"] = loc["url_for_pdf"], 1
            except Exception:
                pass


# ===================================================================== highlights in full text
def strip_refs(xml_text):
    return re.sub(r"<ref-list.*?</ref-list>", " ", xml_text, flags=re.S)


def fulltext_highlights_batch(pmcids):
    """Open-access full text from NCBI PMC (efetch, batched) -> {pmcid: [highlights]}.
    The reference list is removed so a cited title alone does not trigger a highlight.
    Articles without a <body> (embargoed / not in the OA subset) are omitted."""
    xml = http(EUTILS + "efetch.fcgi", data=urllib.parse.urlencode(
        dict(db="pmc", id=",".join(x.replace("PMC", "") for x in pmcids), retmode="xml", tool="phagefeed")).encode(),
        timeout=90).decode("utf-8", "replace")
    out = {}
    for art in re.findall(r"<article[ >].*?</article>", xml, flags=re.S):
        m = re.search(r'<article-id pub-id-type="(?:pmc|pmcid)">(?:PMC)?(\d+)</article-id>', art)
        if not m or "<body" not in art:
            continue
        text = re.sub(r"<[^>]+>", " ", strip_refs(art))
        out["PMC" + m.group(1)] = find_highlights(text)
    return out


# ===================================================================== summaries
def extractive_summary(title, abstract):
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z])", re.sub(r"^[A-Z ]+:\s*", "", abstract or ""))
    sents = [re.sub(r"^[A-Z][A-Za-z ]{2,20}:\s+", "", s) for s in sents if len(s) > 30]
    if not sents:
        return title
    key = [s for s in sents if re.search(r"\b(here|we (show|find|found|report|demonstrate|identify|reveal|describe|discover))", s, re.I)]
    first = key[0] if key else sents[0]
    rest = [s for s in sents if s != first]
    return " ".join([first] + ([rest[-1]] if rest else []))


def ai_summary(p, s):
    if not p.get("abstract"):
        return "No abstract available yet - open the paper for details.", "none"
    prompt = C.SUMMARY_PROMPT.format(title=p["title"], journal=p["journal"], abstract=p["abstract"][:6000])
    prov = s.get("provider")
    if prov == "anthropic" and s.get("anthropic_api_key"):
        body = json.dumps({"model": s.get("anthropic_model") or "claude-haiku-5-5", "max_tokens": 300,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        d = http_json("https://api.anthropic.com/v1/messages", data=body, timeout=60, headers={
            "x-api-key": s["anthropic_api_key"], "anthropic-version": "2023-06-01", "content-type": "application/json"})
        txt = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
        return clean(txt), "ai"
    if prov == "ollama":
        body = json.dumps({"model": s.get("ollama_model"), "prompt": prompt, "stream": False}).encode()
        d = http_json(s.get("ollama_url", "http://127.0.0.1:11434").rstrip("/") + "/api/generate", data=body,
                      timeout=180, headers={"content-type": "application/json"})
        return clean(d.get("response", "")), "ai"
    return extractive_summary(p["title"], p["abstract"]), "extract"


_sum_lock = threading.Lock()


def summarize_pending(limit=400):
    if not _sum_lock.acquire(blocking=False):
        return
    try:
        _summarize_pending(limit)
    finally:
        _sum_lock.release()


def _summarize_pending(limit):
    s = load_settings()
    with db() as con:
        want_ai = (s.get("provider") == "anthropic" and s.get("anthropic_api_key")) or s.get("provider") == "ollama"
        # (re)summarize missing ones, and upgrade extractive ones once an AI provider is configured
        q = "SELECT * FROM papers WHERE summary IS NULL" + (" OR summary_kind='extract'" if want_ai else "")
        rows = [dict(r) for r in con.execute(q + " ORDER BY date DESC LIMIT ?", (limit,))]
    if not rows:
        return

    def work(p):
        try:
            txt, kind = ai_summary(p, s)
        except Exception as e:
            log("summary failed for", p["id"], e)
            txt, kind = extractive_summary(p["title"], p["abstract"]), "extract"
        with _db_lock, db() as con:
            con.execute("UPDATE papers SET summary=?, summary_kind=? WHERE id=?", (txt, kind, p["id"]))

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work, rows))
    log("summarized %d papers" % len(rows))


# ===================================================================== refresh loop
STATUS = {"running": False, "last_refresh": None, "last_error": None, "last_new": 0, "phase": "idle",
          "next_refresh": None}
_refresh_lock = threading.Lock()


def store(papers):
    now = dt.datetime.now().isoformat(timespec="seconds")
    n = 0
    with _db_lock, db() as con:
        for p in papers:
            text = p["title"] + " " + (p["abstract"] or "")
            hl = find_highlights(text)
            where = {h: "abstract" for h in hl}
            cur = con.execute(
                "INSERT OR IGNORE INTO papers(id,source,title,journal,journal_abbr,first_author,last_author,n_authors,"
                "date,added_at,abstract,doi,pmid,pmcid,article_url,pdf_url,is_oa,highlights,highlight_where,category) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p["id"], p["source"], p["title"], p["journal"], p["journal_abbr"], p["first_author"], p["last_author"],
                 p["n_authors"], p["date"], now, p["abstract"], p["doi"], p["pmid"], p["pmcid"], p["article_url"],
                 p["pdf_url"], p["is_oa"], json.dumps(hl), json.dumps(where), p.get("category")))
            n += cur.rowcount
    return n


def enrich_highlights_and_store(recs):
    STATUS["_last_store"] = store(recs)
    threading.Thread(target=summarize_pending, daemon=True).start()


def scan_fulltext_highlights():
    """fulltext_checked: 1 = done, 0 = never tried, negative = failed attempts (gives up after 3)."""
    if not C.FULLTEXT_HIGHLIGHT_SCAN:
        return
    with db() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT id,pmcid,highlights,highlight_where,fulltext_checked FROM papers "
            "WHERE fulltext_checked<=0 AND fulltext_checked>-3 AND pmcid IS NOT NULL ORDER BY date DESC LIMIT 200")]
    for k in range(0, len(rows), 20):
        chunk = rows[k:k + 20]
        try:
            found = fulltext_highlights_batch([r["pmcid"] for r in chunk])
        except Exception as e:
            log("full-text batch failed:", e)
            found = {}
        with _db_lock, db() as con:
            for p in chunk:
                if p["pmcid"] not in found:
                    con.execute("UPDATE papers SET fulltext_checked=fulltext_checked-1 WHERE id=?", (p["id"],))
                    continue
                hl, where = json.loads(p["highlights"]), json.loads(p["highlight_where"])
                for h in found[p["pmcid"]]:
                    if h not in hl:
                        hl.append(h)
                        where[h] = "full text"
                con.execute("UPDATE papers SET highlights=?, highlight_where=?, fulltext_checked=1 WHERE id=?",
                            (json.dumps(hl), json.dumps(where), p["id"]))
        time.sleep(0.4)


def refresh():
    if not _refresh_lock.acquire(blocking=False):
        return False
    STATUS.update(running=True, last_error=None)
    errors, new_total = [], 0
    try:
        STATUS["phase"] = "fetching PubMed"
        try:
            papers = fetch_pubmed()
            STATUS["phase"] = "finding open-access PDFs"
            enrich_oa(papers)
            new_total += store(papers)
        except Exception as e:
            errors.append("PubMed: %s" % e)
            log(traceback.format_exc())
        # summaries in a side thread so they appear while bioRxiv is still scanning
        sum_thread = threading.Thread(target=summarize_pending, daemon=True)
        sum_thread.start()
        try:
            new_total += fetch_biorxiv()
        except Exception as e:
            errors.append("bioRxiv: %s" % e)
            log(traceback.format_exc())
        sum_thread.join()
        STATUS["phase"] = "writing summaries"
        summarize_pending()
        STATUS["phase"] = "scanning open-access full text"
        try:
            scan_fulltext_highlights()
        except Exception as e:
            errors.append("full-text scan: %s" % e)
        STATUS["last_new"] = new_total
        if new_total and load_settings().get("notify") and sys.platform == "darwin":
            notify("%d new phage paper%s" % (new_total, "" if new_total == 1 else "s"))
    finally:
        STATUS.update(running=False, phase="idle", last_refresh=dt.datetime.now().isoformat(timespec="seconds"),
                      last_error="; ".join(errors) or None)
        set_state("last_refresh", STATUS["last_refresh"])
        _refresh_lock.release()
    log("refresh done: %d new, errors=%s" % (new_total, errors))
    return True


def notify(msg):
    try:
        subprocess.run(["osascript", "-e", 'display notification "%s" with title "PhageFeed"' % msg], timeout=10)
    except Exception:
        pass


def scheduler():
    while True:
        refresh()
        nxt = time.time() + C.REFRESH_SECONDS
        STATUS["next_refresh"] = dt.datetime.fromtimestamp(nxt).isoformat(timespec="seconds")
        while time.time() < nxt:
            time.sleep(20)
            if STATUS.get("_kick"):
                STATUS["_kick"] = False
                break


# ===================================================================== web
def query_papers(qs):
    limit = int(qs.get("limit", [C.DEFAULT_PAGE_SIZE])[0])
    offset = int(qs.get("offset", [0])[0])
    where, args = [], []
    journals = [j for j in qs.get("journal", []) if j]
    if journals:
        where.append("journal IN (%s)" % ",".join("?" * len(journals)))
        args += journals
    src = qs.get("source", [""])[0]
    if src in ("pubmed", "biorxiv"):
        where.append("source=?")
        args.append(src)
    hls = [h for h in qs.get("highlight", []) if h]
    if hls:
        where.append("(" + " OR ".join("highlights LIKE ?" for _ in hls) + ")")
        args += ['%%"%s"%%' % h for h in hls]
    q = qs.get("q", [""])[0].strip()
    if q:
        where.append("(title LIKE ? OR abstract LIKE ? OR first_author LIKE ? OR last_author LIKE ?)")
        args += ["%" + q + "%"] * 4
    w = (" WHERE " + " AND ".join(where)) if where else ""
    with db() as con:
        total = con.execute("SELECT COUNT(*) FROM papers" + w, args).fetchone()[0]
        rows = [dict(r) for r in con.execute(
            "SELECT id,source,title,journal,first_author,last_author,n_authors,date,added_at,doi,article_url,pdf_url,"
            "is_oa,highlights,highlight_where,summary,summary_kind,category FROM papers" + w +
            " ORDER BY date DESC, added_at DESC LIMIT ? OFFSET ?", args + [limit, offset])]
        journals_all = [dict(r) for r in con.execute(
            "SELECT journal, COUNT(*) n FROM papers GROUP BY journal ORDER BY (journal='bioRxiv') DESC, n DESC")]
    for r in rows:
        r["highlights"] = json.loads(r["highlights"] or "[]")
        r["highlight_where"] = json.loads(r["highlight_where"] or "{}")
    return {"total": total, "papers": rows, "journals": journals_all,
            "highlight_defs": C.HIGHLIGHTS, "page_size": C.DEFAULT_PAGE_SIZE}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path == "/api/papers":
            return self._send(200, query_papers(qs))
        if u.path == "/api/status":
            st = {k: v for k, v in STATUS.items() if not k.startswith("_")}
            with db() as con:
                st["count"] = con.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
                st["pending_summaries"] = con.execute("SELECT COUNT(*) FROM papers WHERE summary IS NULL").fetchone()[0]
            return self._send(200, st)
        if u.path == "/api/settings":
            s = load_settings()
            k = s.get("anthropic_api_key") or ""
            s["anthropic_api_key"] = ("…" + k[-4:]) if k else ""
            return self._send(200, s)
        path = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
        fp = os.path.normpath(os.path.join(STATIC, path))
        if fp.startswith(STATIC) and os.path.isfile(fp):
            ctype = {"html": "text/html; charset=utf-8", "js": "text/javascript", "css": "text/css",
                     "png": "image/png", "svg": "image/svg+xml"}.get(fp.rsplit(".", 1)[-1], "application/octet-stream")
            with open(fp, "rb") as f:
                return self._send(200, f.read(), ctype)
        self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if u.path == "/api/refresh":
            if STATUS["running"]:
                return self._send(202, {"started": False, "msg": "already running"})
            threading.Thread(target=refresh, daemon=True).start()
            return self._send(202, {"started": True})
        if u.path == "/api/settings":
            if body.get("anthropic_api_key", "").startswith("…"):
                body.pop("anthropic_api_key")   # masked value echoed back - keep stored key
            save_settings(body)
            threading.Thread(target=summarize_pending, daemon=True).start()
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})


def main():
    init_db()
    STATUS["last_refresh"] = get_state("last_refresh")
    if "--no-refresh" not in sys.argv:
        threading.Thread(target=scheduler, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", C.PORT), Handler)
    log("PhageFeed serving on http://127.0.0.1:%d  (data: %s)" % (C.PORT, HOME))
    srv.serve_forever()


if __name__ == "__main__":
    main()
