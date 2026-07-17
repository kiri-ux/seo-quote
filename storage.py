"""
Persistence for saved SEO quotes, with version history.

Mirrors the Meta Forecasting Tool's approach: quotes are saved by name (+ optional
client), can be reloaded and edited, and every save snapshots the previous version
to history so the original quote — and every edit since — is always recoverable.

Degrades gracefully: if DATABASE_URL isn't set (no Postgres attached), enabled()
returns False and the app runs normally with saving disabled.
"""
import os, json, datetime

DATABASE_URL = os.environ.get("DATABASE_URL", "")

try:
    import psycopg2
    import psycopg2.extras
    _HAVE_DRIVER = True
except Exception:
    _HAVE_DRIVER = False


def enabled():
    """True only when a Postgres DB is attached and the driver is available."""
    return bool(DATABASE_URL) and _HAVE_DRIVER


def _conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    """Create tables on startup. No-op when saving isn't enabled."""
    if not enabled():
        return
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS quotes (
                id          SERIAL PRIMARY KEY,
                name        TEXT NOT NULL,
                client      TEXT DEFAULT '',
                payload     JSONB NOT NULL,
                base        INTEGER,
                intermediate INTEGER,
                advanced    INTEGER,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS quote_versions (
                id          SERIAL PRIMARY KEY,
                quote_id    INTEGER NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
                payload     JSONB NOT NULL,
                base        INTEGER,
                intermediate INTEGER,
                advanced    INTEGER,
                snapshot_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
        conn.commit()


def _tiers(payload):
    """Pull the 3 client-tier prices out of a saved quote for list display."""
    try:
        ct = payload.get("pricing", {}).get("client_tiers", {})
        return ct.get("base"), ct.get("intermediate"), ct.get("advanced")
    except Exception:
        return None, None, None


def save_quote(name, client, payload):
    """Create a new saved quote. Returns its id."""
    b, i, a = _tiers(payload)
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO quotes (name, client, payload, base, intermediate, advanced) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (name, client or "", json.dumps(payload), b, i, a))
        qid = cur.fetchone()[0]
        conn.commit()
        return qid


def update_quote(quote_id, payload, name=None, client=None):
    """Update an existing quote IN PLACE, snapshotting the prior version to history
    first so nothing is ever lost. Returns True if the quote existed."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT payload, base, intermediate, advanced FROM quotes WHERE id=%s",
                    (quote_id,))
        row = cur.fetchone()
        if not row:
            return False
        # snapshot the CURRENT (about-to-be-replaced) version to history
        cur.execute(
            "INSERT INTO quote_versions (quote_id, payload, base, intermediate, advanced) "
            "VALUES (%s,%s,%s,%s,%s)",
            (quote_id, json.dumps(row[0]), row[1], row[2], row[3]))
        # write the new version in place
        b, i, a = _tiers(payload)
        sets = ["payload=%s", "base=%s", "intermediate=%s", "advanced=%s", "updated_at=now()"]
        vals = [json.dumps(payload), b, i, a]
        if name is not None:
            sets.append("name=%s"); vals.append(name)
        if client is not None:
            sets.append("client=%s"); vals.append(client)
        vals.append(quote_id)
        cur.execute(f"UPDATE quotes SET {', '.join(sets)} WHERE id=%s", vals)
        conn.commit()
        return True


def list_quotes(search=""):
    """List saved quotes (newest first), optionally filtered by name/client."""
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if search:
            like = f"%{search}%"
            cur.execute(
                "SELECT id, name, client, base, intermediate, advanced, created_at, updated_at "
                "FROM quotes WHERE name ILIKE %s OR client ILIKE %s ORDER BY updated_at DESC",
                (like, like))
        else:
            cur.execute(
                "SELECT id, name, client, base, intermediate, advanced, created_at, updated_at "
                "FROM quotes ORDER BY updated_at DESC")
        out = []
        for r in cur.fetchall():
            d = dict(r)
            d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
            d["updated_at"] = d["updated_at"].isoformat() if d["updated_at"] else None
            out.append(d)
        return out


def load_quote(quote_id):
    """Load one quote's full payload + how many versions it has."""
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, name, client, payload, created_at, updated_at "
                    "FROM quotes WHERE id=%s", (quote_id,))
        r = cur.fetchone()
        if not r:
            return None
        d = dict(r)
        d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
        d["updated_at"] = d["updated_at"].isoformat() if d["updated_at"] else None
        cur.execute("SELECT COUNT(*) AS n FROM quote_versions WHERE quote_id=%s", (quote_id,))
        d["version_count"] = cur.fetchone()["n"]
        return d


def list_versions(quote_id):
    """List the history snapshots for a quote (oldest first = original first)."""
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, base, intermediate, advanced, snapshot_at "
            "FROM quote_versions WHERE quote_id=%s ORDER BY snapshot_at ASC", (quote_id,))
        out = []
        for r in cur.fetchall():
            d = dict(r)
            d["snapshot_at"] = d["snapshot_at"].isoformat() if d["snapshot_at"] else None
            out.append(d)
        return out


def load_version(version_id):
    """Load one historical snapshot's full payload."""
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, quote_id, payload, snapshot_at FROM quote_versions WHERE id=%s",
                    (version_id,))
        r = cur.fetchone()
        if not r:
            return None
        d = dict(r)
        d["snapshot_at"] = d["snapshot_at"].isoformat() if d["snapshot_at"] else None
        return d


def delete_quote(quote_id):
    """Delete a quote and its version history (cascade)."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM quotes WHERE id=%s", (quote_id,))
        conn.commit()
        return True
