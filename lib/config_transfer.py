# lib/config_transfer.py
"""
Export / import of settings as a JSON file:
  • a whole radio system (all its settings tabs + triggers + per-trigger notifiers), or
  • just triggers, to copy them into another system.

The table list is read from the database's foreign keys, so new settings tables are included
automatically. Call history (calls, tone hits, fire log) is never exported.
On import, ids are renumbered, the system gets a new API key, and columns the running version
doesn't know are skipped (so files from older / newer versions still import).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from lib.system_module import add_system, delete_system

module_logger = logging.getLogger("icad_dispatch.config_transfer")

FORMAT = "ecrxn_dispatch_export"
OLD_FORMATS = ("icad_dispatch_export",)   # files exported before the rename still import
VERSION = 1

# History, not settings
SKIP_TABLES = {"call_records", "call_tone_events", "call_transcripts", "call_transcript_segments", "call_vad_segments",
               "alert_trigger_last_fire", "tone_trigger_map", "trigger_fires", "users", "user_remember_tokens",
               "schema_migrations", "sqlite_sequence"}

# Left out unless "include passwords and tokens" is ticked
SECRET_COLUMNS = {
    "api_key", "smtp_password", "pushover_group_token", "pushover_app_token", "telegram_bot_token",
    "discord_webhook_url", "make_webhook_url", "make_api_key", "transcribe_api_key", "n8n_webhook_url",
    "jwt_passphrase", "openai_api_key", "google_maps_api_key", "sftp_password", "s3_access_key_id",
    "s3_secret_access_key", "facebook_page_token",
}
SECRET_JSON_KEYS = {"bot_token", "webhook_url", "api_key", "smtp_password", "jwt_passphrase", "page_token"}
# Uploaded files aren't in the export
FILE_COLUMNS = {"facebook_background"}
FILE_JSON_KEYS = {"background"}


class ImportError_(ValueError):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────
def _schema(db) -> Dict[str, Dict[str, Any]]:
    """{table: {cols, notnull, pk:[...], parent:(table, fk_col, parent_col) | None, refs:[(table, fk_col, parent_col)]}}
    The parent is the table's one ON DELETE CASCADE key (its owner); other keys (e.g. a trigger's group,
    ON DELETE SET NULL) are refs, renumbered on import when the row they point to came along, else cleared."""
    tables = [r["name"] for r in db.execute_query(
        "SELECT name FROM sqlite_master WHERE type='table'", fetch_mode="all")["result"]]
    out: Dict[str, Dict[str, Any]] = {}
    for t in tables:
        if t in SKIP_TABLES:
            continue
        info = db.execute_query(f"PRAGMA table_info({t})", fetch_mode="all")["result"]
        fks = db.execute_query(f"PRAGMA foreign_key_list({t})", fetch_mode="all")["result"]
        owners = [f for f in fks if str(f.get("on_delete") or "").upper() == "CASCADE"] if len(fks) > 1 else fks
        parent = (owners[0]["table"], owners[0]["from"], owners[0]["to"]) if len(owners) == 1 else None
        out[t] = {
            "cols": [c["name"] for c in info],
            "notnull": {c["name"] for c in info if c["notnull"]},
            "pk": [c["name"] for c in sorted(info, key=lambda c: c["pk"]) if c["pk"]],
            "parent": parent,
            "refs": [(f["table"], f["from"], f["to"]) for f in fks if parent and f["from"] != parent[1]],
        }
    return out


def _tree(schema, root: str) -> List[str]:
    """Tables under `root`, parents before children (root first); a table also comes after the tables
    its refs point to (so trigger groups are imported before the triggers in them)."""
    order, queue = [root], [root]
    while queue:
        parent = queue.pop(0)
        for t, meta in sorted(schema.items()):
            if meta["parent"] and meta["parent"][0] == parent and t not in order:
                order.append(t)
                queue.append(t)
    for t in list(order):
        for rtable, _c, _p in schema[t].get("refs") or []:
            if rtable in order and order.index(rtable) > order.index(t):
                order.remove(rtable)
                order.insert(order.index(t), rtable)
    return order


def _own_pk(meta) -> Optional[str]:
    """A single-column id this table numbers itself (renumbered on import), else None."""
    pk = meta["pk"]
    if len(pk) == 1 and (not meta["parent"] or pk[0] != meta["parent"][1]):
        return pk[0]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Export
# ─────────────────────────────────────────────────────────────────────────────
def _scrub(table: str, row: Dict[str, Any], secrets: bool) -> Dict[str, Any]:
    row = dict(row)
    for c in list(row):
        if c in FILE_COLUMNS or (not secrets and c in SECRET_COLUMNS):
            row[c] = None
    if table in ("alert_trigger_notifiers", "alert_trigger_group_notifiers") and row.get("config"):
        try:
            cfg = json.loads(row["config"])
            for k in list(cfg):
                if k in FILE_JSON_KEYS or (not secrets and (k in SECRET_JSON_KEYS or k in SECRET_COLUMNS)):
                    cfg[k] = ""
            row["config"] = json.dumps(cfg)
        except ValueError:
            pass
    return row


def _collect(db, schema, root: str, root_ids: List[int], secrets: bool) -> Dict[str, List[Dict[str, Any]]]:
    data: Dict[str, List[Dict[str, Any]]] = {}
    ids: Dict[str, List[Any]] = {}
    for t in _tree(schema, root):
        meta = schema[t]
        if t == root:
            col, wanted = meta["pk"][0], root_ids
        else:
            ptable, fk, pcol = meta["parent"]
            col, wanted = fk, [r[pcol] for r in data.get(ptable, [])]
        if not wanted:
            data[t] = []
            continue
        rows = db.execute_query(
            f"SELECT * FROM {t} WHERE {col} IN ({','.join('?' for _ in wanted)})", wanted, fetch_mode="all")["result"]
        data[t] = [_scrub(t, r, secrets) for r in rows or []]
    return data


def export_system(db, radio_system_id: int, *, secrets: bool = False, app_version: str = "") -> Dict[str, Any]:
    schema = _schema(db)
    data = _collect(db, schema, "radio_systems", [radio_system_id], secrets)
    if not data["radio_systems"]:
        raise ImportError_("System not found.")
    for r in data["radio_systems"]:
        r["api_key"] = None             # a new key is made on import
    return _envelope("system", data, secrets, app_version)


def export_triggers(db, radio_system_id: int, trigger_ids: Optional[List[int]] = None, *,
                    secrets: bool = False, app_version: str = "") -> Dict[str, Any]:
    schema = _schema(db)
    q = "SELECT alert_trigger_id FROM alert_triggers WHERE radio_system_id = ?"
    rows = db.execute_query(q, (radio_system_id,), fetch_mode="all")["result"] or []
    ids = [r["alert_trigger_id"] for r in rows]
    if trigger_ids:
        ids = [i for i in ids if i in set(trigger_ids)]
    data = _collect(db, schema, "alert_triggers", ids, secrets)
    return _envelope("triggers", data, secrets, app_version)


def _envelope(kind: str, data, secrets: bool, app_version: str) -> Dict[str, Any]:
    return {"format": FORMAT, "version": VERSION, "kind": kind, "app_version": app_version,
            "exported_at": int(time.time()), "includes_secrets": bool(secrets),
            "tables": {t: rows for t, rows in data.items() if rows}}


# ─────────────────────────────────────────────────────────────────────────────
# Import
# ─────────────────────────────────────────────────────────────────────────────
def read_export(raw: bytes) -> Dict[str, Any]:
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise ImportError_("That isn't an ECRXN Dispatch export file (couldn't read it as JSON).")
    if not isinstance(doc, dict) or doc.get("format") not in (FORMAT, *OLD_FORMATS):
        raise ImportError_("That isn't an ECRXN Dispatch export file.")
    if int(doc.get("version") or 0) > VERSION:
        raise ImportError_("That file comes from a newer ECRXN Dispatch - update this one first.")
    if doc.get("kind") not in ("system", "triggers") or not isinstance(doc.get("tables"), dict):
        raise ImportError_("The export file is incomplete.")
    return doc


def _insert_rows(db, schema, doc_tables, order: List[str], idmap: Dict[str, Dict[Any, Any]],
                 adopt: Dict[str, Dict[Any, Any]]) -> Dict[str, int]:
    """
    Insert exported rows below already-mapped parents. A row whose table already has a row for the new
    parent (a default settings row made with the new system) updates that row instead of adding a second.
    """
    counts: Dict[str, int] = {}
    for t in order:
        meta = schema.get(t)
        rows = doc_tables.get(t) or []
        if not meta or not rows or not meta["parent"]:
            continue
        ptable, fk, pcol = meta["parent"]
        own = _own_pk(meta)
        cols_ok = set(meta["cols"])
        idmap.setdefault(t, {})
        for r in rows:
            if not isinstance(r, dict):
                continue
            new_parent = idmap.get(ptable, {}).get(r.get(fk))
            if new_parent is None:
                continue
            vals = {k: v for k, v in r.items() if k in cols_ok and k != own}
            vals[fk] = new_parent
            for rtable, rcol, _rpcol in meta.get("refs") or []:
                if vals.get(rcol) is not None:     # e.g. a trigger's group: the new group's id, if it came along
                    vals[rcol] = idmap.get(rtable, {}).get(vals[rcol])
            for k in meta["notnull"]:
                if k in vals and vals[k] is None:
                    vals.pop(k)         # let the column default apply
            existing = adopt.get(t, {}).get(new_parent)
            if existing is not None:
                sets = {k: v for k, v in vals.items() if k != fk and k not in meta["pk"]}
                if sets:
                    _ok(db.execute_commit(
                        f"UPDATE {t} SET {', '.join(f'{k} = ?' for k in sets)} WHERE {own or fk} = ?",
                        (*sets.values(), existing if own else new_parent)))
                if own:
                    idmap[t][r.get(own)] = existing
                adopt[t].pop(new_parent, None)      # a second exported row for this parent is inserted
            else:
                res = _ok(db.execute_commit(
                    f"INSERT INTO {t} ({', '.join(vals)}) VALUES ({', '.join('?' for _ in vals)})",
                    tuple(vals.values()), return_row_id=True))
                if own:
                    idmap[t][r.get(own)] = res["result"]
            counts[t] = counts.get(t, 0) + 1
    return counts


def _ok(res: Dict[str, Any]) -> Dict[str, Any]:
    if not res.get("success"):
        raise ImportError_(f"Couldn't import: {res.get('message')}")
    return res


def import_system(db, doc: Dict[str, Any], *, system_decimal: Optional[int] = None,
                  system_name: Optional[str] = None) -> Dict[str, Any]:
    """Create a new system from an export. Returns {radio_system_id, triggers}."""
    if doc["kind"] != "system":
        raise ImportError_("This file holds triggers, not a whole system - import it from the Triggers page.")
    src = (doc["tables"].get("radio_systems") or [None])[0]
    if not isinstance(src, dict):
        raise ImportError_("The export file has no system in it.")
    created = add_system(db, {
        "system_decimal": system_decimal or src.get("system_decimal"),
        "system_name": (system_name or src.get("system_name") or "").strip(),
        "stream_url": src.get("stream_url"),
    })
    if not created["success"]:
        msg = created["message"]
        raise ImportError_({"System decimal already exists": "A system with that System ID already exists - "
                                                             "enter a different System ID.",
                            "System name already exists": "A system with that name already exists - "
                                                          "enter a different name."}.get(msg, msg))
    new_id = created["result"]
    schema = _schema(db)
    order = _tree(schema, "radio_systems")
    # The default rows add_system just made: adopt them rather than adding duplicates
    adopt: Dict[str, Dict[Any, Any]] = {}
    for t in order[1:]:
        meta = schema[t]
        if meta["parent"] and meta["parent"][0] == "radio_systems":
            own = _own_pk(meta)
            row = db.execute_query(f"SELECT {own or meta['parent'][1]} AS id FROM {t} WHERE {meta['parent'][1]} = ? "
                                   f"LIMIT 1", (new_id,), fetch_mode="one")["result"]
            if row and t != "alert_triggers":
                adopt[t] = {new_id: row["id"]}
    try:
        db.begin()
        idmap = {"radio_systems": {src.get("radio_system_id"): new_id}}
        # default child rows (seeded Discord / Make fields) of adopted rows are replaced by the imported ones
        for t, meta in schema.items():
            if meta["parent"] and meta["parent"][0] in adopt and meta["parent"][0] in doc["tables"]:
                parent_ids = list(adopt[meta["parent"][0]].values())
                _ok(db.execute_commit(f"DELETE FROM {t} WHERE {meta['parent'][1]} IN "
                                      f"({','.join('?' for _ in parent_ids)})", parent_ids))
        counts = _insert_rows(db, schema, doc["tables"], order, idmap, adopt)
        db.commit()
    except Exception:
        db.rollback()
        delete_system(db, radio_system_id=new_id)
        raise
    return {"radio_system_id": new_id, "triggers": counts.get("alert_triggers", 0)}


def import_triggers(db, doc: Dict[str, Any], radio_system_id: int) -> Dict[str, Any]:
    """Add the triggers from an export (a triggers file or a whole-system file) to an existing system."""
    schema = _schema(db)
    rows = doc["tables"].get("alert_triggers") or []
    if not rows:
        raise ImportError_("The file has no triggers in it.")
    order = _tree(schema, "alert_triggers")
    # every exported trigger hangs off the target system
    idmap = {"radio_systems": {r.get("radio_system_id"): radio_system_id for r in rows}}
    order = ["alert_triggers"] + order[1:]
    try:
        db.begin()
        counts = _insert_rows(db, schema, doc["tables"], order, idmap, {})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"triggers": counts.get("alert_triggers", 0), "trigger_ids": list(idmap.get("alert_triggers", {}).values())}
