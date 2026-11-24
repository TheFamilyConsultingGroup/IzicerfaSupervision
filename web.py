import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from flask import Flask, abort, g, jsonify, make_response, redirect, render_template, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024
ORIGIN = os.environ["JOURNAL_ORIGIN"].rstrip("/")
OWNER = os.environ["OWNER_EMAIL"].casefold()
FEED_KEY = os.environ["FEED_KEY"]
if len(FEED_KEY) < 40 or not ORIGIN.startswith("https://"):
    raise RuntimeError("Configuration incomplète")
DIR = Path(os.environ.get("DATA_DIR", "/data"))
DIR.mkdir(parents=True, exist_ok=True)
FIELDS = ("id","received","site","event","donation","subscription","status","worker","error","email",
          "amount","currency","source_created","source_accounting","source_date","initial_donation")
COOKIE = "__Host-journal"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DIR / "journal.sqlite", timeout=12)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close(_error):
    if "db" in g:
        g.db.close()


with app.app_context():
    conn = db()
    conn.executescript("""
      PRAGMA journal_mode=WAL;
      CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, received TEXT NOT NULL, site TEXT NOT NULL,
        event TEXT, donation TEXT, subscription TEXT, status TEXT, worker TEXT, error TEXT, email TEXT,
        amount TEXT, currency TEXT, source_created TEXT, source_accounting TEXT, source_date TEXT, initial_donation TEXT);
      CREATE INDEX IF NOT EXISTS by_time ON events(received);
      CREATE TABLE IF NOT EXISTS state(name TEXT PRIMARY KEY, value TEXT);
      CREATE TABLE IF NOT EXISTS links(hash TEXT PRIMARY KEY, owner TEXT, expiry INTEGER);
      CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, owner TEXT, expiry INTEGER);
      CREATE TABLE IF NOT EXISTS mail_requests(at INTEGER);
    """)


def save_state(name, value):
    db().execute("INSERT OR REPLACE INTO state VALUES (?,?)", (name, value))


def state(name):
    row = db().execute("SELECT value FROM state WHERE name=?", (name,)).fetchone()
    return row[0] if row else None


@app.before_request
def protect_changes():
    if request.method == "POST" and not request.path.startswith("/internal/"):
        if request.headers.get("Origin") != ORIGIN:
            abort(403)


@app.after_request
def headers(resp):
    resp.headers.update({"Cache-Control":"no-store", "Referrer-Policy":"no-referrer",
                         "X-Content-Type-Options":"nosniff", "X-Frame-Options":"DENY",
                         "Strict-Transport-Security":"max-age=31536000",
                         "Content-Security-Policy":"default-src 'none'; style-src 'self'; script-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
                         "X-Robots-Tag":"noindex,nofollow"})
    return resp


@app.get("/health")
def health():
    db().execute("SELECT 1 FROM state LIMIT 1")
    return jsonify(ok=True)


def require_feed():
    if not hmac.compare_digest(request.headers.get("Authorization","").encode(), ("Bearer " + FEED_KEY).encode()):
        abort(401)


@app.get("/internal/checkpoint")
def checkpoint():
    require_feed()
    return jsonify(through=state("through"), full_day=state("full_day"))


@app.post("/internal/import")
def ingest():
    require_feed()
    rows = request.get_json()["rows"]
    if not isinstance(rows, list) or len(rows) > 150:
        abort(400)
    for row in rows:
        if (not isinstance(row, dict) or set(row) != set(FIELDS) or row.get("site") not in {"AIU", "ENIO"}
                or not row.get("id") or not row.get("received")
                or any(v is not None and (not isinstance(v, str) or len(v)>1024) for v in row.values())):
            abort(400)
    db().executemany("INSERT OR REPLACE INTO events VALUES (" + ",".join("?" for _ in FIELDS) + ")",
                     [tuple(row[field] for field in FIELDS) for row in rows])
    db().commit()
    return jsonify(received=len(rows))


@app.post("/internal/complete")
def complete():
    require_feed()
    data = request.get_json()
    through = datetime.fromisoformat(data["through"]).astimezone(UTC)
    if not state("through") or through.isoformat() >= state("through"):
        save_state("through", through.isoformat())
        if data["full"]:
            save_state("full_day", through.date().isoformat())
    db().execute("DELETE FROM events WHERE received < ?", ((datetime.now(UTC)-timedelta(days=30)).isoformat(),))
    for table in ("sessions","links"):
        db().execute("DELETE FROM " + table + " WHERE expiry <= ?", (int(time.time()),))
    db().commit()
    return jsonify(ok=True)


def active_session():
    return db().execute("SELECT 1 FROM sessions WHERE hash=? AND owner=? AND expiry>?",
                        (digest(request.cookies.get(COOKIE,"")),OWNER,time.time())).fetchone()


@app.get("/")
def home():
    if not active_session():
        return render_template("login.html", mode="login", mail=bool(os.getenv("RESEND_API_KEY")))
    return redirect("/journal")


