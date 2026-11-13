/*********************************************************************
 *  ECRXN Dispatch Demo - a pretend server that lives in this browser tab.
 *
 *  The pages are the real dashboard; every request they make to /api/... or /auth/...
 *  is answered here from demo-data.js. Changes are kept in sessionStorage, so they
 *  last until the tab is closed, "Reset" is clicked, or an hour has passed.
 *  Nothing is sent anywhere: the pages' Content-Security-Policy only allows this site's own
 *  files, and webhooks, tokens or addresses typed in are only ever stored in this tab.
 *********************************************************************/
(function () {
    "use strict";
    const KEY = "ecrxnDemoState.v2";
    const MAX_AGE_S = 3600;                 // start over after an hour
    const clone = o => JSON.parse(JSON.stringify(o));
    const now = () => Math.floor(Date.now() / 1000);

    // ── state ────────────────────────────────────────────────────────
    function fresh() {
        const d = clone(window.DEMO_DATA);
        // keep the demo calls "recent"
        const newest = Math.max(...d.calls.result.map(c => c.start_epoch));
        const shift = now() - 1800 - newest;
        d.calls.result.forEach(c => { c.start_epoch += shift; });
        Object.values(d.call_details).forEach(x => {
            x.result.call.start_epoch += shift;
            (x.result.triggers || []).forEach(t => { t.fired_at_epoch_s += shift; });
        });
        d.triggers.forEach(t => { if (t.last_fired_at) t.last_fired_at += shift; });
        d.blankNotifiers = clone(Object.values(d.notifiers).find(n =>
            Object.values(n.channels).every(c => !c.enabled)) || Object.values(d.notifiers)[0]);
        (d.unmatched || []).forEach(g => { g.last_epoch += shift; });
        d.nextId = 1000;
        d.createdAt = now();
        return d;
    }
    let S;
    try { S = JSON.parse(sessionStorage.getItem(KEY)); } catch { S = null; }
    if (!S || !(now() - (S.createdAt || 0) < MAX_AGE_S)) S = fresh();
    // audio paths are relative to the demo folder; the dashboard expects full addresses
    const absAudio = u => (u && !/^https?:/.test(u) ? new URL(u, location.href).href : u);
    S.calls.result.forEach(c => { c.audio_url = absAudio(c.audio_url); });
    Object.values(S.call_details).forEach(x => { x.result.call.audio_url = absAudio(x.result.call.audio_url); });
    const save = () => { try { sessionStorage.setItem(KEY, JSON.stringify(S)); } catch { /* private mode: in memory only */ } };
    const nextId = () => ++S.nextId;
    window.demoReset = () => { try { sessionStorage.removeItem(KEY); } catch { } location.reload(); };

    // ── helpers ──────────────────────────────────────────────────────
    const ok = (result, message = "OK") => ({ status: 200, body: { success: true, message, result } });
    const fail = (message, status = 400) => ({ status, body: { success: false, message, result: [] } });
    const DEMO_SENT = "Demo: on a real server this sends a test now. Nothing was sent.";
    const sys = id => S.systems.find(s => +s.radio_system_id === +id);
    const trig = id => S.triggers.find(t => +t.alert_trigger_id === +id);
    const clean = b => { const o = { ...(b || {}) }; delete o._csrf_token; delete o.csrf_token; return o; };

    /** Merge form keys like "telegram_bot_token" / "smtp_hostname" into a settings object */
    function mergeSection(obj, section, body) {
        const prefix = section + "_";
        for (const [k, v] of Object.entries(clean(body))) {
            if (k === "radio_system_id" || k === "system_name") continue;
            if (k in obj) obj[k] = v;
            else if (k === prefix + "enabled" || k === "enabled") obj.enabled = +v ? 1 : 0;
            else if (k.startsWith(prefix) && k.slice(prefix.length) in obj) obj[k.slice(prefix.length)] = v;
            else obj[k.startsWith(prefix) ? k.slice(prefix.length) : k] = v;
        }
        return obj;
    }

    function listOps(list, idKey, body, id, method) {
        if (method === "DELETE") {
            const i = list.findIndex(x => +x[idKey] === +id);
            if (i >= 0) list.splice(i, 1);
            return ok([], "Deleted.");
        }
        const row = id ? list.find(x => +x[idKey] === +id) : null;
        const data = clean(body);
        if (row) Object.assign(row, data);
        else list.push({ ...data, [idKey]: nextId(), sort_order: list.length, field_enabled: data.field_enabled ?? 1, enabled: data.enabled ?? 1 });
        return ok(row || list[list.length - 1], "Saved.");
    }

    function tonesCsv(sid) {
        const q = v => /[",\n]/.test(String(v ?? "")) ? `"${String(v).replace(/"/g, '""')}"` : String(v ?? "");
        const rows = [["Trigger", "Talkgroup", "Enabled", "Match", "Type", "Tone A (Hz)", "Tone A length (s)",
                       "Tone B (Hz)", "Tone B length (s)", "Tolerance (%)", "Other"]];
        S.triggers.filter(t => +t.radio_system_id === +sid).forEach(t => {
            const base = [t.alert_trigger_name, t.alert_trigger_talkgroup ?? "", +t.alert_trigger_enabled ? "Yes" : "No", t.alert_trigger_type || "OR"];
            const r = [];
            (t.two_tone_sets || []).forEach(x => r.push(["Two-tone", x.freq_a_hz, x.min_len_a_s, x.freq_b_hz, x.min_len_b_s, x.tol_pct ?? "", ""]));
            (t.long_tone_sets || []).forEach(x => r.push(["Long tone", x.freq_hz, x.min_len_s, "", "", x.tol_pct ?? "", ""]));
            (t.dtmf_sequences || []).forEach(x => r.push(["DTMF", "", "", "", "", "", x.sequence]));
            (r.length ? r : [["", "", "", "", "", "", ""]]).forEach(x => rows.push([...base, ...x]));
        });
        return "﻿" + rows.map(r => r.map(q).join(",")).join("\r\n");
    }

    /** Same idea as the server: a tone drops off "Tones without a trigger" once a trigger covers it */
    function coveredByTrigger(g, sid) {
        const close = (a, b, pct) => a != null && b != null && Math.abs(a - b) <= Math.max(a, b) * pct / 100;
        return S.triggers.some(t => {
            if (+t.radio_system_id !== +sid) return false;
            const tg = String(t.alert_trigger_talkgroup ?? "").trim();
            if (tg && !g.talkgroups.includes(tg)) return false;
            const tol = Math.max(+t.alert_trigger_tone_tolerance || 2, 1.5);
            if (g.type === "two_tone") return (t.two_tone_sets || []).some(x => close(+x.freq_a_hz, g.freq_a, tol) && close(+x.freq_b_hz, g.freq_b, tol));
            if (g.type === "long") return (t.long_tone_sets || []).some(x => close(+x.freq_hz, g.freq_a, tol));
            if (g.type === "hi_low") return (t.hi_low_sets || []).some(x => close(+x.hi_freq_a_hz, g.freq_a, tol) && close(+x.hi_freq_b_hz, g.freq_b, tol));
            if (g.type === "pulsed") return (t.pulsed_sets || []).some(x => close(+x.center_hz, g.freq_a, tol));
            if (g.type === "dtmf") return (t.dtmf_sequences || []).some(x => x.sequence === g.dtmf);
            return false;
        });
    }

    function saveFile(name, text, type) {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([text], { type }));
        a.download = name;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    }

    // ── the pretend API ──────────────────────────────────────────────
    function handle(method, path, query, body) {
        let m;
        // auth
        if (path === "/auth/login") return ok({}, "Authenticated");
        if (path === "/auth/change_password") return ok({}, "Demo: the password wasn't really changed.");

        // tone finder (Dashboard)
        if ((m = path.match(/^\/api\/tone-finder\/calls\/?$/))) {
            const sid = query.get("radio_system_id");
            const rows = S.calls.result.filter(c => !sid || +(S.call_details[c.call_id]?.result.call.radio_system_id ?? sid) === +sid);
            return { status: 200, body: { ...S.calls, result: rows, total: rows.length } };
        }
        if (path === "/api/tone-finder/calls/bulk-delete") {
            const ids = (body.call_ids || []).map(Number);
            S.calls.result = S.calls.result.filter(c => !ids.includes(+c.call_id));
            ids.forEach(i => delete S.call_details[i]);
            // a tone without a trigger goes once none of its calls are left
            S.unmatched = (S.unmatched || []).filter(g => !(g.call_ids || []).every(id => ids.includes(+id)));
            return ok({ deleted_ids: ids, not_found_ids: [], file_errors: [] }, `${ids.length} call(s) deleted.`);
        }
        if ((m = path.match(/^\/api\/tone-finder\/calls\/(\d+)$/))) {
            if (method === "DELETE") {
                S.calls.result = S.calls.result.filter(c => +c.call_id !== +m[1]);
                delete S.call_details[m[1]];
                return ok({}, `Call ${m[1]} deleted.`);
            }
            return S.call_details[m[1]] ? { status: 200, body: S.call_details[m[1]] } : fail("call_id not found", 404);
        }
        if (path.startsWith("/api/trigger-calls")) return ok([]);
        if (path === "/api/tone-finder/unmatched") {
            const sid = query.get("radio_system_id"), since = now() - (+query.get("days") || 30) * 86400;
            return ok((S.unmatched || []).filter(g => g.last_epoch >= since && !coveredByTrigger(g, sid)));
        }

        // systems
        if (path === "/api/systems/import") return fail("Importing is turned off in the demo. On your own server this creates a system from an export file.");
        if (/^\/api\/systems\/?$/.test(path)) {
            if (method === "POST") {
                if (S.systems.some(s => +s.system_decimal === +body.system_decimal)) return fail("System decimal already exists");
                const s = clone(S.systems[0]);
                const id = nextId();
                Object.assign(s, { radio_system_id: id, system_decimal: +body.system_decimal, system_name: body.system_name,
                                   stream_url: body.stream_url || null, api_key: crypto.randomUUID?.() || String(Math.random()) });
                ["telegram", "discord", "make", "pushover", "email", "n8n", "facebook", "transcribe", "address_extraction",
                 "incident_classification"].forEach(k => { if (s[k]) s[k].enabled = 0; });
                S.systems.push(s);
                return { status: 201, body: { success: true, message: `New system "${s.system_name}" added.`, result: id } };
            }
            const id = query.get("radio_system_id");
            return ok(id ? S.systems.filter(s => +s.radio_system_id === +id) : S.systems);
        }
        if (!(m = path.match(/^\/api\/systems\/(\d+)(\/.*)?$/))) return fail("Not available in the demo.", 404);
        const sid = +m[1], rest = m[2] || "", s = sys(sid);
        if (!s) return fail("System not found.", 404);

        if (rest === "") {
            if (method === "DELETE") {
                S.systems = S.systems.filter(x => x !== s);
                S.triggers = S.triggers.filter(t => +t.radio_system_id !== sid);
                return ok([], "System deleted.");
            }
            if (method === "PATCH") Object.assign(s, clean(body));
            return ok(s);
        }
        if (rest === "/apikey") { s.api_key = crypto.randomUUID?.() || String(Math.random()); return ok({ api_key: s.api_key }, "New API key generated."); }
        if (rest === "/export") return ok({});
        if (rest === "/tone_settings") return ok(s.tone);
        if (/\/test$/.test(rest)) return ok({}, DEMO_SENT);
        if (/\/facebook\/(background|preview)$/.test(rest) || /\/triggers\/\d+\/facebook\/(background|preview)$/.test(rest)) {
            return method === "GET" ? fail("No background.", 404) : fail("Uploads are turned off in the demo.");
        }

        // list children: Discord / Make fields, email addresses, geocoding regions
        if ((m = rest.match(/^\/discord\/fields(?:\/(\d+|reorder))?$/))) {
            if (m[1] === "reorder") return ok(s.discord.fields, "Order saved.");
            if (method === "GET") return ok(s.discord.fields);
            return listOps(s.discord.fields, "embed_field_id", body, m[1], method);
        }
        if ((m = rest.match(/^\/make\/fields(?:\/(\d+))?$/))) {
            if (method === "GET") return ok(s.make.fields);
            return listOps(s.make.fields, "payload_field_id", body, m[1], method);
        }
        if ((m = rest.match(/^\/emails(?:\/(\d+))?$/))) {
            s.email.recipients = s.email.recipients || [];
            if (method === "GET") return ok(s.email.recipients);
            return listOps(s.email.recipients, "email_id", body, m[1], method);
        }
        if ((m = rest.match(/^\/address_extraction\/regions(?:\/(\d+|reorder|bulk))?$/))) {
            const regions = s.address_extraction.regions = s.address_extraction.regions || [];
            if (m[1] === "reorder" || m[1] === "bulk") return ok(regions, "Saved.");
            if (method === "GET") return ok(regions);
            return listOps(regions, "region_id", body, m[1], method);
        }

        // settings tabs: /api/systems/<id>/<section>/settings
        if ((m = rest.match(/^\/([a-z_]+)\/settings$/))) {
            const sec = m[1];
            s[sec] = s[sec] || {};
            if (method !== "GET") {
                mergeSection(s[sec], sec, body);
                if (sec === "facebook") s.facebook.post_type = body.facebook_post_type || s.facebook.post_type;
            }
            return ok(s[sec], "Settings saved.");
        }

        // triggers
        if (rest === "/triggers/export") return ok({});
        if (rest === "/tones.csv") return ok({});
        if (rest === "/triggers/import") return fail("Importing is turned off in the demo. On your own server this adds triggers from a tones spreadsheet or an export file.");
        if (/^\/triggers\/?$/.test(rest)) {
            if (method === "POST") {
                const id = nextId();
                const t = { alert_trigger_enable_discord: 0, alert_trigger_enable_make: 0, alert_trigger_enable_n8n: 0,
                            alert_trigger_enable_telegram: 0, alert_trigger_enabled: 1, alert_trigger_ignore_time: 30,
                            alert_trigger_stream_url: null, alert_trigger_talkgroup: null, alert_trigger_tone_tolerance: 2,
                            alert_trigger_type: "OR", two_tone_sets: [], long_tone_sets: [], hi_low_sets: [], pulsed_sets: [],
                            dtmf_sequences: [], last_fired_at: null, ...clean(body), alert_trigger_id: id, radio_system_id: sid };
                S.triggers.push(t);
                S.notifiers[id] = clone(S.blankNotifiers);
                // new triggers: only in the system's Pushover alert, like a real server
                Object.keys(S.notifiers[id].system_includes || {}).forEach(k => { S.notifiers[id].system_includes[k] = k === "pushover" ? 1 : 0; });
                return { status: 201, body: { success: true, message: `Trigger '${t.alert_trigger_name || ""}' created.`, result: { alert_trigger_id: id } } };
            }
            let list = S.triggers.filter(t => +t.radio_system_id === sid);
            const only = query.get("alert_trigger_id");
            if (only) list = list.filter(t => only.split(",").map(Number).includes(+t.alert_trigger_id));
            return ok(list);
        }
        if (!(m = rest.match(/^\/triggers\/(\d+)(\/.*)?$/))) return fail("Not available in the demo.", 404);
        const tid = +m[1], trest = m[2] || "", t = trig(tid);
        if (!t || +t.radio_system_id !== sid) return fail("Trigger not found for this system.", 404);
        if (trest === "") {
            if (method === "DELETE") {
                S.triggers = S.triggers.filter(x => x !== t);
                delete S.notifiers[tid];
                return ok([], "Trigger deleted.");
            }
            if (method === "PATCH") Object.assign(t, clean(body));
            return ok(t, method === "PATCH" ? "Trigger updated." : "OK");
        }
        if (trest === "/rules") {
            const map = { two_tone: "two_tone_sets", long: "long_tone_sets", long_tone: "long_tone_sets", hi_low: "hi_low_sets",
                          pulsed: "pulsed_sets", dtmf: "dtmf_sequences" };
            const tk = map[body.type_key] || body.type_key;
            if (!t[tk]) return fail("Invalid or unsupported type_key.");
            const rule = { rule_uid: "r" + nextId(), ...(body.rule || {}) };
            t[tk].push(rule);
            return ok({ alert_trigger_id: tid, type_key: tk, index: t[tk].length - 1, rule }, "Rule added.");
        }
        if (trest === "/pushover/settings") {
            S.pushover[tid] = S.pushover[tid] || clone(Object.values(S.pushover)[0] || {});
            if (method !== "GET") Object.assign(S.pushover[tid], clean(body));
            return ok(S.pushover[tid], "Pushover settings updated.");
        }
        const n = S.notifiers[tid] = S.notifiers[tid] || clone(S.blankNotifiers);
        if (trest === "/notifiers") return ok(n);
        if ((m = trest.match(/^\/notifiers\/([a-z0-9]+)\/system$/))) {
            n.system_includes[m[1]] = +body.include ? 1 : 0;
            return ok({ include: n.system_includes[m[1]] }, "Saved.");
        }
        if ((m = trest.match(/^\/notifiers\/([a-z0-9]+)\/test$/))) return ok([], DEMO_SENT);
        if ((m = trest.match(/^\/notifiers\/([a-z0-9]+)$/))) {
            const ch = n.channels[m[1]];
            if (!ch) return fail("Unknown notifier.", 404);
            Object.assign(ch, clean(body));
            ch.enabled = +body.enabled ? 1 : 0;
            return ok(ch, "Saved.");
        }
        return fail("Not available in the demo.", 404);
    }

    // ── hook fetch / XHR / file downloads ────────────────────────────
    function route(input, init) {
        const url = new URL(typeof input === "string" ? input : input.url, location.href);
        const i = url.pathname.search(/\/(api|auth)\//);
        if (i < 0) return null;
        const path = url.pathname.slice(i).replace(/\/+$/, "") || "/";
        const method = String(init?.method || (typeof input !== "string" && input.method) || "GET").toUpperCase();
        let body = {};
        const raw = init?.body;
        if (typeof raw === "string") { try { body = JSON.parse(raw); } catch { body = Object.fromEntries(new URLSearchParams(raw)); } }
        else if (raw instanceof FormData || raw instanceof URLSearchParams) body = Object.fromEntries(raw.entries());
        let res;
        try { res = handle(method, path, url.searchParams, body); }
        catch (e) { console.error("demo api", e); res = fail("Demo error: " + e.message, 500); }
        if (method !== "GET") save();
        return res;
    }

    const realFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
        const res = route(input, init);
        if (!res) return realFetch(input, init);
        return new Promise(r => setTimeout(() => r(new Response(JSON.stringify(res.body),
            { status: res.status, headers: { "Content-Type": "application/json" } })), 120));
    };

    const RealXHR = window.XMLHttpRequest;
    window.XMLHttpRequest = function () {
        const x = new RealXHR();
        let target = null;
        const open = x.open.bind(x), send = x.send.bind(x);
        x.open = (method, url, ...a) => { target = { method, url }; return open(method, url, ...a); };
        x.send = body => {
            const res = target && route(target.url, { method: target.method, body });
            if (!res) return send(body);
            Object.defineProperty(x, "status", { value: res.status });
            Object.defineProperty(x, "responseText", { value: JSON.stringify(res.body) });
            setTimeout(() => { x.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 1 }); x.onload?.(); }, 300);
        };
        return x;
    };

    // export / spreadsheet links are plain downloads: build the files here instead
    document.addEventListener("click", ev => {
        const a = ev.target.closest?.("a[href]");
        if (!a || a.download) return;
        const url = new URL(a.getAttribute("href"), location.href);
        let m = url.pathname.match(/\/api\/systems\/(\d+)\/(export|tones\.csv|triggers\/export)$/);
        if (!m) return;
        ev.preventDefault();
        const s = sys(m[1]);
        const slug = (s?.system_name || "system").replace(/[^A-Za-z0-9]+/g, "_");
        if (m[2] === "tones.csv") return saveFile(`ecrxn_${slug}_tones.csv`, tonesCsv(m[1]), "text/csv");
        const triggers = S.triggers.filter(t => +t.radio_system_id === +m[1]).map(t => ({
            ...t, notifiers: S.notifiers[t.alert_trigger_id]?.channels, pushover: S.pushover[t.alert_trigger_id] }));
        const doc = { format: "ecrxn_dispatch_demo_export", note: "Made by the browser demo - a real server's export can be imported.",
                      kind: m[2] === "export" ? "system" : "triggers",
                      system: m[2] === "export" ? s : undefined, triggers };
        saveFile(`ecrxn_${slug}_${m[2] === "export" ? "settings" : "triggers"}.json`, JSON.stringify(doc, null, 1), "application/json");
    }, true);

    // ── the demo ribbon ──────────────────────────────────────────────
    document.addEventListener("DOMContentLoaded", () => {
        const bar = document.createElement("div");
        bar.className = "demo-ribbon";
        bar.innerHTML = `<i class="bi bi-eye"></i><span><strong>Demo</strong><span class="demo-long"> · nothing is sent anywhere; changes reset after an hour</span></span>
            <button type="button" class="btn btn-sm btn-light">Reset</button>`;
        bar.querySelector("button").addEventListener("click", () => window.demoReset());
        document.body.appendChild(bar);
        // the login page: any name and password works
        const user = document.querySelector("[name=loginEmail]");
        if (user && !user.value) { user.value = "demo"; document.querySelector("[name=loginPassword]").value = "demo"; }
    });
})();
