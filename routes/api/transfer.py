# routes/api/transfer.py
"""
Export / import:
  GET  /api/systems/<sys>/export                     whole system (settings + triggers) as JSON
                                                       (everything, tokens included; ?secrets=0 leaves them out)
  POST /api/systems/import                             new system from that JSON
  GET  /api/systems/<sys>/triggers/export?ids=1,2      triggers only, as JSON
  POST /api/systems/<sys>/triggers/import              add triggers from a JSON export or a tones CSV
  GET  /api/systems/<sys>/tones.csv                    every trigger's tones as a spreadsheet
Routes are attached to the /api/systems blueprint.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import time

from flask import request, jsonify, abort, current_app, Response

from lib.alert_trigger_module import add_trigger, get_triggers_full
from lib.config_transfer import ImportError_, export_system, export_triggers, import_system, import_triggers, read_export
from lib.system_module import get_systems
from routes.api.systems import (
    api_systems, _apply_system_defaults_to_rule, _canonicalize_rule, _ensure_system_channel_rows,
    _ensure_trigger_child_rows, _fetch_system_tone_settings_row, _system_defaults_from_row,
)
from routes.decorators import login_required, csrf_protect

route_logger = logging.getLogger("icad_dispatch.transfer")

MAX_IMPORT_BYTES = 20 * 1024 * 1024
CSV_HEADERS = ["Trigger", "Talkgroup", "Enabled", "Match", "Type", "Tone A (Hz)", "Tone A length (s)",
               "Tone B (Hz)", "Tone B length (s)", "Tolerance (%)", "Other"]
TYPE_NAMES = {"two_tone_sets": "Two-tone", "long_tone_sets": "Long tone", "hi_low_sets": "Hi-low",
              "pulsed_sets": "Pulsed", "dtmf_sequences": "DTMF"}


def _system(db, radio_system_id: int) -> dict:
    res = get_systems(db, radio_system_id=radio_system_id)
    if not res.get("success") or not res.get("result"):
        abort(404, "System not found.")
    return res["result"][0]


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s or "").strip("_")[:40] or "system"


def _download(body: str, filename: str, mimetype: str) -> Response:
    resp = Response(body, mimetype=mimetype)
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _want_secrets() -> bool:
    """Exports are a full copy (tokens, passwords, webhook URLs) unless ?secrets=0 asks for a shareable one."""
    return str(request.args.get("secrets", "1")).lower() not in ("0", "false", "no", "off")


def _upload_bytes() -> tuple[bytes, str]:
    f = request.files.get("file")
    if not f or not f.filename:
        abort(400, "Choose a file to import.")
    raw = f.stream.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        abort(400, "That file is too big to be an export.")
    return raw, f.filename


# ──────────────────────────────────────────────────────────────────────
# Whole system
# ──────────────────────────────────────────────────────────────────────
@api_systems.route("/<int:radio_system_id>/export", methods=["GET"])
@login_required
def system_export(radio_system_id: int):
    db = current_app.config["db"]
    sys_row = _system(db, radio_system_id)
    doc = export_system(db, radio_system_id, secrets=_want_secrets(), app_version=current_app.config.get("VERSION", ""))
    name = f"ecrxn_{_slug(sys_row.get('system_name'))}_{time.strftime('%Y-%m-%d')}.json"
    return _download(json.dumps(doc, indent=1, default=str), name, "application/json")


@api_systems.route("/import", methods=["POST"])
@login_required
@csrf_protect
def system_import():
    db = current_app.config["db"]
    raw, _ = _upload_bytes()
    try:
        doc = read_export(raw)
        dec = request.form.get("system_decimal", "").strip()
        res = import_system(db, doc, system_decimal=int(dec) if dec.isdigit() else None,
                            system_name=request.form.get("system_name", "").strip() or None)
    except ImportError_ as e:
        return jsonify(success=False, message=str(e), result=[]), 400
    except Exception as e:
        route_logger.exception("System import failed")
        return jsonify(success=False, message=f"Import failed: {e}", result=[]), 400
    _ensure_system_channel_rows(db, res["radio_system_id"])
    for t in db.execute_query("SELECT alert_trigger_id FROM alert_triggers WHERE radio_system_id = ?",
                              (res["radio_system_id"],), fetch_mode="all")["result"] or []:
        _ensure_trigger_child_rows(db, t["alert_trigger_id"])
    note = "" if doc.get("includes_secrets") else " Passwords, tokens and webhook URLs weren't in the file - enter them again."
    return jsonify(success=True, result=res,
                   message=f"System imported with {res['triggers']} trigger(s). It has a new API key.{note}"), 201


# ──────────────────────────────────────────────────────────────────────
# Triggers
# ──────────────────────────────────────────────────────────────────────
@api_systems.route("/<int:radio_system_id>/triggers/export", methods=["GET"])
@login_required
def triggers_export(radio_system_id: int):
    db = current_app.config["db"]
    sys_row = _system(db, radio_system_id)
    ids = [int(x) for x in re.findall(r"\d+", request.args.get("ids", ""))] or None
    doc = export_triggers(db, radio_system_id, ids, secrets=_want_secrets(), app_version=current_app.config.get("VERSION", ""))
    name = f"ecrxn_{_slug(sys_row.get('system_name'))}_triggers_{time.strftime('%Y-%m-%d')}.json"
    return _download(json.dumps(doc, indent=1, default=str), name, "application/json")


@api_systems.route("/<int:radio_system_id>/triggers/import", methods=["POST"])
@login_required
@csrf_protect
def triggers_import(radio_system_id: int):
    db = current_app.config["db"]
    _system(db, radio_system_id)
    raw, filename = _upload_bytes()
    _ensure_system_channel_rows(db, radio_system_id)
    try:
        if filename.lower().endswith((".csv", ".txt")):
            res = _import_tones_csv(db, radio_system_id, raw)
        else:
            res = import_triggers(db, read_export(raw), radio_system_id)
            res["skipped"] = []
    except ImportError_ as e:
        return jsonify(success=False, message=str(e), result=[]), 400
    except Exception as e:
        route_logger.exception("Trigger import failed")
        return jsonify(success=False, message=f"Import failed: {e}", result=[]), 400
    for tid in res.get("trigger_ids") or []:
        _ensure_trigger_child_rows(db, tid)
    msg = f"Imported {res['triggers']} trigger(s)."
    if res["skipped"]:
        msg += f" Skipped {len(res['skipped'])}: " + "; ".join(res["skipped"][:5]) + ("…" if len(res["skipped"]) > 5 else "")
    return jsonify(success=True, message=msg, result=res), 200


# ──────────────────────────────────────────────────────────────────────
# Tones spreadsheet (CSV): one row per tone rule
# ──────────────────────────────────────────────────────────────────────
def _num(v):
    if v in (None, ""):
        return ""
    f = float(v)
    return int(f) if f.is_integer() else round(f, 3)


def _rule_cells(tk: str, r: dict) -> list:
    a = al = b = bl = other = ""
    if tk == "two_tone_sets":
        a, al, b, bl = r.get("freq_a_hz"), r.get("min_len_a_s"), r.get("freq_b_hz"), r.get("min_len_b_s")
    elif tk == "long_tone_sets":
        a, al = r.get("freq_hz"), r.get("min_len_s")
    elif tk == "hi_low_sets":
        a, b = r.get("hi_freq_a_hz"), r.get("hi_freq_b_hz")
        other = "; ".join(f"{k}={_num(r.get(k))}" for k in ("min_alternations", "interval_s") if r.get(k) not in (None, ""))
    elif tk == "pulsed_sets":
        a = r.get("center_hz")
        other = "; ".join(f"{k}={_num(r.get(k))}" for k in
                          ("min_cycles", "min_on_ms", "max_on_ms", "min_off_ms", "max_off_ms") if r.get(k) not in (None, ""))
    elif tk == "dtmf_sequences":
        other = r.get("sequence") or ""
    return [TYPE_NAMES[tk], _num(a), _num(al), _num(b), _num(bl), _num(r.get("tol_pct")), other]


@api_systems.route("/<int:radio_system_id>/tones.csv", methods=["GET"])
@login_required
def tones_csv(radio_system_id: int):
    db = current_app.config["db"]
    sys_row = _system(db, radio_system_id)
    res = get_triggers_full(db, radio_system_id=radio_system_id)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CSV_HEADERS)
    for t in sorted(res.get("result") or [], key=lambda t: (t.get("alert_trigger_name") or "").lower()):
        base = [t.get("alert_trigger_name") or "", t.get("alert_trigger_talkgroup") or "",
                "Yes" if int(t.get("alert_trigger_enabled") or 0) else "No", t.get("alert_trigger_type") or "OR"]
        rules = [(tk, r) for tk in TYPE_NAMES for r in (t.get(tk) or [])]
        if not rules:
            w.writerow(base + [""] * 7)
        for tk, r in rules:
            w.writerow(base + _rule_cells(tk, r))
    name = f"ecrxn_{_slug(sys_row.get('system_name'))}_tones_{time.strftime('%Y-%m-%d')}.csv"
    # BOM so Excel opens it as UTF-8
    return _download("﻿" + out.getvalue(), name, "text/csv")


def _pick_type(raw: str, a, b) -> str | None:
    t = re.sub(r"[^a-z]", "", (raw or "").lower())
    if not t:
        return "two_tone_sets" if a and b else "long_tone_sets" if a else None
    if t in ("twotone", "quickcall", "qc", "qcii", "2tone", "tone"):
        return "two_tone_sets"
    if t.startswith("long") or t in ("single", "singletone"):
        return "long_tone_sets"
    if t.startswith("hilo") or t.startswith("hilow"):
        return "hi_low_sets"
    if t.startswith("puls"):
        return "pulsed_sets"
    if t.startswith("dtmf"):
        return "dtmf_sequences"
    return None


def _import_tones_csv(db, radio_system_id: int, raw: bytes) -> dict:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ImportError_("The spreadsheet is empty.")
    head = [re.sub(r"[^a-z]", "", h.lower()) for h in rows[0]]

    def col(*names):
        for n in names:
            if n in head:
                return head.index(n)
        return None
    ci = {"name": col("trigger", "name", "triggername", "agency", "station"), "tg": col("talkgroup", "tg"),
          "enabled": col("enabled"), "match": col("match", "mode"), "type": col("type", "tonetype"),
          "a": col("toneahz", "tonea", "a", "freqa"), "al": col("tonealengths", "tonealength", "alength", "alen"),
          "b": col("tonebhz", "toneb", "b", "freqb"), "bl": col("toneblengths", "toneblength", "blength", "blen"),
          "tol": col("tolerance", "tolerancepct", "tol"), "other": col("other", "dtmf", "sequence")}
    if ci["name"] is None:
        raise ImportError_("The spreadsheet needs a 'Trigger' column with the trigger names.")

    def cell(row, key):
        i = ci[key]
        return row[i].strip() if i is not None and i < len(row) else ""

    existing = {(t.get("alert_trigger_name") or "").strip().lower()
                for t in (get_triggers_full(db, radio_system_id=radio_system_id).get("result") or [])}
    sys_defs = _system_defaults_from_row(_fetch_system_tone_settings_row(db, radio_system_id) or {})
    groups: dict[str, dict] = {}
    skipped: list[str] = []
    for n, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        name = cell(row, "name")
        if not name:
            skipped.append(f"row {n} has no trigger name")
            continue
        if name.lower() in existing:
            if name not in [s.split(" (")[0] for s in skipped]:
                skipped.append(f"{name} (already exists)")
            continue
        g = groups.setdefault(name, {"alert_trigger_name": name, "alert_trigger_enabled": 1, "rules": {}})
        if cell(row, "tg").isdigit():
            g["alert_trigger_talkgroup"] = int(cell(row, "tg"))
        if cell(row, "enabled"):
            g["alert_trigger_enabled"] = 0 if cell(row, "enabled").lower() in ("no", "n", "0", "false", "off") else 1
        if cell(row, "match").upper() in ("AND", "OR"):
            g["alert_trigger_type"] = cell(row, "match").upper()
        a, b = cell(row, "a"), cell(row, "b")
        tk = _pick_type(cell(row, "type"), a, b)
        other = cell(row, "other")
        if not tk:
            if cell(row, "type") or a:
                skipped.append(f"row {n}: unknown tone type '{cell(row, 'type')}'")
            continue
        try:
            if tk == "two_tone_sets":
                rule = {"freq_a_hz": a, "min_len_a_s": cell(row, "al"), "freq_b_hz": b, "min_len_b_s": cell(row, "bl")}
                if not (a and b):
                    raise ValueError("two-tone needs Tone A and Tone B")
            elif tk == "long_tone_sets":
                rule = {"freq_hz": a, "min_len_s": cell(row, "al")}
                if not a:
                    raise ValueError("long tone needs Tone A")
            elif tk == "dtmf_sequences":
                rule = {"sequence": other}
                if not other:
                    raise ValueError("DTMF needs the digits in the Other column")
            elif tk == "hi_low_sets":
                rule = {"hi_freq_a_hz": a, "hi_freq_b_hz": b, **_kv(other)}
                if not (a and b):
                    raise ValueError("hi-low needs Tone A and Tone B")
            else:
                rule = {"center_hz": a, **_kv(other)}
                if not a:
                    raise ValueError("pulsed needs Tone A")
            if cell(row, "tol"):
                rule["tol_pct"] = cell(row, "tol")
            rule = {k: v for k, v in rule.items() if v not in ("", None)}
            rule = _apply_system_defaults_to_rule(tk, _canonicalize_rule(tk, rule), sys_defs)
            for k, v in rule.items():
                if k not in ("sequence",) and v is not None and not isinstance(v, (int, float)):
                    raise ValueError(f"'{v}' isn't a number")
        except (ValueError, TypeError) as e:
            skipped.append(f"row {n}: {e}")
            continue
        g["rules"].setdefault(tk, []).append(rule)

    created = []
    for name, g in groups.items():
        rules = g.pop("rules")
        if not rules:
            skipped.append(f"{name} (no usable tones)")
            continue
        payload = {**g, "radio_system_id": radio_system_id, **rules}
        payload.setdefault("alert_trigger_type", "OR")
        res = add_trigger(db, payload)
        if res.get("success"):
            created.append(res["result"])
        else:
            skipped.append(f"{name}: {res.get('message')}")
    return {"triggers": len(created), "trigger_ids": created, "skipped": skipped}


def _kv(text: str) -> dict:
    """'min_cycles=6; min_on_ms=100' -> dict"""
    out = {}
    for part in re.split(r"[;,]", text or ""):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out
