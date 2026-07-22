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


def _normalized_url():
    """Render sometimes provides 'postgres://'; some psycopg2 builds/SQLAlchemy
    prefer 'postgresql://'. psycopg2 accepts both, but normalize to be safe."""
    u = DATABASE_URL
    if u.startswith("postgres://"):
        u = "postgresql://" + u[len("postgres://"):]
    return u


def status_detail():
    """Human-readable reason saving is on/off — surfaced in the status endpoint so
    a misconfiguration isn't a silent black box."""
    if not DATABASE_URL:
        return "No DATABASE_URL set — attach a Postgres instance in Render."
    if not _HAVE_DRIVER:
        return ("DATABASE_URL is set, but the psycopg2 driver isn't installed — "
                "the build may not have picked up requirements.txt (needs "
                "psycopg2-binary). Redeploy after confirming requirements.txt deployed.")
    # both present — try an actual connection so we surface real errors (bad host,
    # SSL, wrong creds, DB still spinning up, etc.)
    try:
        conn = psycopg2.connect(_normalized_url(), connect_timeout=6)
        conn.close()
        return "Connected to Postgres — saving enabled."
    except Exception as e:
        return f"DATABASE_URL and driver present, but connection failed: {e}"


def _conn():
    return psycopg2.connect(_normalized_url())


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
    # Share-token column for read-only review links (idempotent for existing DBs).
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("ALTER TABLE quotes ADD COLUMN IF NOT EXISTS share_token TEXT UNIQUE;")
        # Which tab owns the quote: 'seo' (default keeps legacy rows) or 'rep'.
        cur.execute("ALTER TABLE quotes ADD COLUMN IF NOT EXISTS tool TEXT NOT NULL DEFAULT 'seo';")
        conn.commit()


def get_or_create_share_token(quote_id):
    """Return the quote's share token, minting one on first request. The token
    is the whole credential — anyone with the link can VIEW (never edit), so
    it's long and random, and stable so a re-share doesn't kill the old link."""
    import secrets
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT share_token FROM quotes WHERE id=%s", (quote_id,))
        row = cur.fetchone()
        if not row:
            return None
        if row[0]:
            return row[0]
        token = secrets.token_urlsafe(18)
        cur.execute("UPDATE quotes SET share_token=%s WHERE id=%s", (token, quote_id))
        conn.commit()
        return token


def load_by_token(token):
    """Read-only fetch of a quote by its share token."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name, client, payload, updated_at, tool FROM quotes "
                    "WHERE share_token=%s", (token,))
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "name": row[1], "client": row[2],
                "payload": row[3], "updated_at": row[4].isoformat(),
                "tool": row[5] or "seo"}


def _tiers(payload):
    """Pull display prices for the saved-quotes list. SEO quotes: the three
    client tiers. Rep quotes: one-time -> base, monthly -> intermediate (the
    columns are reused rather than widening the schema)."""
    try:
        rt = payload.get("rep_totals")
        if rt:
            return rt.get("one_time"), rt.get("monthly"), None
        ct = payload.get("pricing", {}).get("client_tiers", {})
        return ct.get("base"), ct.get("intermediate"), ct.get("advanced")
    except Exception:
        return None, None, None


def save_quote(name, client, payload, tool="seo"):
    """Create a new saved quote. Returns its id."""
    b, i, a = _tiers(payload)
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO quotes (name, client, payload, base, intermediate, advanced, tool) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (name, client or "", json.dumps(payload), b, i, a, tool or "seo"))
        qid = cur.fetchone()[0]
        conn.commit()
        return qid


def _norm_for_diff(p):
    """Normalized copy of a quote payload for change detection only — never
    stored. Sorts row arrays into canonical order and drops transient flags."""
    try:
        q = json.loads(json.dumps(p))
    except Exception:
        return p
    if isinstance(q, dict):
        t = q.get("table")
        if isinstance(t, list):
            rows = []
            for r in t:
                if isinstance(r, dict):
                    r = {k: v for k, v in r.items() if k != "queued"}
                rows.append(r)
            try:
                rows.sort(key=lambda r: str(r.get("kw", "")) if isinstance(r, dict) else str(r))
            except Exception:
                pass
            q["table"] = rows
        paa = q.get("paa")
        if isinstance(paa, list):
            try:
                q["paa"] = sorted(paa, key=str)
            except Exception:
                pass
    return q


def update_quote(quote_id, payload, name=None, client=None):
    """Update an existing quote IN PLACE. Snapshots the prior version to history
    first — but ONLY when the content actually changed, so repeated auto-saves
    don't fill the history with identical entries.
    Returns (found, version_saved)."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT payload, base, intermediate, advanced FROM quotes WHERE id=%s",
                    (quote_id,))
        row = cur.fetchone()
        if not row:
            return False, False
        old_payload = row[0]
        # Compare normalized JSON so noise doesn't create phantom "changes":
        # key order, keyword-table row order (rank batches land in arrival
        # order), and transient row flags (queued) all differ between visually
        # identical states — an Update click with no real edit must not snapshot.
        try:
            changed = (json.dumps(_norm_for_diff(old_payload), sort_keys=True)
                       != json.dumps(_norm_for_diff(payload), sort_keys=True))
        except Exception:
            changed = True
        version_saved = False
        if changed:
            cur.execute(
                "INSERT INTO quote_versions (quote_id, payload, base, intermediate, advanced) "
                "VALUES (%s,%s,%s,%s,%s)",
                (quote_id, json.dumps(old_payload), row[1], row[2], row[3]))
            version_saved = True
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
        return True, version_saved


def delete_version(version_id):
    """Delete a single history snapshot."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM quote_versions WHERE id=%s", (version_id,))
        conn.commit()
        return True


def list_quotes(search="", tool="seo"):
    """List saved quotes for one tool (newest first), optionally filtered by
    name/client. Default 'seo' keeps the SEO drawer's behavior unchanged."""
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if search:
            like = f"%{search}%"
            cur.execute(
                "SELECT id, name, client, base, intermediate, advanced, created_at, updated_at "
                "FROM quotes WHERE tool=%s AND (name ILIKE %s OR client ILIKE %s) "
                "ORDER BY updated_at DESC", (tool or "seo", like, like))
        else:
            cur.execute(
                "SELECT id, name, client, base, intermediate, advanced, created_at, updated_at "
                "FROM quotes WHERE tool=%s ORDER BY updated_at DESC", (tool or "seo",))
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
        cur.execute("SELECT id, name, client, payload, created_at, updated_at, tool "
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
