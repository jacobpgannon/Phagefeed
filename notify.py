#!/usr/bin/env python3
"""PhageFeed email alerts.

Runs your original PhageFeed engine (server.py + config.py, unchanged) once, on a schedule
in GitHub Actions, and emails you the papers it has not seen before. The paper database is kept
between runs in the GitHub Actions cache.

Who gets the emails:
  BUTTONDOWN_API_KEY set     paper emails go to everyone subscribed through the website (Buttondown
                             handles confirmation and unsubscribe links)
  otherwise                  paper emails go to you through SMTP (below)

Settings come from environment variables (GitHub repository secrets):
  BUTTONDOWN_API_KEY         optional: send to website subscribers via Buttondown
  SMTP_USER, SMTP_PASSWORD   your sending account (e.g. Gmail + app password); required without Buttondown,
                             optional with it (then used only for the one-time "alerts are on" email to you)
  MAIL_TO                    where your own emails go (default: SMTP_USER)
  SMTP_HOST, SMTP_PORT       default smtp.gmail.com, 465
  ANTHROPIC_API_KEY          optional: Claude summaries in the email (else key sentences)
  APP_URL                    optional: link to your PhageFeed iPhone app, shown in the email
  ONLY_HIGHLIGHTS            optional: "yes" = only email papers mentioning Listeria/Nostoc/Clostridium
  DISABLED_TERMS             optional (GitHub *variable*): comma-separated term ids from terms.json to switch off,
                             e.g. "phage,jumbo" - copy it from the app's Search terms sheet
  TEST_EMAIL                 "true" = send the last TEST_DAYS (default 7) days of papers to you only;
                             subscribers get nothing and the workflow does not save this run's database
"""
import html
import os
import datetime as dt
import json
import re
import smtplib
import ssl
import sys
import urllib.error
import urllib.request
from email.message import EmailMessage

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("PHAGEFEED_HOME", os.path.join(os.getcwd(), ".phagefeed-data"))
sys.path.insert(0, HERE)
import server as S  # noqa: E402  (your original server.py)

C = S.C
# The iPhone app keeps the 60-day archive; alerts only need recent papers, which keeps each run short.
C.LOOKBACK_DAYS = int(os.environ.get("PUBMED_LOOKBACK_DAYS") or 14)
C.BIORXIV_LOOKBACK_DAYS = int(os.environ.get("BIORXIV_LOOKBACK_DAYS") or 7)
COLORS = {h["name"]: h["color"] for h in C.HIGHLIGHTS}


def env(k, default=""):
    return (os.environ.get(k) or default).strip()


def https(u):
    return u if isinstance(u, str) and u.startswith("https://") else ""


def have_smtp():
    return bool(env("SMTP_USER") and env("SMTP_PASSWORD"))