@app.get("/connexion")
def enter():
    return render_template("login.html", mode="confirm")


def send_link(url):
    req = Request("https://api.resend.com/emails", data=json.dumps({
        "from": os.environ["MAIL_FROM"], "to": [OWNER], "subject": "Ton accès au journal IZICERFA",
        "text": "Ouvre ce lien puis confirme la connexion. Le lien est personnel et valable 15 minutes.\n\n" + url
    }).encode(), headers={"Content-Type":"application/json","Authorization":"Bearer "+os.environ["RESEND_API_KEY"],
                          "User-Agent":"IzicerfaSupervision/1.0"})
    with urlopen(req, timeout=10) as res:
        if res.status not in (200,201,202):
            raise ValueError("Envoi indisponible")


@app.post("/demander")
def issue():
    if not os.getenv("RESEND_API_KEY") or not os.getenv("MAIL_FROM"):
        return render_template("login.html", mode="unavailable"), 503
    now = int(time.time())
    if request.form.get("email","").strip().casefold() == OWNER:
        db().execute("BEGIN IMMEDIATE")
        db().execute("DELETE FROM mail_requests WHERE at < ?", (now-3600,))
        times = db().execute("SELECT COUNT(*), MAX(at) FROM mail_requests").fetchone()
        if times[0] < 5 and (times[1] is None or times[1] <= now-60):
            token = secrets.token_urlsafe(32)
            db().execute("INSERT INTO links VALUES(?,?,?)", (digest(token),OWNER,now+900))
            db().execute("INSERT INTO mail_requests VALUES(?)", (now,))
            db().commit()
            try:
                send_link(ORIGIN + "/connexion#" + token)
            except Exception:
                db().execute("DELETE FROM links WHERE hash=?", (digest(token),))
                db().commit()
                print("Echec du transport email", flush=True)
                return render_template("login.html", mode="unavailable"),503
        else:
            db().commit()
    return render_template("login.html", mode="sent")


@app.post("/ouvrir")
def redeem():
    token = request.form.get("token","")[:128]
    key = digest(token)
    now = int(time.time())
    db().execute("BEGIN IMMEDIATE")
    # Une invitation initiale peut être distribuée directement à la boîte autorisée.
    if (hmac.compare_digest(key,os.getenv("INVITE_HASH","")) and int(os.getenv("INVITE_UNTIL","0"))>now
            and state("used_invite") != key):
        save_state("used_invite", key)
    elif db().execute("DELETE FROM links WHERE hash=? AND owner=? AND expiry>?",(key,OWNER,now)).rowcount != 1:
        db().rollback()
        return render_template("login.html", mode="expired"),403
    session = secrets.token_urlsafe(32)
    db().execute("INSERT INTO sessions VALUES(?,?,?)",(digest(session),OWNER,now+8*3600))
    db().commit()
    res = make_response(redirect("/journal",303))
    res.set_cookie(COOKIE, session, secure=True, httponly=True, samesite="Strict", max_age=8*3600, path="/")
    return res


@app.post("/sortir")
def logout():
    db().execute("DELETE FROM sessions WHERE hash=?",(digest(request.cookies.get(COOKIE,"")),))
    db().commit()
    res = make_response(redirect("/",303))
    res.delete_cookie(COOKIE, secure=True, httponly=True, samesite="Strict",path="/")
    return res


@app.template_filter("paris")
def paris(value):
    return datetime.fromisoformat(value).astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y %H:%M:%S") if value else "—"


@app.route("/journal", methods=["GET","POST"])
def journal():
    if not active_session():
        return redirect("/")
    params = request.form
    site = params.get("site","")
    status = params.get("status","")
    q = params.get("q","").strip()[:180]
    page = max(1,min(params.get("page",1,type=int),1000000))
    clauses, values = [], []
    if site in ("AIU","ENIO"):
        clauses.append("site=?")
        values.append(site)
    if status:
        clauses.append("status=?")
        values.append(status[:64])
    if q:
        clauses.append("(instr(lower(coalesce(email,'')),lower(?))>0 OR lower(site||'-'||donation)=lower(?) OR donation=? OR subscription=?)")
        values.extend([q]*4)
    where = (" WHERE "+" AND ".join(clauses)) if clauses else ""
    total = db().execute("SELECT count(*) FROM events"+where,values).fetchone()[0]
    rows = db().execute("SELECT * FROM events"+where+" ORDER BY received DESC,id DESC LIMIT 50 OFFSET ?",
                        (*values,(page-1)*50)).fetchall()
    statuses = [r[0] for r in db().execute("SELECT DISTINCT status FROM events WHERE status IS NOT NULL ORDER BY status")]
    last = state("through")
    late = not last or (datetime.now(UTC)-datetime.fromisoformat(last)).total_seconds()>420
    return render_template("journal.html", rows=rows, total=total, page=page, status=status, statuses=statuses,
                           site=site, q=q, last=last, late=late)
