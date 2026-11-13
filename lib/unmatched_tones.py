# lib/unmatched_tones.py
"""
"Tones without a trigger" for the dashboard: tones the detector heard that no trigger covers yet,
grouped so the same page tone heard ten times shows once (with a count).

This only reads what the detector already stored (call_tone_events); it doesn't change detection.
A tone counts as covered when it fired a trigger at the time, or when a trigger added since has a
rule within tolerance (and, if that trigger has a talkgroup, on the same talkgroup).
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

GROUP_TOL_PCT = 1.5          # tones this close are the same tone heard again
DEFAULT_TOL_PCT = 2.0        # when neither the rule nor the trigger sets a tolerance
MAX_EVENTS = 5000            # newest tone events looked at


def _close(a: Optional[float], b: Optional[float], pct: float) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(a, b) * pct / 100.0


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _rules(db, radio_system_id: int) -> List[Dict[str, Any]]:
    """Every tone rule of the system's triggers, flattened: {type, a, b, seq, tol, tg}."""
    trig = db.execute_query(
        "SELECT alert_trigger_id, alert_trigger_tone_tolerance, alert_trigger_talkgroup FROM alert_triggers "
        "WHERE radio_system_id = ?", (radio_system_id,), fetch_mode="all")
    meta = {r["alert_trigger_id"]: r for r in (trig.get("result") or [])} if trig.get("success") else {}
    if not meta:
        return []
    ids = ",".join(str(int(i)) for i in meta)
    out: List[Dict[str, Any]] = []

    def add(sql, build):
        res = db.execute_query(sql, (), fetch_mode="all")
        for r in (res.get("result") or []) if res.get("success") else []:
            m = meta.get(r["alert_trigger_id"]) or {}
            tol = _num(r.get("tol_pct")) or _num(m.get("alert_trigger_tone_tolerance")) or DEFAULT_TOL_PCT
            rule = build(r)
            rule.update(tol=max(tol, GROUP_TOL_PCT), tg=str(m.get("alert_trigger_talkgroup") or "").strip())
            out.append(rule)

    add(f"SELECT * FROM alert_trigger_two_tone_sets WHERE alert_trigger_id IN ({ids})",
        lambda r: {"type": "two_tone", "a": _num(r["freq_a_hz"]), "b": _num(r["freq_b_hz"])})
    add(f"SELECT * FROM alert_trigger_long_tone_sets WHERE alert_trigger_id IN ({ids})",
        lambda r: {"type": "long", "a": _num(r["freq_hz"]), "b": None})
    add(f"SELECT * FROM alert_trigger_hi_low_sets WHERE alert_trigger_id IN ({ids})",
        lambda r: {"type": "hi_low", "a": _num(r["hi_freq_a_hz"]), "b": _num(r["hi_freq_b_hz"])})
    add(f"SELECT * FROM alert_trigger_pulsed_sets WHERE alert_trigger_id IN ({ids})",
        lambda r: {"type": "pulsed", "a": _num(r["center_hz"]), "b": None})
    add(f"SELECT *, NULL AS tol_pct FROM alert_trigger_dtmf_sequences WHERE alert_trigger_id IN ({ids})",
        lambda r: {"type": "dtmf", "seq": str(r.get("sequence") or "").strip()})
    return out


def _covered(ev: Dict[str, Any], rules: List[Dict[str, Any]]) -> bool:
    for r in rules:
        if r["type"] != ev["type"] or (r["tg"] and r["tg"] != ev["talkgroup"]):
            continue
        if ev["type"] == "dtmf":
            if r["seq"] and ev["dtmf"] and r["seq"] == ev["dtmf"]:
                return True
        elif ev["type"] in ("two_tone", "hi_low"):
            if _close(r["a"], ev["a"], r["tol"]) and _close(r["b"], ev["b"], r["tol"]):
                return True
        elif _close(r["a"], ev["a"], r["tol"]):
            return True
    return False


def unmatched_tones(db, radio_system_id: int, days: int = 30) -> List[Dict[str, Any]]:
    since = int(time.time()) - max(1, int(days)) * 86400
    res = db.execute_query(
        """
        SELECT cte.tone_type, cte.freq_a, cte.freq_b, cte.length_a_s, cte.length_b_s, cte.start_s, cte.end_s,
               cte.json_payload, cte.matches_trigger, cr.call_id, cr.talkgroup, cr.start_epoch_s
        FROM   call_tone_events cte
        JOIN   call_records cr USING (call_id)
        WHERE  cr.radio_system_id = ? AND cr.start_epoch_s >= ? AND cte.tone_type != 'mdc'
        ORDER  BY cr.start_epoch_s DESC
        LIMIT  ?
        """,
        (int(radio_system_id), since, MAX_EVENTS), fetch_mode="all",
    )
    if not res.get("success"):
        raise RuntimeError(res.get("message") or "query failed")

    rules = _rules(db, radio_system_id)
    groups: List[Dict[str, Any]] = []
    for row in res.get("result") or []:
        if int(row.get("matches_trigger") or 0):
            continue
        try:
            jp = json.loads(row.get("json_payload") or "{}") or {}
        except ValueError:
            jp = {}
        det = jp.get("detected")
        a = _num(row.get("freq_a")) or _num(det[0] if isinstance(det, list) and det else det)
        b = _num(row.get("freq_b")) or _num(det[1] if isinstance(det, list) and len(det) > 1 else None)
        ev = {"type": row["tone_type"], "a": a, "b": b, "talkgroup": str(row.get("talkgroup") or "").strip(),
              "dtmf": str(jp.get("digit") or jp.get("digits") or jp.get("sequence") or "").strip()}
        if ev["type"] == "dtmf" and not ev["dtmf"]:
            continue
        if ev["type"] != "dtmf" and a is None:
            continue
        if _covered(ev, rules):
            continue

        g = next((g for g in groups if g["type"] == ev["type"] and (
            g["dtmf"] == ev["dtmf"] if ev["type"] == "dtmf"
            else _close(g["freq_a"], a, GROUP_TOL_PCT) and (b is None or _close(g["freq_b"], b, GROUP_TOL_PCT)))), None)
        if g is None:
            start, end = _num(row.get("start_s")) or 0.0, _num(row.get("end_s")) or 0.0
            g = {"type": ev["type"], "freq_a": a, "freq_b": b, "dtmf": ev["dtmf"], "count": 0, "talkgroups": [],
                 "call_ids": [],    # every call this tone was heard in (for Delete)
                 # newest example (rows come newest first) - used to build the trigger
                 "last_epoch": row["start_epoch_s"], "last_call_id": row["call_id"],
                 "a_len": _num(row.get("length_a_s")) or _num(jp.get("tone_a_length")),
                 "b_len": _num(row.get("length_b_s")) or _num(jp.get("tone_b_length")),
                 "len": round(end - start, 2) if end > start else None,
                 "alts": jp.get("alternations"), "cycles": jp.get("cycles"),
                 "on_ms": jp.get("on_ms"), "off_ms": jp.get("off_ms")}
            groups.append(g)
        g["count"] += 1
        if row["call_id"] not in g["call_ids"]:
            g["call_ids"].append(row["call_id"])
        if ev["talkgroup"] and ev["talkgroup"] not in g["talkgroups"] and len(g["talkgroups"]) < 5:
            g["talkgroups"].append(ev["talkgroup"])
    return groups