def buttondown_draft(subject, html_body):
    """Save an unsent draft in Buttondown (for previewing / 'Send test' there)."""
    req = urllib.request.Request(
        "https://api.buttondown.com/v1/emails", method="POST",
        data=json.dumps({"subject": subject, "body": html_body, "status": "draft"}).encode(),
        headers={"Authorization": "Token " + env("BUTTONDOWN_API_KEY"), "Content-Type": "application/json",
                 "User-Agent": S.UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print("saved as a draft in Buttondown (HTTP %d): open Emails -> Drafts there to preview it" % r.status)
    except urllib.error.HTTPError as e:
        sys.exit("Buttondown refused the draft (HTTP %d): %s" % (e.code, e.read().decode("utf-8", "replace")[:800]))


def send_to_subscribers(subject, html_body):
    """Create and send one Buttondown email to every confirmed subscriber.
    Sent once, without retries, so a slow reply can never cause a duplicate email."""
    req = urllib.request.Request(
        "https://api.buttondown.com/v1/emails", method="POST",
        data=json.dumps({"subject": subject, "body": html_body, "status": "about_to_send"}).encode(),
        headers={"Authorization": "Token " + env("BUTTONDOWN_API_KEY"), "Content-Type": "application/json",
                 "X-Buttondown-Live-Dangerously": "true", "User-Agent": S.UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print("sent to subscribers via Buttondown:", subject, "(HTTP %d)" % r.status)
    except urllib.error.HTTPError as e:
        sys.exit("Buttondown refused the email (HTTP %d): %s" % (e.code, e.read().decode("utf-8", "replace")[:800]))


def send(subject, text_body, html_body):
    user, pw = env("SMTP_USER"), env("SMTP_PASSWORD")
    if not user or not pw:
        sys.exit("No way to send email: set BUTTONDOWN_API_KEY, or SMTP_USER and SMTP_PASSWORD - see the README.")
    host, port = env("SMTP_HOST", "smtp.gmail.com"), int(env("SMTP_PORT", "465"))
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, "PhageFeed <%s>" % user, env("MAIL_TO", user)
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=60) as s:
            s.login(user, pw)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as s:
            s.starttls(context=ctx)
            s.login(user, pw)
            s.send_message(msg)
    print("emailed:", subject)


def paper_html(p):
    href = https(p.get("pdf_url")) or https(p.get("article_url"))
    hl = p["highlights"]
    authors = p["first_author"] + (" … " + p["last_author"] if p["last_author"] else "")
    tags = "".join('<span style="background:%s;color:#fff;border-radius:4px;padding:0 6px;font-size:11px;'
                   'font-weight:600;margin-left:6px">%s%s</span>'
                   % (COLORS.get(h, "#555"), html.escape(h), " (full text)" if p["highlight_where"].get(h) == "full text" else "")
                   for h in hl)
    bar = COLORS.get(hl[0], "#d0d0d0") if hl else "#d0d0d0"
    kind = {"ai": "AI", "extract": "extract"}.get(p.get("summary_kind"), "")
    links = []
    if https(p.get("pdf_url")):
        links.append('<a href="%s" style="color:#0a66c2">PDF</a>' % html.escape(p["pdf_url"]))
    if https(p.get("article_url")):
        links.append('<a href="%s" style="color:#0a66c2">%s</a>'
                     % (html.escape(p["article_url"]), "bioRxiv page" if p["source"] == "biorxiv" else "Journal page"))
    return (
        '<div style="border-left:4px solid %s;padding:6px 0 6px 12px;margin:0 0 18px">'
        '<a href="%s" style="font-size:16px;font-weight:600;color:#1d1d1f;text-decoration:none;line-height:1.3">%s</a>'
        '<div style="font-size:12.5px;color:#6e6e73;margin-top:3px"><b style="color:%s">%s</b>, %s, %s%s</div>'
        '<div style="font-size:14px;margin-top:6px;color:#1d1d1f">%s%s</div>'
        '<div style="font-size:13px;margin-top:6px">%s</div></div>'
        % (bar, html.escape(href), html.escape(p["title"]),
           "#b31b1b" if p["source"] == "biorxiv" else "#1d1d1f", html.escape(p["journal"]), html.escape(p["date"] or ""),
           html.escape(authors), tags,
           ('<span style="font-size:10px;color:#6e6e73;border:1px solid #ddd;border-radius:3px;padding:0 4px;margin-right:5px">%s</span>' % kind) if kind else "",
           html.escape(p.get("summary") or ""), " &nbsp; ".join(links)))


def paper_text(p):
    out = "%s\n%s, %s, %s%s\n" % (p["title"], p["journal"], p["date"], p["first_author"],
                                  (" … " + p["last_author"]) if p["last_author"] else "")
    if p["highlights"]:
        out += "Mentions: %s\n" % ", ".join(p["highlights"])
    if p.get("summary"):
        out += p["summary"] + "\n"
    return out + (https(p.get("pdf_url")) or https(p.get("article_url"))) + "\n"


def wrap(inner):
    app = https(env("APP_URL"))
    foot = ('<p style="font-size:12px;color:#6e6e73">All papers: <a href="%s">open PhageFeed</a></p>' % html.escape(app)) if app else ""
    return ('<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:640px">%s%s</div>' % (inner, foot))


def load_terms():
    """Toggleable search terms shared with the iPhone app (terms.json next to this file)."""
    path = os.path.join(HERE, "terms.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        terms = json.load(f).get("terms", [])
    out = []
    for t in terms:
        try:
            out.append((t["id"], re.compile(t["pattern"], re.I)))
        except (KeyError, re.error) as e:
            print("skipping search term", t.get("id"), e)
    return out


def apply_terms(rows):
    """Drop papers whose every matching term is switched off (papers matching no listed term stay)."""
    off = {x.strip().lower() for x in env("DISABLED_TERMS").split(",") if x.strip()}
    if not off:
        return rows
    terms = load_terms()
    unknown = off - {i for i, _ in terms}
    if unknown:
        print("DISABLED_TERMS has ids not in terms.json (ignored):", ", ".join(sorted(unknown)))
    keep = []
    for r in rows:
        text = r["title"] + " " + (r.get("abstract") or "")
        hits = [i for i, rx in terms if rx.search(text)]
        if not hits or any(i not in off for i in hits):
            keep.append(r)
    print("search terms off: %s -> %d of %d papers kept" % (", ".join(sorted(off)), len(keep), len(rows)))
    return keep


def load_rows(sql, args=()):
    with S.db() as con:
        rows = [dict(r) for r in con.execute(sql, args)]
    for r in rows:
        r["highlights"] = json.loads(r["highlights"] or "[]")
        r["highlight_where"] = json.loads(r["highlight_where"] or "{}")
    return rows


def test_email():
    """Fetch as usual, then send the recent papers to you only."""
    days = int(env("TEST_DAYS", "7"))
    S.init_db()
    S.refresh()
    with S._sum_lock:
        pass
    S.summarize_pending()
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = load_rows("SELECT * FROM papers WHERE date >= ? ORDER BY (highlights != '[]') DESC, date DESC LIMIT 40", (since,))
    rows = apply_terms(rows)
    if env("ONLY_HIGHLIGHTS").lower() in ("1", "yes", "true"):
        rows = [r for r in rows if r["highlights"]]
    subject = "PhageFeed test: %d paper%s from the last %d days" % (len(rows), "" if len(rows) == 1 else "s", days)
    note = ('<p style="font-size:12px;color:#6e6e73">Test email: this is what the daily update looks like. '
            'Only you received it.</p>')
    body = wrap(note + ("".join(paper_html(r) for r in rows) or "<p>No papers in this period.</p>"))
    if have_smtp():
        send(subject, "\n".join(paper_text(r) for r in rows) or "No papers in this period.", body)
    elif env("BUTTONDOWN_API_KEY"):
        buttondown_draft(subject, body)
    else:
        sys.exit("No way to send email: set SMTP_USER and SMTP_PASSWORD (or BUTTONDOWN_API_KEY) - see the README.")
    print("test done, errors:", S.STATUS.get("last_error"))


def main():
    if env("TEST_EMAIL").lower() == "true":
        return test_email()
    subscribers = bool(env("BUTTONDOWN_API_KEY"))
    if not subscribers and not have_smtp():
        sys.exit("No way to send email: set BUTTONDOWN_API_KEY, or SMTP_USER and SMTP_PASSWORD - see the README.")
    S.init_db()
    with S.db() as con:
        known = {r[0] for r in con.execute("SELECT id FROM papers")}
    before = len(known)

    S.refresh()                       # PubMed + bioRxiv + OA links + summaries + full-text highlights
    with S._sum_lock:                 # let any summary thread still running finish ...
        pass
    S.summarize_pending()             # ... then summarize anything left
    errors = S.STATUS.get("last_error")

    rows = load_rows("SELECT * FROM papers ORDER BY (highlights != '[]') DESC, date DESC")
    total = len(rows)
    rows = [r for r in rows if r["id"] not in known]

    if before == 0:
        # First run (or the stored database expired): record what exists now, don't email all of it.
        if total and have_smtp():           # only to you, never to subscribers
            send("PhageFeed email alerts are on",
                 "PhageFeed is now tracking %d recent papers. You'll get an email when new ones appear." % total,
                 wrap("<p>PhageFeed is now tracking <b>%d</b> recent papers. You'll get an email like this "
                      "whenever new ones appear.</p>" % total))
        print("baseline run: %d papers recorded, errors=%s" % (total, errors))
    else:
        rows = apply_terms(rows)
        if env("ONLY_HIGHLIGHTS").lower() in ("1", "yes", "true"):
            rows = [r for r in rows if r["highlights"]]
        if rows:
            n = len(rows)
            hls = sorted({h for r in rows for h in r["highlights"]})
            subject = "PhageFeed daily: %d new phage paper%s" % (n, "" if n == 1 else "s") + (" (%s)" % ", ".join(hls) if hls else "")
            body = wrap("".join(paper_html(r) for r in rows))
            if subscribers:
                send_to_subscribers(subject, body)
            else:
                send(subject, "\n".join(paper_text(r) for r in rows), body)
        else:
            print("no new papers")

    if errors:
        print("errors:", errors)
        # both sources down: fail the run so GitHub emails you about it
        if "PubMed" in errors and "bioRxiv" in errors:
            sys.exit(1)


if __name__ == "__main__":
    main()
