import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

import psycopg2
from psycopg2.extras import RealDictCursor

ROLE = "izicerfa_journal_reader"
VIEW = "izicerfa_supervision.journal"


def connect():
    conn = psycopg2.connect(host=os.environ["PGHOST"], dbname=os.environ["PGDATABASE"],
                            port=os.getenv("PGPORT", "5432"), user=ROLE,
                            password=os.environ["READER_PASSWORD"], connect_timeout=7,
                            options="-c default_transaction_read_only=on -c statement_timeout=12000")
    return conn


def setup():
    dsn = os.environ["SETUP_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg2.connect(dsn, connect_timeout=8) as admin, admin.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '3s'")
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (ROLE,))
        if not cur.fetchone():
            cur.execute("CREATE ROLE izicerfa_journal_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %s", (os.environ["READER_PASSWORD"],))
        cur.execute("CREATE SCHEMA IF NOT EXISTS izicerfa_supervision")
        cur.execute(Path("view.sql").read_text())
        cur.execute("REVOKE ALL ON SCHEMA izicerfa_supervision FROM PUBLIC")
        cur.execute("REVOKE ALL ON izicerfa_supervision.journal FROM PUBLIC")
        cur.execute("GRANT USAGE ON SCHEMA izicerfa_supervision TO izicerfa_journal_reader")
        cur.execute("GRANT SELECT ON izicerfa_supervision.journal TO izicerfa_journal_reader")
        cur.execute("ALTER ROLE izicerfa_journal_reader SET default_transaction_read_only = on")
    with connect() as limited, limited.cursor() as cur:
        cur.execute("""SELECT has_table_privilege(current_user,%s,'SELECT'),
                       has_table_privilege(current_user,'public.evenements_webhook_recus','SELECT'),
                       has_table_privilege(current_user,'public.evenements_webhook_recus','INSERT,UPDATE,DELETE'),
                       has_table_privilege(current_user,%s,'INSERT,UPDATE,DELETE')""", (VIEW, VIEW))
        if cur.fetchone() != (True, False, False, False):
            raise RuntimeError("Droits de lecture inattendus")
        cur.execute("SELECT count(*) FROM izicerfa_supervision.journal")
        print("LECTURE_VERIFIEE", cur.fetchone()[0], flush=True)
        ref = os.getenv("CHECK_REFERENCE", "")
        if ref:
            site, donation = ref.split("-", 1)
            cur.execute("""SELECT source_created, source_date, source_accounting FROM izicerfa_supervision.journal
                           WHERE site=%s AND donation=%s AND status='publish' ORDER BY received DESC LIMIT 1""",
                        (site, donation))
            dates = cur.fetchone()
            if dates:
                print("DATES_SOURCE", json.dumps(list(dates), ensure_ascii=False), flush=True)



def push(path, data=None):
    origin = os.environ["JOURNAL_ORIGIN"]
    if not origin.startswith("https://"):
        raise ValueError("HTTPS requis")
    req = Request(origin + path, data=None if data is None else json.dumps(data).encode(),
                  headers={"Authorization": "Bearer " + os.environ["FEED_KEY"], "Content-Type": "application/json"})
    with urlopen(req, timeout=15) as response:
        return json.load(response)


def sync():
    state = push("/internal/checkpoint")
    now = datetime.now(UTC)
    floor = max(datetime(2026, 11, 24, 13, 30, tzinfo=UTC), now - timedelta(days=30))
    last = datetime.fromisoformat(state["through"]) if state["through"] else None
    full = not last or state.get("full_day") != now.date().isoformat()
    since = floor if full else max(floor, last - timedelta(minutes=10))
    count = 0
    with connect() as conn, conn.cursor(name="journal_rows", cursor_factory=RealDictCursor) as cur:
        cur.execute("""SELECT * FROM izicerfa_supervision.journal
                       WHERE received >= %s AND received <= %s AND
                         (changed >= %s OR worker <> 'TRAITE')
                       ORDER BY received, id""", (floor, now, since))
        while rows := cur.fetchmany(150):
            batch = []
            for row in rows:
                row.pop("changed")
                row["received"] = row["received"].astimezone(UTC).isoformat()
                batch.append(dict(row))
            push("/internal/import", {"rows": batch})
            count += len(batch)
    push("/internal/complete", {"through": now.isoformat(), "full": full})
    print("Lecture terminée", count, flush=True)


def run(mode):
    if mode == "setup":
        setup()
        return
    if os.getenv("SETUP_DATABASE_URL"):
        raise RuntimeError("Le relais doit démarrer sans identifiant d’administration")
    while True:
        try:
            sync()
        except Exception as error:
            print("Lecture interrompue", type(error).__name__, getattr(error, "code", "") or "", flush=True)
        time.sleep(120)
