/*********************************************************************
 *  Edit-Triggers page script  (Bootstrap 5.3 + DataTables v2)
 *  © ECRXN Dispatch
 *
 *  Highlights
 *  - Autosave for Tone Rules: add/edit/delete and drag-to-reorder
 *  - DataTables per tone-type (Responsive + RowReorder)
 *  - Hides each tone table when it has 0 rows; shows it when rows exist
 *  - Busy UI while saving (tiny "Saving…" badge + disabled action buttons)
 *********************************************************************/

/* ===================================================================
   0) GLOBALS / ELEMENT REFS
   ===================================================================*/

/** System/Trigger selectors + editor cards */
const sysSel   = document.getElementById("triggerSystemSelect");
const trigGrp  = document.getElementById("triggerSelectGroup");
const trigSel  = document.getElementById("triggerSelect");   // hidden; tracks the open trigger
const editorEl = document.getElementById("triggerEditor");    // offcanvas side panel
const editor   = bootstrap.Offcanvas.getOrCreateInstance(editorEl);
const listBody = document.getElementById("triggerListBody");
const listWrap = document.getElementById("triggerListWrap");
const listEmpty = document.getElementById("triggerListEmpty");
const noMatch  = document.getElementById("triggerNoMatch");
const searchEl = document.getElementById("triggerSearch");
const addBtn   = document.getElementById("addTriggerBtn");
const LAST_SYSTEM_KEY = "icad.triggers.system";

/** Triggers of the current system, as shown in the list */
let triggerRows = [];

/** Config + state */
const AUTOSAVE_RULES = true;       // master switch for tone-rule autosave
let systemToneSettings = null;     // { tone_tolerance_pct?: number }
let triggerDefaultTolPct = null;   // number | null
let lastSavedToneState = null;     // snapshot used for rollback
let isSaving = false;              // saving-in-flight flag (UI hint)

/** Current selected IDs */
let curSys  = null;
let curTrig = null;
let curGroup = null;               // the group open in the group editor

/** Trigger groups of the current system */
let groupRows = [];

/** Hide trigger picklist until a system is chosen */
trigGrp.classList.add("d-none");


/* ===================================================================
   1) SMALL UTILITIES (alerts, csrf, fetch, debounce, waitFor)
   ===================================================================*/

/**
 * Show a quick, themed message to the user.
 * If a global showAlert() exists, that will be used; otherwise uses alert().
 * @param {string} m   Message text
 * @param {"info"|"success"|"warning"|"danger"} [t="info"]
 */
if (typeof showAlert !== "function") {
    window.showAlert = (m, t = "info") => alert(`${t.toUpperCase()}: ${m}`);
}

/** @returns {string} Best-effort CSRF token from page */
function getCsrfToken() {
    return (
        document.querySelector('input[name="_csrf_token"]')?.value ||
        document.querySelector('meta[name="csrf-token"]')?.content ||
        window.CSRF_TOKEN ||
        ""
    );
}

function statusSuffix(enabled) {
    return (+enabled ? "" : " [off]");
}

function pickNum(obj, keys) {
    for (const k of keys) {
        const v = obj?.[k];
        if (v != null && !Number.isNaN(+v)) return parseFloat(v);
    }
    return null;
}

/**
 * Deep clone a plain object/array.
 * @template T
 * @param {T} obj
 * @returns {T}
 */
function deepClone(obj) { return JSON.parse(JSON.stringify(obj)); }

/**
 * Return a debounced wrapper around fn.
 * @param {Function} fn
 * @param {number} [wait=600] milliseconds
 */
function debounce(fn, wait = 600) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), wait); };
}

/**
 * Lightweight JSON fetch with CSRF header + automatic JSON body.
 * Returns parsed JSON (never throws), attaches http_status if !ok.
 * @param {string} url
 * @param {{method?: string, body?: any, headers?: Record<string,string>}} [opts]
 * @returns {Promise<object>}
 */
async function apiJson(url, { method = "GET", body = null, headers = {} } = {}) {
    const token = getCsrfToken();
    const opts = { method, credentials: "same-origin", headers: { ...headers } };

    // Always send CSRF header on state-changing calls
    if (!["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase()) && token) {
        opts.headers["X-CSRFToken"]  = token;
        opts.headers["X-CSRF-Token"] = token;
    }

    if (body !== null) {
        opts.headers["Content-Type"] = "application/json";
        if (token && body._csrf_token == null) body = { _csrf_token: token, ...body };
        opts.body = JSON.stringify(body);
    }

    const r = await fetch(url, opts);
    let data;
    try { data = await r.json(); }
    catch { data = { success: false, message: "Bad response", result: [] }; }
    if (!r.ok) data.http_status = r.status;
    return data;
}

/**
 * Polls a test function until it becomes true or times out.
 * @param {() => boolean} testFn
 * @param {number} [timeoutMs=3000]
 * @param {number} [intervalMs=50]
 * @returns {Promise<boolean>}
 */
function waitFor(testFn, timeoutMs = 3000, intervalMs = 50) {
    return new Promise(resolve => {
        const t0 = Date.now();
        const timer = setInterval(() => {
            if (testFn()) { clearInterval(timer); resolve(true); }
            else if (Date.now() - t0 > timeoutMs) { clearInterval(timer); resolve(false); }
        }, intervalMs);
    });
}


/* ===================================================================
   2) DEFAULTS / TOLERANCE RESOLUTION
   ===================================================================*/

/**
 * Find the default tolerance to apply when a rule’s tol_pct is blank:
 * prefer trigger-level, then fall back to system-level.
 * @returns {{tol: number|null, source: "trigger"|"system"|null}}
 */
function getDefaultTolPct() {
    if (triggerDefaultTolPct != null && !Number.isNaN(triggerDefaultTolPct)) {
        return { tol: triggerDefaultTolPct, source: "trigger" };
    }
    const sysTol = systemToneSettings?.tone_tolerance_pct;
    if (sysTol != null && !Number.isNaN(sysTol)) {
        return { tol: parseFloat(sysTol), source: "system" };
    }
    return { tol: null, source: null };
}

/**
 * Resolve tolerance for display (rule > trigger > system).
 * @param {any} ruleTol
 * @returns {{tol: number|null, source: "rule"|"trigger"|"system"|null}}
 */
function resolveTolForDisplay(ruleTol) {
    if (ruleTol != null && ruleTol !== "") {
        const n = parseFloat(ruleTol);
        return { tol: Number.isNaN(n) ? null : n, source: "rule" };
    }
    return getDefaultTolPct();
}


/* ===================================================================
   3) STARTUP (DOMContentLoaded) + SYSTEM/TRIGGER LOADING
   ===================================================================*/

document.addEventListener("DOMContentLoaded", async () => {
    await loadSystems();
    wirePatchForms();
    wireTriggerEnabledAutosave();
    await preselectFromURL();
});

/**
 * Load system-level tone settings from a few likely endpoints.
 * @param {string|number} systemId
 */
async function loadSystemToneSettings(systemId) {
    systemToneSettings = null;
    const candidates = [
        `/api/systems/${systemId}/tone_settings`,
        `/api/systems/${systemId}?include=tone_settings`,
        `/api/systems/${systemId}`
    ];

    for (const url of candidates) {
        try {
            const rsp = await apiJson(url);
            if (!rsp?.success) continue;

            const root = rsp.result || rsp.results || rsp.system || rsp;
            const ts   = root?.tone_settings || root?.system_tone_settings || root;
            if (!ts) continue;

            const tol =
                ts?.tone_tolerance_pct ??
                ts?.default_tone_tolerance ??
                ts?.tolerance_pct ??
                null;

            const tolNum = (tol != null && !Number.isNaN(+tol)) ? parseFloat(tol) : null;

            // build the per-type defaults
            const sysDefaults = {
                two_tone: {
                    min_len_a_s: pickNum(ts, ["two_tone_a_min_s","two_tone_min_len_a_s","min_len_a_s"]),
                    min_len_b_s: pickNum(ts, ["two_tone_b_min_s","two_tone_min_len_b_s","min_len_b_s"]),
                },
                long_tone: {
                    min_len_s:   pickNum(ts, ["long_min_s","long_tone_min_len_s","min_len_s"]),
                },
                hi_low: {
                    min_alternations: pickNum(ts, ["hi_low_min_alternations","hi_low_min_alts","min_alternations"]),
                    interval_s:       pickNum(ts, ["hi_low_interval_s","interval_s"]),
                },
                pulsed: {
                    min_cycles:  pickNum(ts, ["pulsed_min_cycles","min_cycles"]),
                    min_on_ms:   pickNum(ts, ["pulsed_min_on_ms","min_on_ms","on_min_ms"]),
                    max_on_ms:   pickNum(ts, ["pulsed_max_on_ms","max_on_ms","on_max_ms"]),
                    min_off_ms:  pickNum(ts, ["pulsed_min_off_ms","min_off_ms","off_min_ms"]),
                    max_off_ms:  pickNum(ts, ["pulsed_max_off_ms","max_off_ms","off_max_ms"]),
                }
            };

            systemToneSettings = {
                tone_tolerance_pct: tolNum,
                defaults: sysDefaults
            };
            break; // ✅ break only after we've set both tol + defaults
        } catch { /* noop */ }
    }
}

/** Populate the Systems select */
async function loadSystems() {
    const rsp = await apiJson("/api/systems");
    if (!rsp.success) { showAlert(rsp.message, "danger"); return; }

    sysSel.innerHTML = `<option value="">Select System</option>`;
    rsp.result.forEach(s =>
        sysSel.insertAdjacentHTML(
            "beforeend",
            `<option value="${s.radio_system_id}">${esc(s.system_name)}</option>`
        )
    );
}

/** Preselect system/trigger from URL params (?system=...&trigger=...) */
async function preselectFromURL() {
    const params = new URLSearchParams(location.search);
    const has  = v => v && Array.from(sysSel.options).some(o => o.value === String(v));
    let remembered = null;
    try { remembered = localStorage.getItem(LAST_SYSTEM_KEY); } catch { /* storage blocked */ }
    const realOpts = Array.from(sysSel.options).filter(o => o.value);

    // URL first, then the last system used, then the only system if there is just one
    let sys = has(params.get("system")) ? params.get("system")
            : has(remembered) ? remembered
            : (realOpts.length === 1 ? realOpts[0].value : null);
    const trig = params.get("trigger");
    if (!sys) return;

    sysSel.value = sys;
    await populateTriggersForSystem(sys);

    if (trig) {
        const ok = await waitFor(() =>
            Array.from(trigSel.options).some(o => o.value === String(trig)), 3000);
        if (ok) {
            trigSel.value = String(trig);
            trigSel.dispatchEvent(new Event("change"));
        }
    }
}

/**
 * Load triggers for a system and reveal the trigger picklist._fetch_system_tone_settings_row
 * Editor is hidden until a trigger is chosen.
 * @param {string|number|null} systemId
 */
async function populateTriggersForSystem(systemId) {
    curSys  = systemId || null;
    curTrig = null;

    if (curSys) await loadSystemToneSettings(curSys);

    trigSel.innerHTML = `<option value="">Select Trigger</option>`;
    toggleEditor(false);
    rememberSystem(curSys);

    if (!curSys) { triggerRows = []; groupRows = []; renderGroups(); renderTriggerList(); return; }

    const [rsp] = await Promise.all([apiJson(`/api/systems/${curSys}/triggers?full=1`), loadGroups()]);
    if (!rsp.success) { showAlert(rsp.message, "danger"); return; }
    triggerRows = rsp.result || [];
    renderGroups();
    renderTriggerList();

    rsp.result.forEach(t =>
        trigSel.insertAdjacentHTML(
            "beforeend",
            `<option value="${t.alert_trigger_id}" data-enabled="${t.alert_trigger_enabled ?? 1}">
      ${esc(t.alert_trigger_name)}${
                t.alert_trigger_talkgroup != null ? ` (TG ${t.alert_trigger_talkgroup})` : ""
            }${statusSuffix(t.alert_trigger_enabled ?? 1)}
    </option>`
        )
    );
}

/** System selector change → refresh triggers */
sysSel.addEventListener("change", async () => {
    await populateTriggersForSystem(sysSel.value || null);
});

/** Trigger selector change → load trigger payload + show editor */
trigSel.addEventListener("change", async () => {
    curTrig = trigSel.value || null;
    if (!curTrig) { toggleEditor(false); return; }

    const rsp = await apiJson(`/api/systems/${curSys}/triggers/${curTrig}?full=1`);
    if (!rsp.success) { showAlert(rsp.message, "danger"); toggleEditor(false); return; }

    populateEditor(rsp.result);
    document.getElementById("triggerEditorTitle").textContent = rsp.result.alert_trigger_name || "Trigger";
    toggleEditor(true);
});

/**
 * Toggle the editor vs empty-card state.
 * @param {boolean} show
 */
function toggleEditor(show) {
    if (show) editor.show();
    else editor.hide();
    setUrl();
}


/* ===================================================================
   4) EDITOR POPULATION (general tab, legacy fields, notifiers)
   ===================================================================*/

/**
 * Fill the whole editor from a trigger payload.
 * @param {object} t
 */
function populateEditor(t) {
    triggerDefaultTolPct = (t?.alert_trigger_tone_tolerance !== undefined && t?.alert_trigger_tone_tolerance !== null && t?.alert_trigger_tone_tolerance !== "")
        ? parseFloat(t.alert_trigger_tone_tolerance)
        : null;

    // General
    document.getElementById("updateTriggerId").value        = t.alert_trigger_id;
    document.getElementById("updateTriggerName").value      = t.alert_trigger_name;
    document.getElementById("updateTriggerEnabled").value   = t.alert_trigger_enabled;
    document.getElementById("updateTriggerType").value      = t.alert_trigger_type;
    document.getElementById("updateTriggerIgnore").value    = t.alert_trigger_ignore_time;
    document.getElementById("updateTriggerTol").value       = t.alert_trigger_tone_tolerance;
    document.getElementById("updateTriggerTalkgroup").value = t.alert_trigger_talkgroup ?? "";
    trigGroupSel.value = t.alert_trigger_group_id != null ? String(t.alert_trigger_group_id) : "";

    // Legacy single-value tone fields (kept for compatibility)
    const map = {
        alert_trigger_two_tone_a:         "alert_trigger_two_tone_a",
        alert_trigger_two_tone_a_length:  "alert_trigger_two_tone_a_length",
        alert_trigger_two_tone_b:         "alert_trigger_two_tone_b",
        alert_trigger_two_tone_b_length:  "alert_trigger_two_tone_b_length",
        alert_trigger_long_tone:          "alert_trigger_long_tone",
        alert_trigger_long_tone_length:   "alert_trigger_long_tone_length",
        alert_trigger_hi_low_tone_a:      "alert_trigger_hi_low_tone_a",
        alert_trigger_hi_low_tone_b:      "alert_trigger_hi_low_tone_b",
        alert_trigger_hi_low_alternations:"alert_trigger_hi_low_alternations",
        alert_trigger_pulsed_tone:        "alert_trigger_pulsed_tone",
        alert_trigger_pulsed_min_cycles:  "alert_trigger_pulsed_min_cycles",
    };
    for (const col of Object.keys(map)) {
        const el = document.querySelector(`[name="${col}"]`);
        if (el) el.value = t[col] ?? "";
    }

    // Tone Rules (DataTables)
    populateToneRules(t);

    // This trigger's own notifiers (incl. Pushover)
    loadNotifiers();
}

/**
 * Refresh the trigger <select> options and optionally re-select an ID.
 * @param {string|number|null} [selectId]
 */
async function reloadTriggerSelect(selectId = null) {
    trigSel.innerHTML = `<option value="">Select Trigger</option>`;
    const [rsp] = await Promise.all([apiJson(`/api/systems/${curSys}/triggers?full=1`), loadGroups()]);
    if (!rsp.success) return;
    triggerRows = rsp.result || [];
    renderGroups();
    renderTriggerList();

    rsp.result.forEach(t =>
        trigSel.insertAdjacentHTML(
            "beforeend",
            `<option value="${t.alert_trigger_id}" data-enabled="${t.alert_trigger_enabled ?? 1}">
      ${esc(t.alert_trigger_name)}${
                t.alert_trigger_talkgroup != null ? ` (TG ${t.alert_trigger_talkgroup})` : ""
            }${statusSuffix(t.alert_trigger_enabled ?? 1)}
    </option>`
        )
    );
    if (selectId) {
        trigSel.value = selectId;
        trigSel.dispatchEvent(new Event("change"));
    }
}


/* ===================================================================
   5) TRIGGER ADD/EDIT/DELETE MODALS (non-rule-level)
   ===================================================================*/

const modalEl   = document.getElementById("triggerModal");
const modalForm = document.getElementById("triggerForm");

/** Open Add Trigger modal (prefill system) */
document.getElementById("addTriggerBtn").addEventListener("click", () => {
    if (!curSys) { showAlert("Select a system first.", "warning"); return; }
    modalForm.reset();
    modalForm.modalSystemId.value  = curSys;
    modalForm.modalTriggerId.value = "";
    document.getElementById("triggerModalLabel").textContent = "Add Trigger";
});

/** Create or update a trigger */
modalForm.addEventListener("submit", async ev => {
    ev.preventDefault();
    const data  = Object.fromEntries(new FormData(modalForm).entries());
    const isNew = !data.alert_trigger_id;
    const url   = isNew
        ? `/api/systems/${curSys}/triggers`
        : `/api/systems/${curSys}/triggers/${data.alert_trigger_id}`;

    const rsp = await apiJson(url, { method: isNew ? "POST" : "PATCH", body: data });
    if (!rsp.success) { showAlert(rsp.message, "danger"); return; }

    bootstrap.Modal.getInstance(modalEl).hide();
    await reloadTriggerSelect(rsp.result.alert_trigger_id);
    showAlert(rsp.message, "success");
});

/* ----- Delete modal ----- */
const delModal = document.getElementById("triggerDeleteModal");
const delForm  = document.getElementById("triggerDeleteForm");

/** Preconfirm delete text */
document.getElementById("deleteTriggerBtn").addEventListener("click", () => {
    delForm.deleteTriggerId.value = curTrig;
    document.getElementById("deleteTriggerQuestion").textContent =
        `Delete trigger “${trigSel.selectedOptions[0].textContent}”?`;
});

/** Delete a trigger */
delForm.addEventListener("submit", async ev => {
    ev.preventDefault();
    const csrf = delForm._csrf_token.value;
    const rsp  = await apiJson(`/api/systems/${curSys}/triggers/${curTrig}`,
        { method: "DELETE", body: { _csrf_token: csrf } });
    if (!rsp.success) { showAlert(rsp.message, "danger"); return; }

    bootstrap.Modal.getInstance(delModal).hide();
    await reloadTriggerSelect();
    toggleEditor(false);
    showAlert(rsp.message, "success");
});


/* ===================================================================
   6) IN-CARD PATCH FORMS (General)
   ===================================================================*/

/** Attach PATCH handlers for on-card forms */
function wirePatchForms() {
    attachPatch("updateTriggerGeneralForm");
    attachPatch("updateTriggerTwoToneForm");    // back-compat if present
}

/**
 * Generic PATCH binder for a simple form that updates the trigger row.
 * @param {string} formId
 */
function attachPatch(formId) {
    const f = document.getElementById(formId);
    if (!f) return;
    f.addEventListener("submit", async ev => {
        ev.preventDefault();
        const data = Object.fromEntries(new FormData(f).entries());
        const rsp  = await apiJson(
            `/api/systems/${curSys}/triggers/${curTrig}`,
            { method: "PATCH", body: data }
        );
        showAlert(rsp.message, rsp.success ? "success" : "danger");
    });
}

/* ===================================================================
   7) TONE RULES: SCHEMA + STATE + RENDER HELPERS
   ===================================================================*/

function getSystemDefault(typeKey, fieldName) {
    return systemToneSettings?.defaults?.[typeKey]?.[fieldName] ??
        RULE_TYPES?.[typeKey]?.defaults?.[fieldName] ??
        null;
}

const FIELD_ALIASES = {
    two_tone: {
        freq_a_hz:      ["tone_a_hz", "two_tone_a", "tone_a", "freqAHz"],
        min_len_a_s:    ["two_tone_a_length", "tone_a_length", "a_min_s", "tone_a_min_s"],
        freq_b_hz:      ["tone_b_hz", "two_tone_b", "tone_b", "freqBHz"],
        min_len_b_s:    ["two_tone_b_length", "tone_b_length", "b_min_s", "tone_b_min_s"],
        tol_pct:        ["tolerance_pct", "tolerance", "tol", "tone_tolerance_pct"]
    },
    long_tone: {
        freq_hz:        ["long_tone_hz", "long_tone", "tone_hz", "frequency_hz"],
        min_len_s:      ["long_tone_length", "length_s", "tone_length_s"],
        tol_pct:        ["tolerance_pct", "tolerance", "tol", "tone_tolerance_pct"]
    },
    hi_low: {
        hi_freq_a_hz:   ["hi_hz", "high_hz", "hi_low_tone_a", "hi_freq_hz_a"],
        hi_freq_b_hz:   ["low_hz", "lo_hz", "hi_low_tone_b", "hi_freq_hz_b"],
        min_alternations:["alternations", "hi_low_alternations"],
        interval_s:     ["hi_low_interval_s", "interval"],
        tol_pct:        ["tolerance_pct", "tolerance", "tol", "tone_tolerance_pct"]
    },
    pulsed: {
        center_hz:      ["pulsed_center_hz", "pulsed_tone", "center"],
        min_cycles:     ["pulsed_min_cycles", "mincycles"],
        min_on_ms:      ["on_min_ms", "min_on"],
        max_on_ms:      ["on_max_ms", "max_on"],
        min_off_ms:     ["off_min_ms", "min_off"],
        max_off_ms:     ["off_max_ms", "max_off"],
        tol_pct:        ["tolerance_pct", "tolerance", "tol", "tone_tolerance_pct"]
    },
    dtmf: {
        sequence:       ["dtmf_sequence", "seq"]
    }
};

/** Server-side defaults used when building a new rule row in the UI */
const SCHEMA_DEFAULTS = {
    TWO_TONE_A_MIN_S  : 0.6,
    TWO_TONE_B_MIN_S  : 2.5,
    LONG_MIN_S        : 3.8,
    HI_LOW_MIN_ALTS   : 4,
    HI_LOW_INTERVAL_S : 0.2,
    PULSED_MIN_CYCLES : 6,
};

/** Spec per tone rule type (UI + wire format) */
const RULE_TYPES = {
    two_tone: {
        title: "Two-Tone",
        listId: "twoToneList",
        paneId: "trPaneTwoTone",
        emptyId: "twoToneEmpty",
        countId: "twoToneCount",
        key: "two_tone_sets",
        fields: [
            { name:"freq_a_hz",   label:"Tone A",   type:"number", step:"0.1", num:"float", suffix:"Hz" },
            { name:"min_len_a_s", label:"A min",    type:"number", step:"0.1", num:"float", suffix:"s"  },
            { name:"freq_b_hz",   label:"Tone B",   type:"number", step:"0.1", num:"float", suffix:"Hz" },
            { name:"min_len_b_s", label:"B min",    type:"number", step:"0.1", num:"float", suffix:"s"  },
            { name:"tol_pct",     label:"±Tol",     type:"number", step:"0.1", num:"float", suffix:"%", optional:true },
        ],
        layout: [["freq_a_hz","min_len_a_s"], ["freq_b_hz","min_len_b_s"], ["tol_pct"]],
        defaults: { min_len_a_s: SCHEMA_DEFAULTS.TWO_TONE_A_MIN_S, min_len_b_s: SCHEMA_DEFAULTS.TWO_TONE_B_MIN_S },
    },

    long_tone: {
        title: "Long Tone",
        listId: "longToneList",
        paneId: "trPaneLongTone",
        emptyId: "longToneEmpty",
        countId: "longToneCount",
        key: "long_tone_sets",
        fields: [
            { name:"freq_hz",   label:"Frequency", type:"number", step:"0.1", num:"float", suffix:"Hz" },
            { name:"min_len_s", label:"Min length",type:"number", step:"0.1", num:"float", suffix:"s"  },
            { name:"tol_pct",   label:"±Tol",      type:"number", step:"0.1", num:"float", suffix:"%", optional:true },
        ],
        layout: [["freq_hz","min_len_s"], ["tol_pct"]],
        defaults: { min_len_s: SCHEMA_DEFAULTS.LONG_MIN_S },
    },

    hi_low: {
        title: "Hi / Low",
        listId: "hiLowList",
        paneId: "trPaneHiLow",
        emptyId: "hiLowEmpty",
        countId: "hiLowCount",
        key: "hi_low_sets",
        fields: [
            { name:"hi_freq_a_hz",    label:"Hi",            type:"number", step:"0.1",  num:"float", suffix:"Hz" },
            { name:"hi_freq_b_hz",    label:"Low",           type:"number", step:"0.1",  num:"float", suffix:"Hz" },
            { name:"min_alternations",label:"Alternations",  type:"number", step:"1",    num:"int"                },
            { name:"interval_s",      label:"Interval",      type:"number", step:"0.05", num:"float", suffix:"s"  },
            { name:"tol_pct",         label:"±Tol",          type:"number", step:"0.1",  num:"float", suffix:"%", optional:true },
        ],
        layout: [["hi_freq_a_hz","hi_freq_b_hz"], ["min_alternations","interval_s"], ["tol_pct"]],
        defaults: { min_alternations: SCHEMA_DEFAULTS.HI_LOW_MIN_ALTS, interval_s: SCHEMA_DEFAULTS.HI_LOW_INTERVAL_S },
    },

    pulsed: {
        title: "Pulsed",
        listId: "pulsedList",
        paneId: "trPanePulsed",
        emptyId: "pulsedEmpty",
        countId: "pulsedCount",
        key: "pulsed_sets",
        fields: [
            { name:"center_hz",  label:"Center",     type:"number", step:"0.1", num:"float", suffix:"Hz" },
            { name:"min_cycles", label:"Min cycles", type:"number", step:"1",   num:"int"                },
            { name:"min_on_ms",  label:"Min ON",     type:"number", step:"1",   num:"int", suffix:"ms", optional:true },
            { name:"max_on_ms",  label:"Max ON",     type:"number", step:"1",   num:"int", suffix:"ms", optional:true },
            { name:"min_off_ms", label:"Min OFF",    type:"number", step:"1",   num:"int", suffix:"ms", optional:true },
            { name:"max_off_ms", label:"Max OFF",    type:"number", step:"1",   num:"int", suffix:"ms", optional:true },
            { name:"tol_pct",    label:"±Tol",       type:"number", step:"0.1", num:"float", suffix:"%", optional:true },
        ],
        layout: [["center_hz","min_cycles"], ["min_on_ms","max_on_ms"], ["min_off_ms","max_off_ms"], ["tol_pct"]],
        defaults: { min_cycles: SCHEMA_DEFAULTS.PULSED_MIN_CYCLES },
    },

    dtmf: {
        title: "DTMF",
        listId: "dtmfList",
        paneId: "trPaneDTMF",
        emptyId: "dtmfEmpty",
        countId: "dtmfCount",
        key: "dtmf_sequences",
        fields: [
            { name:"sequence",   label:"Sequence",  type:"text" },
        ],
        layout: [["sequence"]],
        defaults: {},
    },
};

/** In-memory state mirroring server arrays */
let toneState = {
    two_tone_sets  : [],
    long_tone_sets : [],
    hi_low_sets    : [],
    pulsed_sets    : [],
    dtmf_sequences : [],
};

/** Generate a short, stable UID for rule rows */
function uid() {
    return [...crypto.getRandomValues(new Uint8Array(8))]
        .map(b => b.toString(16).padStart(2, "0")).join("");
}

/** Simple formatters used by DataTables cell render */
const fmtHz  = v => v == null || v === "" ? "—" : `${Number(v).toFixed(1)} Hz`;
const fmtSec = v => v == null || v === "" ? "—" : `${Number(v).toFixed(2)} s`;


/* ===================================================================
   8) TONE RULES: DATATABLES RENDERING + ROW EVENTS
   ===================================================================*/

/** DataTable instances by typeKey */
const toneTables = {};

/** Back-compat wrapper for old callers */
function renderToneLists() { renderToneTables(); }

/**
 * Create (once) or retrieve the DataTable instance for a given type.
 * Adds:
 *  - Leading "drag" column as RowReorder handle
 *  - Field columns (formatted values)
 *  - Trailing Actions column (Edit/Delete)
 * @param {"two_tone"|"long_tone"|"hi_low"|"pulsed"|"dtmf"} typeKey
 * @returns {DataTable|null}
 */
function ensureToneTable(typeKey) {
    const spec = RULE_TYPES[typeKey];
    const host = document.getElementById(spec.listId);
    if (!host) return null;

    // Upgrade static list container to a table host (once)
    if (!host.dataset.upgraded) {
        host.dataset.upgraded = "1";
        host.className = "table-responsive border rounded dt-theme";
        host.innerHTML = `
    <table id="${spec.listId}_tbl"
           class="table table-sm table-striped table-hover align-middle w-100"></table>`;
    }
    if (toneTables[typeKey]) return toneTables[typeKey];

    const tableEl = host.querySelector("table");

    const columns = [
        { title: "", data: "_drag", orderable: false, searchable: false, className: "reorder-handle text-secondary", width: "1%" },
        ...spec.fields.map((f, i) => ({
            title: f.label,
            data: f.name,
            responsivePriority: i < 2 ? 1 : (i < 4 ? 2 : 5)
        })),
        { title: "Actions", data: "_actions", orderable: false, searchable: false, className: "text-nowrap", responsivePriority: 1 }
    ];

    const dt = new DataTable(tableEl, {
        data: [],
        columns,
        paging: false,
        searching: false,
        info: false,
        autoWidth: false,
        order: [],
        responsive: true,
        rowReorder: { selector: "td.reorder-handle" },
        language: { emptyTable: `No ${spec.title} rules` },
        layout: { topStart: null, topEnd: null, bottomStart: null, bottomEnd: null }
    });

    // Row-level action buttons (edit/delete)
    tableEl.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-edit-rule],[data-del-rule]");
        if (!btn) return;
        e.preventDefault();
        const uid = btn.dataset.uid;
        if (btn.hasAttribute("data-edit-rule")) openRuleModal(typeKey, uid);
        else deleteRule(typeKey, uid);
    });

    // Keep toneState order in sync after drag + debounced autosave
    dt.on("row-reorder", () => {
        const arr = toneState[spec.key] || [];
        const ordered = dt.rows().data().toArray()
            .map(row => arr.find(r => r.rule_uid === row._uid))
            .filter(Boolean);
        toneState[spec.key] = ordered;
        debouncedAutosave();
    });

    toneTables[typeKey] = dt;
    return dt;
}

/**
 * Resolve a value for a table field from a rule object, trying:
 *  - canonical name,
 *  - known aliases for this tone type,
 *  - generic tolerance fallbacks,
 *  - tolerant case/underscore differences.
 * Returns undefined only if not found anywhere.
 * @param {"two_tone"|"long_tone"|"hi_low"|"pulsed"|"dtmf"} typeKey
 * @param {string} fieldName
 * @param {object} rule
 */
function getRuleFieldValue(typeKey, fieldName, rule) {
    if (!rule) return undefined;

    // 1) Exact
    if (rule[fieldName] !== undefined) return rule[fieldName];

    // 2) Aliases
    const aliases = FIELD_ALIASES[typeKey]?.[fieldName] || [];
    for (const a of aliases) {
        if (rule[a] !== undefined) return rule[a];
    }

    // 3) Generic tolerance fallbacks for any type
    if (fieldName === "tol_pct") {
        const tolKeys = ["tolerance_pct", "tolerance", "tol", "tone_tolerance_pct"];
        for (const k of tolKeys) if (rule[k] !== undefined) return rule[k];
    }

    // 4) Loose key match (case/underscore insensitive)
    const norm = s => String(s).toLowerCase().replace(/[^a-z0-9]/g, "");
    const want = norm(fieldName);
    const entries = Object.entries(rule);
    for (const [k, v] of entries) {
        if (norm(k) === want) return v;
    }

    return undefined;
}

/**
 * Format one value according to field meta for display in the table.
 * Applies unit formatting and tol_pct inheritance display.
 * @param {object} f field spec
 * @param {any} v raw value
 * @returns {string}
 */
function formatCell(f, v) {
    // Show inherited tolerance if per-rule tol is null/blank
    if (f.name === "tol_pct") {
        const { tol } = resolveTolForDisplay(v);
        return tol == null ? "—" : `±${Number(tol).toFixed(1)} %`;
    }

    if (v == null || v === "") return "—";

    const asInt   = x => Number.isFinite(+x) ? parseInt(x, 10) : null;
    const asFloat = x => Number.isFinite(+x) ? parseFloat(x)  : null;

    if (f.type === "select")   return String(v).toUpperCase();
    if (f.name === "sequence") return String(v).toUpperCase();

    if (f.type === "number") {
        const num = (f.num === "int") ? asInt(v) : asFloat(v);
        if (num == null) return "—";
        const suf = (f.suffix || "").toLowerCase();
        if (suf.includes("hz")) return `${num.toFixed(1)} Hz`;
        if (suf === "s")        return `${num.toFixed(2)} s`;
        if (suf === "ms")       return `${Math.round(num)} ms`;
        if (suf === "%")        return `${num.toFixed(1)} %`;
        return String(num);
    }
    return String(v);
}

/**
 * Build a DataTables row object from an internal rule object.
 * @param {"two_tone"|"long_tone"|"hi_low"|"pulsed"|"dtmf"} typeKey
 * @param {object} rule
 */
function buildRowObject(typeKey, rule) {
    const spec = RULE_TYPES[typeKey];
    const obj  = { _uid: rule.rule_uid };

    obj._drag = `<span class="d-inline-flex align-items-center" title="Drag to reorder">
    <i class="bi bi-grip-vertical"></i>
  </span>`;

    spec.fields.forEach(f => {
        const raw = getRuleFieldValue ? getRuleFieldValue(typeKey, f.name, rule) : rule[f.name];
        obj[f.name] = formatCell(f, raw);
    });

    obj._actions = `
    <div class="btn-group btn-group-sm" role="group">
      <button type="button" class="btn btn-outline-secondary"
              data-edit-rule data-uid="${rule.rule_uid}">
        <i class="bi bi-pencil"></i> Edit
      </button>
      <button type="button" class="btn btn-outline-danger"
              data-del-rule data-uid="${rule.rule_uid}">
        <i class="bi bi-trash"></i> Delete
      </button>
    </div>`;
    return obj;
}

/**
 * Render all tone tables from toneState.
 * If a type has 0 rows, its container is hidden and "empty" helper is shown.
 */
function renderToneTables() {
    for (const [typeKey, spec] of Object.entries(RULE_TYPES)) {
        const host  = document.getElementById(spec.listId);
        const empty = document.getElementById(spec.emptyId);
        const badge = document.getElementById(spec.countId);
        if (!host) continue;

        const arr = toneState[spec.key] || [];
        if (badge) badge.textContent = String(arr.length);

        if (arr.length === 0) {
            host.classList.add("d-none");
            empty?.classList.remove("d-none");

            const maybeDt = toneTables[typeKey];
            if (maybeDt) maybeDt.clear().draw(false);
            continue;
        }

        host.classList.remove("d-none");
        empty?.classList.add("d-none");

        const dt   = ensureToneTable(typeKey);
        const data = arr.map(r => buildRowObject(typeKey, r));
        dt.clear();
        dt.rows.add(data);
        dt.draw(false);
    }
}


/* ===================================================================
   9) TONE RULES: MODAL ADD/EDIT FLOW (+ AUTOSAVE)
   ===================================================================*/

document.querySelectorAll("[data-rule-add]").forEach(btn => {
    btn.addEventListener("click", (e) => {
        e.stopPropagation();             // don't toggle the accordion
        openRuleModal(btn.dataset.ruleAdd, null);
    });
});

const ruleModalEl   = document.getElementById("toneRuleModal");
const ruleModal     = new bootstrap.Modal(ruleModalEl);
const ruleForm      = document.getElementById("toneRuleForm");
const ruleFieldsBox = document.getElementById("toneRuleFields");
const ruleUidInput  = document.getElementById("toneRuleUid");
const typeKeyInput  = document.getElementById("toneRuleTypeKey");
const ruleTitle     = document.getElementById("toneRuleModalLabel");

/**
 * Open the tone rule modal for add/edit of a single rule row.
 * Renders inputs per RULE_TYPES[typeKey].layout with units + placeholders.
 * @param {"two_tone"|"long_tone"|"hi_low"|"pulsed"|"dtmf"} typeKey
 * @param {string|null} [existingUid]
 */
function openRuleModal(typeKey, existingUid = null) {
    const spec = RULE_TYPES[typeKey];
    typeKeyInput.value = typeKey;

    let current = null;
    if (existingUid) {
        current = (toneState[spec.key] || []).find(r => r.rule_uid === existingUid) || null;
        ruleUidInput.value = existingUid;
        ruleTitle.textContent = `Edit ${spec.title} rule`;
    } else {
        ruleUidInput.value = "";
        ruleTitle.textContent = `Add ${spec.title} rule`;
    }

    const buildControl = (f, id) => {
        const label = `<label class="form-label" for="${id}">${f.label}${f.optional ? ' <span class="text-muted">(optional)</span>' : ''}</label>`;
        if (f.type === "select") {
            const opts = (f.options||[]).map(o => `<option value="${o}">${o}</option>`).join("");
            return `${label}
        <select id="${id}" class="form-select form-select-sm" name="${f.name}">${opts}</select>`;
        }
        const input = `<input id="${id}" class="form-control form-control-sm" type="${f.type}" name="${f.name}" ${f.step ? `step="${f.step}"` : ""}>`;
        if (f.suffix) {
            return `${label}
        <div class="input-group input-group-sm">
          ${input}
          <span class="input-group-text">${f.suffix}</span>
        </div>`;
        }
        return `${label}${input}`;
    };

    // Render fields in rows
    ruleFieldsBox.innerHTML = "";
    const rows = spec.layout && spec.layout.length ? spec.layout : [spec.fields.map(f => f.name)];

    rows.forEach(row => {
        const cols = row.length;
        const colWidth = Math.max(12 / cols, 3);
        const rowEl = document.createElement("div");
        rowEl.className = "row g-3 align-items-end";

        row.forEach(fname => {
            const f = spec.fields.find(x => x.name === fname);
            if (!f) return;
            const col = document.createElement("div");
            col.className = `col-12 col-md-${colWidth}`;
            const id = `fld_${typeKey}_${f.name}`;

            col.innerHTML = buildControl(f, id);
            rowEl.appendChild(col);

            // Initial value + helpful tolerance placeholder
            const el = col.querySelector(`[name="${f.name}"]`);
            if (f.name === "tol_pct") {
                const { tol, source } = getDefaultTolPct();
                if (tol != null) {
                    el.placeholder = `${tol.toFixed(1)}`;
                    el.title = `Leave blank to use ${tol.toFixed(1)}% from ${source} defaults`;
                } else {
                    el.placeholder = "";
                    el.title = "Optional per-rule tolerance in %";
                }
            }

            let val;
            if (current && current[f.name] != null) {
                val = current[f.name];
            } else {
                // prefer radio_system default, then type defaults, then select-first
                const sysDef = getSystemDefault(typeKey, f.name);
                if (sysDef != null && f.name !== "tol_pct") {
                    val = sysDef;
                } else if (f.name in (spec.defaults||{})) {
                    val = spec.defaults[f.name];
                } else if (f.type === "select") {
                    val = (f.options && f.options[0]) || "";
                } else {
                    val = "";
                }
            }
            if (f.type === "select")      el.value = (val || "").toString().toUpperCase();
            else if (f.type === "number") el.value = (val === null || val === undefined) ? "" : val;
            else                           el.value = val ?? "";

            /* ========= INSERT: system-default placeholder hint (optional) ======== */
            if ((val == null || val === "") && f.name !== "tol_pct") {
                const sysDef = getSystemDefault(typeKey, f.name);
                if (sysDef != null) {
                    el.placeholder = String(sysDef);
                    el.title = "Defaults to radio system setting";
                }
            }
        });

        ruleFieldsBox.appendChild(rowEl);
    });

    ruleModal.show();
}

/**
 * Add/Update a rule locally, re-render the table, and autosave to server.
 * Rolls back UI if save fails (handled in saveRulesToServer()).
 */
ruleForm.addEventListener("submit", async ev => {
    ev.preventDefault();
    const typeKey = typeKeyInput.value;
    const spec    = RULE_TYPES[typeKey];
    const uidVal  = ruleUidInput.value || uid();

    const data = { rule_uid: uidVal };
    spec.fields.forEach(f => {
        const el = ruleForm.querySelector(`[name="${f.name}"]`);
        let v = el ? el.value : null;

        if (f.type === "number") {
            if (v === "") v = null;
            else v = (f.num === "int") ? parseInt(v, 10) : parseFloat(v);
            if (Number.isNaN(v)) v = null;
        } else if (f.type === "select") {
            v = (v || "").toString().toUpperCase();
        } else {
            v = (v || "").trim();
        }
        data[f.name] = v;
    });

    spec.fields.forEach(f => {
        if (f.name === "tol_pct") return; // keep inheritance model for tolerance
        const v = data[f.name];
        if (v == null || v === "") {
            const sysDef = getSystemDefault(typeKey, f.name);
            if (sysDef != null) data[f.name] = sysDef;
        }
    });

    // Upsert locally
    const arr = toneState[spec.key] || (toneState[spec.key] = []);
    const i = arr.findIndex(r => r.rule_uid === uidVal);
    if (i >= 0) arr[i] = { ...arr[i], ...data };
    else arr.push({ ...spec.defaults, ...data });

    // Auto-open accordion if this is the first row for that type
    if ((toneState[spec.key] || []).length === 1) {
        const pane = document.getElementById(spec.paneId);
        if (pane) new bootstrap.Collapse(pane, { toggle: false }).show();
    }

    ruleModal.hide();
    renderToneTables();

    // Persist immediately (autosave)
    setSavingUI(true);
    try {
        await saveRulesToServer({ silent: false });
    } finally {
        setSavingUI(false);
    }
});


/* ===================================================================
   10) TONE RULES: DELETE + RENDER (AUTOSAVE)
   ===================================================================*/

/**
 * Delete a rule row, re-render, then persist immediately.
 * @param {"two_tone"|"long_tone"|"hi_low"|"pulsed"|"dtmf"} typeKey
 * @param {string} ruleUid
 */
async function deleteRule(typeKey, ruleUid) {
    const spec = RULE_TYPES[typeKey];
    const arr  = toneState[spec.key] || [];
    toneState[spec.key] = arr.filter(r => r.rule_uid !== ruleUid);
    renderToneLists(); // may hide table if now empty

    setSavingUI(true);
    try {
        await saveRulesToServer({ silent: false });
    } finally {
        setSavingUI(false);
    }
}


/* ===================================================================
   11) TONE RULES: STATE <-> SERVER + AUTOSAVE PLUMBING
   ===================================================================*/

/**
 * Replace in-memory toneState from a trigger payload and render.
 * @param {object} trigger
 */
function populateToneRules(trigger) {
    toneState = {
        two_tone_sets  : (trigger.two_tone_sets  || []).map(c => ({...c})),
        long_tone_sets : (trigger.long_tone_sets || []).map(c => ({...c})),
        hi_low_sets    : (trigger.hi_low_sets    || []).map(c => ({...c})),
        pulsed_sets    : (trigger.pulsed_sets    || []).map(c => ({...c})),
        dtmf_sequences : (trigger.dtmf_sequences || []).map(c => ({...c})),
    };
    renderToneLists();
    lastSavedToneState = deepClone(toneState);
}

/** Manual Save (kept as a safety valve) */
document.getElementById("saveRulesBtn").addEventListener("click", async ev => {
    ev.preventDefault();
    if (!curSys || !curTrig) return;

    setSavingUI(true);
    try {
        const rsp = await apiJson(`/api/systems/${curSys}/triggers/${curTrig}?full=1`, {
            method: "PATCH",
            body: buildRulesPayload()
        });

        showAlert(
            rsp.message || (rsp.success ? "Rules saved." : "Save failed"),
            rsp.success ? "success" : "danger"
        );

        if (rsp.success) {
            const ref = await apiJson(`/api/systems/${curSys}/triggers/${curTrig}?full=1`);
            if (ref.success) populateToneRules(ref.result);
        }
    } finally {
        setSavingUI(false);
    }
});

/** Reset to server state */
document.getElementById("resetRulesBtn").addEventListener("click", ev => {
    ev.preventDefault();
    trigSel.dispatchEvent(new Event("change"));
});

/**
 * Build the PATCH payload from toneState, adding sort_order based on UI order.
 * @returns {object}
 */
function buildRulesPayload() {
    const payload = {};
    for (const spec of Object.values(RULE_TYPES)) {
        const arr = toneState[spec.key] || [];
        payload[spec.key] = arr.map((r, idx) => ({ ...r, sort_order: idx }));
    }
    return payload;
}

/**
 * Toggle saving UI: disable action buttons and show a small "Saving…" badge.
 * @param {boolean} [saving=false]
 */
function setSavingUI(saving = false) {
    isSaving = !!saving;

    // Disable common buttons while saving to prevent double taps
    document.querySelectorAll('#saveRulesBtn, [data-rule-add], [data-edit-rule], [data-del-rule]')
        .forEach(btn => { if (btn) btn.disabled = isSaving; });

    // Show a tiny "Saving..." pill in the Tone Rules tab header
    let badge = document.getElementById('toneSavingBadge');
    if (!badge) {
        const tabBtn = document.querySelector('button[data-bs-target="#trig-tone"]');
        if (tabBtn) {
            badge = document.createElement('span');
            badge.id = 'toneSavingBadge';
            badge.className = 'badge bg-secondary ms-2 align-middle';
            badge.style.display = 'none';
            tabBtn.appendChild(badge);
        }
    }
    if (badge) {
        badge.textContent = 'Saving…';
        badge.style.display = isSaving ? '' : 'none';
    }
}

/** Debounced saver for reorder drags or bursts of quick edits */
const debouncedAutosave = debounce(() => saveRulesToServer({ silent: true }), 800);

/**
 * Persist current toneState to server.
 * Rolls back UI on failure so the user never ends up “saved visually but not really”.
 * @param {{silent?: boolean}} [opts]
 */
async function saveRulesToServer({ silent = false } = {}) {
    if (!AUTOSAVE_RULES || !curSys || !curTrig) {
        if (!silent) console.warn("Autosave skipped: missing curSys/curTrig or disabled.");
        return;
    }

    const prevSnapshot = deepClone(toneState);
    const payload = buildRulesPayload();

    let rsp;
    try {
        rsp = await apiJson(`/api/systems/${curSys}/triggers/${curTrig}?full=1`, {
            method: "PATCH",
            body: payload
        });
    } catch (e) {
        rsp = { success: false, message: e?.message || "Network error" };
    }

    if (!rsp.success) {
        // rollback
        toneState = prevSnapshot;
        renderToneTables();
        if (!silent) showAlert(rsp.message || "Failed to save tone rules.", "danger");
        return;
    }

    // Re-fetch authoritative state to keep client exactly in sync
    const ref = await apiJson(`/api/systems/${curSys}/triggers/${curTrig}?full=1`);
    if (ref.success) {
        populateToneRules(ref.result);
        lastSavedToneState = deepClone(toneState);
    }
    if (!silent) showAlert(rsp.message || "Rules saved.", "success");
}

function wireTriggerEnabledAutosave() {
    const sel = document.getElementById("updateTriggerEnabled");
    if (!sel) return;

    // remember last good value for rollback on failure
    sel.dataset.prev = sel.value;

    sel.addEventListener("change", async () => {
        if (!curSys || !curTrig) return;
        const newVal = sel.value; // "1" or "0"

        // optimistic UI: disable while saving
        sel.disabled = true;
        const rsp = await apiJson(`/api/systems/${curSys}/triggers/${curTrig}`, {
            method: "PATCH",
            body: { alert_trigger_enabled: newVal }
        });
        sel.disabled = false;

        if (!rsp.success) {
            showAlert(rsp.message || "Failed to update status.", "danger");
            // rollback
            sel.value = sel.dataset.prev ?? "1";
            return;
        }

        sel.dataset.prev = newVal;
        showAlert("Trigger status updated.", "success");
        // refresh the <select> labels so the “[off]” suffix reflects the new state
        await reloadTriggerSelect(curTrig);
    });
}


/* ===================================================================
   12) TRIGGER LIST (table, search, row menu) + SIDE-PANEL EDITOR
   ===================================================================*/

// Modals opened from inside the side panel must live at <body> level to stack above it
document.body.appendChild(ruleModalEl);

/** Escape text for safe insertion into HTML */
function esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, c =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Short number: 1000 -> "1000", 688.30 -> "688.3" */
const hz = v => (v == null || v === "") ? "?" : String(+Number(v).toFixed(1));

/** One badge per tone rule, e.g. "1000 / 1500 Hz", "Long 1200 Hz", "DTMF 123#" */
function toneBadges(t) {
    const out = [];
    (t.two_tone_sets  || []).forEach(r => out.push(["two", `${hz(r.freq_a_hz)} / ${hz(r.freq_b_hz)} Hz`]));
    (t.long_tone_sets || []).forEach(r => out.push(["long", `Long ${hz(r.freq_hz)} Hz`]));
    (t.hi_low_sets    || []).forEach(r => out.push(["hilow", `Hi/Low ${hz(r.hi_freq_a_hz)} / ${hz(r.hi_freq_b_hz)} Hz`]));
    (t.pulsed_sets    || []).forEach(r => out.push(["pulsed", `Pulsed ${hz(r.center_hz)} Hz`]));
    (t.dtmf_sequences || []).forEach(r => out.push(["dtmf", `DTMF ${String(r.sequence || "").toUpperCase()}`]));
    return out;
}

/** "2 h ago", "3 d ago", "never" */
function timeAgo(epoch) {
    if (!epoch) return "never";
    const s = Math.max(0, Date.now() / 1000 - epoch);
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    if (s < 86400 * 30) return `${Math.floor(s / 86400)} d ago`;
    return new Date(epoch * 1000).toLocaleDateString();
}

function triggerMatches(t, q) {
    if (!q) return true;
    const hay = [t.alert_trigger_name, t.alert_trigger_talkgroup ?? "any",
                 ...toneBadges(t).map(b => b[1])].join(" ").toLowerCase();
    return q.toLowerCase().split(/\s+/).every(word => hay.includes(word));
}

/** Draw the trigger table for the current system */
function renderTriggerList() {
    const hasSys = !!curSys;
    searchEl.disabled = !hasSys;
    addBtn.disabled = !hasSys;

    const showEmpty = (title, text) => {
        document.getElementById("triggerListEmptyTitle").textContent = title;
        document.getElementById("triggerListEmptyText").textContent = text;
        listEmpty.classList.remove("d-none");
        listWrap.classList.add("d-none");
        noMatch.classList.add("d-none");
    };
    if (!hasSys) return showEmpty("Select a system", "Choose a radio system above to see its triggers.");
    if (!triggerRows.length) return showEmpty("No triggers yet", "Click Add Trigger to create the first one for this system.");

    listEmpty.classList.add("d-none");

    const rows = triggerRows.filter(t => triggerMatches(t, searchEl.value.trim()));
    noMatch.classList.toggle("d-none", rows.length > 0);
    listWrap.classList.toggle("d-none", rows.length === 0);

    // With groups: a heading row per group (click = edit the group), then its triggers; ungrouped ones last
    const searching = !!searchEl.value.trim();
    const sections = groupRows.length
        ? [...groupRows.map(g => ({ g, rows: rows.filter(t => String(t.alert_trigger_group_id) === String(g.alert_trigger_group_id)) })),
           { g: null, rows: rows.filter(t => !groupById(t.alert_trigger_group_id)) }]
        : [{ g: null, rows, plain: true }];
    const head = ({ g, rows: r }) => `
        <tr class="trig-group-head" data-group-head="${g ? g.alert_trigger_group_id : ""}">
          <td colspan="7">
            <span class="grp-dot" style="background:${esc(g ? g.group_color : "transparent")}"></span>
            <span class="fw-semibold">${esc(g ? g.group_name : "No group")}</span>
            <span class="text-secondary small ms-1">${r.length} trigger${r.length === 1 ? "" : "s"}</span>
            ${g ? `<span class="grp-head-edit small ms-2"><i class="bi bi-pencil"></i> Edit group</span>` : ""}
          </td>
        </tr>`;
    listBody.innerHTML = sections
        .filter(sec => sec.plain || sec.rows.length || (sec.g && !searching))
        .map(sec => (sec.plain ? "" : head(sec)) + sec.rows.map(triggerRowHtml).join("")).join("");
}

/** One trigger's row in the list */
function triggerRowHtml(t) {
    const id = t.alert_trigger_id;
    const on = +(t.alert_trigger_enabled ?? 1) === 1;
    const badges = toneBadges(t);
    const tones = badges.length
        ? badges.map(([kind, label]) => `<span class="badge trig-tone trig-tone-${kind}">${esc(label)}</span>`).join(" ")
        : `<span class="text-secondary small">No tone rules</span>`;
    const match = badges.length > 1 ? (t.alert_trigger_type === "OR" ? "Any rule" : "All rules") : "—";
    const firedTitle = t.last_fired_at ? new Date(t.last_fired_at * 1000).toLocaleString() : "";
    return `
    <tr data-trigger-id="${id}" class="${on ? "" : "trig-off"}">
      <td class="fw-semibold trig-c-name">${esc(t.alert_trigger_name)}</td>
      <td class="trig-c-tg" data-label="Talkgroup">${t.alert_trigger_talkgroup != null ? esc(t.alert_trigger_talkgroup) : `<span class="text-secondary">Any</span>`}</td>
      <td class="trig-tones trig-c-tones">${tones}</td>
      <td class="d-none d-lg-table-cell text-secondary small">${match}</td>
      <td class="d-none d-md-table-cell text-secondary small trig-c-fired" title="${esc(firedTitle)}">${timeAgo(t.last_fired_at)}</td>
      <td class="text-nowrap trig-no-open trig-c-status">
        <div class="form-check form-switch d-inline-block m-0">
          <input class="form-check-input" type="checkbox" role="switch" data-act="toggle"
                 ${on ? "checked" : ""} aria-label="Enable or disable trigger">
        </div>
        <span class="trig-status ${on ? "trig-status-on" : ""}">${on ? "Enabled" : "Disabled"}</span>
      </td>
      <td class="text-end trig-no-open trig-c-menu">
        <div class="dropdown">
          <button class="btn btn-sm btn-link text-secondary trig-menu-btn" type="button"
                  data-bs-toggle="dropdown" data-bs-popper-config='{"strategy":"fixed"}' aria-expanded="false" aria-label="Trigger actions">
            <i class="bi bi-three-dots-vertical"></i>
          </button>
          <ul class="dropdown-menu dropdown-menu-end">
            <li><a class="dropdown-item" href="#" data-act="edit"><i class="bi bi-pencil me-2"></i>Edit</a></li>
            <li><a class="dropdown-item" href="#" data-act="toggle-menu"><i class="bi bi-power me-2"></i>${on ? "Disable" : "Enable"}</a></li>
            <li><hr class="dropdown-divider"></li>
            <li><a class="dropdown-item text-danger" href="#" data-act="delete"><i class="bi bi-trash me-2"></i>Delete</a></li>
          </ul>
        </div>
      </td>
    </tr>`;
}

/** Open a trigger in the side panel */
function openTrigger(id) {
    trigSel.value = String(id);
    trigSel.dispatchEvent(new Event("change"));
}

/** Enable/disable a trigger straight from the list */
async function setTriggerEnabled(id, on) {
    const rsp = await apiJson(`/api/systems/${curSys}/triggers/${id}`, {
        method: "PATCH",
        body: { alert_trigger_enabled: on ? "1" : "0" }
    });
    if (!rsp.success) showAlert(rsp.message || "Failed to update trigger.", "danger");
    else showAlert(on ? "Trigger enabled." : "Trigger disabled.", "success");
    await reloadTriggerSelect();
}

listBody.addEventListener("click", ev => {
    const groupHead = ev.target.closest("tr[data-group-head]");
    if (groupHead) {
        if (groupHead.dataset.groupHead) openGroup(groupHead.dataset.groupHead);
        return;
    }
    const row = ev.target.closest("tr[data-trigger-id]");
    if (!row) return;
    const id = row.dataset.triggerId;
    const act = ev.target.closest("[data-act]")?.dataset.act;

    if (act === "toggle") return;                                   // handled by the change event
    if (!act && ev.target.closest(".trig-no-open")) return;            // switch / menu cells never open the editor
    ev.preventDefault();

    const t = triggerRows.find(x => String(x.alert_trigger_id) === id);
    if (act === "toggle-menu") {
        setTriggerEnabled(id, +(t?.alert_trigger_enabled ?? 1) !== 1);
    } else if (act === "delete") {
        trigSel.value = id;
        curTrig = id;
        delForm.deleteTriggerId.value = id;
        document.getElementById("deleteTriggerQuestion").textContent = `Delete trigger “${t?.alert_trigger_name ?? ""}”?`;
        bootstrap.Modal.getOrCreateInstance(delModal).show();
    } else {
        openTrigger(id);                                            // row click or Edit
    }
});

listBody.addEventListener("change", ev => {
    if (ev.target.dataset.act !== "toggle") return;
    const id = ev.target.closest("tr[data-trigger-id]").dataset.triggerId;
    ev.target.disabled = true;
    setTriggerEnabled(id, ev.target.checked);
});

searchEl.addEventListener("input", renderTriggerList);

/** Closing the panel returns to the list and refreshes it (names, tones, status may have changed) */
editorEl.addEventListener("hidden.bs.offcanvas", () => {
    if (!curTrig) return;
    curTrig = null;
    trigSel.value = "";
    setUrl();
    if (curSys) reloadTriggerSelect();
});

/** Remember the system for next visit */
function rememberSystem(id) {
    try {
        if (id) localStorage.setItem(LAST_SYSTEM_KEY, String(id));
    } catch { /* storage blocked */ }
}

/** Keep ?system=&trigger= in the address bar so links and refresh land in the same place */
function setUrl() {
    const params = new URLSearchParams();
    if (curSys) params.set("system", curSys);
    if (curSys && trigSel.value) params.set("trigger", trigSel.value);
    const qs = params.toString();
    history.replaceState(null, "", location.pathname + (qs ? `?${qs}` : ""));
}

renderTriggerList();



/* ===================================================================
   13) TRIGGER NOTIFIERS - per channel: is this trigger in the system's
       alert, and does it send its own alert (Telegram, Discord, Make,
       Pushover, Email, n8n, Facebook)
   ===================================================================*/

const TEMPLATE_HELP = "Placeholders: {trigger_list}, {timestamp_readable}, {timestamp_24}, {talkgroup_id}, {transcript}, {address}, {incident_type}, {audio_url}, {stream_url}, {system_name} (full list: docs/alerts.md → Placeholders)";
const PUSHOVER_SOUNDS = ["pushover", "bike", "bugle", "cashregister", "classical", "cosmic", "falling", "gamelan", "incoming",
    "intermission", "magic", "mechanical", "pianobar", "siren", "spacealarm", "tugboat", "alien", "climb", "persistent",
    "echo", "updown", "vibrate", "none"];

/** Field list per channel. ph / help / note may be functions of the system summary (what a blank falls back to). */
const NOTIFIERS = [
    { key: "telegram", name: "Telegram", icon: "bi-telegram", dest: "channel_id", fields: [
        { k: "channel_id", label: "Channel ID", ph: "e.g. -1001234567890", col: 6, required: true,
          help: "The channel or group this trigger posts to. Add the bot to it as an admin." },
        { k: "bot_token", label: "Bot token", type: "password", col: 6,
          ph: s => s.telegram_bot_token ? "Blank = use the system's bot" : "From @BotFather (the system has no bot set)" },
        { k: "message_body", label: "Message", type: "textarea", ph: "Blank = use the system's message", help: TEMPLATE_HELP },
        { k: "send_audio", label: "Send the audio file as a voice message (off = text only; {audio_url} in the message adds a link)", type: "switch" },
    ] },

    { key: "discord", name: "Discord", icon: "bi-discord", dest: "webhook_url", fields: [
        { k: "webhook_url", label: "Webhook URL", type: "url", required: true, ph: "https://discord.com/api/webhooks/…",
          help: "Channel settings → Integrations → Webhooks → Copy Webhook URL." },
        { k: "message", label: "Message", type: "textarea", rows: 2, ph: "Optional text above the embed, e.g. @here {trigger_list} dispatched",
          help: TEMPLATE_HELP },
        { k: "embed_title", label: "Embed title", col: 6, ph: "Blank = use the system's title" },
        { k: "embed_color", label: "Embed color", type: "color", col: 6 },
        { k: "embed_footer", label: "Embed footer", ph: "Blank = use the system's footer" },
        { k: "fields", label: "Embed fields", type: "rows", add: "Add field",
          cols: [{ k: "label", ph: "Label, e.g. Address" }, { k: "value", ph: "Value, e.g. {address}" }], inline: true,
          help: s => `No fields = use the system's Discord fields (${s.discord_fields} enabled). Inline fields sit side by side.` },
        { k: "render_map", label: "Include a map of the address (when one was found)", type: "switch" },
        { k: "attach_audio", label: "Attach the audio file (up to 10 MB; use {audio_url} in a field or the message for a link)", type: "switch" },
    ] },

    { key: "make", name: "Make", icon: "bi-boxes", dest: "webhook_url", fields: [
        { k: "webhook_url", label: "Webhook URL", type: "url", required: true, ph: "https://hook.us1.make.com/…" },
        { k: "api_key", label: "API key", type: "password", ph: "Blank = use the system's key" },
        { k: "fields", label: "JSON keys and values", type: "rows", add: "Add key",
          cols: [{ k: "key", ph: "Key, e.g. message" }, { k: "value", ph: "Value, e.g. {trigger_list} at {timestamp_24}" }],
          help: s => `No keys = use the system's Make keys (${s.make_fields} enabled). ` + TEMPLATE_HELP },
        { k: "attach_audio", label: "Also send the audio file (form data, file field \"audio\")", type: "switch" },
    ] },

    { key: "pushover", name: "Pushover", icon: "bi-signpost-split-fill", dest: "pushover_group_token", fields: [
        { k: "pushover_group_token", label: "Group / user key", col: 6, required: true },
        { k: "pushover_app_token", label: "App token", type: "password", col: 6, required: true },
        { k: "pushover_subject", label: "Title", ph: "Blank = use the system's title" },
        { k: "pushover_body", label: "Message", type: "textarea", ph: "Blank = use the system's message", help: TEMPLATE_HELP },
        { k: "pushover_sound", label: "Sound", type: "select", col: 6, options: [["", "System's sound"], ...PUSHOVER_SOUNDS.map(x => [x, x])] },
    ], note: "Pushover can't carry audio files, so every alert includes a \"Dispatch Audio\" link to the call." },

    { key: "email", name: "Email", icon: "bi-envelope-at", dest: "recipients", fields: [
        { k: "recipients", label: "Send to", type: "textarea", rows: 2, required: true,
          ph: "chief@example.com, station12@example.com", help: "Separate addresses with commas or new lines." },
        { k: "subject", label: "Subject", ph: s => s.email_subject ? `Blank = “${s.email_subject}”` : "Dispatch Alert" },
        { k: "body", label: "Message (HTML allowed)", type: "textarea", ph: "Blank = use the system's message", help: TEMPLATE_HELP },
        { k: "attach_audio", label: "Attach the audio file (up to 25 MB)", type: "switch" },
        { k: "own_server", label: "Use a different mail server for this trigger", type: "switch", reveals: "server",
          help: s => s.email_server ? `Off = the system's mail server (${s.email_server}).` : "Off = the system's mail server (none is set yet: Radio Systems → Email)." },
        { k: "smtp_hostname", label: "SMTP server", col: 6, group: "server", ph: "smtp.gmail.com" },
        { k: "smtp_port", label: "Port", col: 6, group: "server", ph: "587", inputmode: "numeric" },
        { k: "smtp_username", label: "Username", col: 6, group: "server" },
        { k: "smtp_password", label: "Password", type: "password", col: 6, group: "server" },
        { k: "email_address_from", label: "From address", col: 6, group: "server",
          ph: s => s.email_from ? `Blank = ${s.email_from}` : "dispatch@example.com" },
        { k: "email_text_from", label: "From name", col: 6, group: "server", ph: "Blank = the system's" },
    ] },

    { key: "n8n", name: "n8n", icon: "bi-diagram-3", dest: "webhook_url", fields: [
        { k: "webhook_url", label: "Webhook URL", type: "url", required: true, ph: "https://n8n.example.com/webhook/…" },
        { k: "jwt_passphrase", label: "JWT passphrase", type: "password",
          ph: s => s.n8n_passphrase ? "Blank = use the system's passphrase" : "Required (the system has none set)" },
        { k: "attach_audio", label: "Also send the audio file (form data, binary field \"audio\")", type: "switch" },
    ], note: "Posts the full alert (every placeholder, including audio_url), signed with an HS256 JWT like the system's n8n alert." },

    { key: "facebook", name: "Facebook", icon: "bi-facebook", dest: "page_id", fields: [
        { k: "page_id", label: "Page ID", col: 6, required: true, ph: "e.g. 104123456789012",
          help: "Open your Page, click its name: Page ID is under Page transparency. Full steps: docs/alerts.md → Facebook." },
        { k: "page_token", label: "Page access token", type: "password", col: 6,
          ph: s => s.facebook_page_token ? "Blank = use the system's token" : "Long-lived Page token" },
        { k: "post_type", label: "Post as a video with the call audio (off = text post with a link)", type: "switch", on: "video", off: "post" },
        { k: "background", label: "Video background", type: "fbbg" },
        { k: "message_body", label: "Post text", type: "textarea", ph: "Blank = use the system's text", help: TEMPLATE_HELP },
    ], note: "Posts to a Facebook Page (Facebook doesn't let apps post to personal profiles). Use a system-user token from your Meta business portfolio, set to never expire, with pages_show_list, pages_manage_posts, pages_read_engagement and business_management. Step by step: docs/alerts.md → Facebook." },
];

const resolve = (v, sys) => (typeof v === "function" ? v(sys) : v) ?? "";
const notifDef = ch => NOTIFIERS.find(x => x.key === ch);

function rowHtml(f, row = {}) {
    const cells = f.cols.map(c =>
        `<input class="form-control form-control-sm notif-row-${c.k}" data-col="${c.k}" placeholder="${esc(c.ph)}"
                value="${esc(row[c.k] ?? "")}" autocomplete="off" aria-label="${esc(c.ph)}">`).join("");
    const inline = f.inline ? `<div class="form-check form-switch notif-row-inline mb-0" title="Show side by side with the next field">
            <input class="form-check-input" type="checkbox" role="switch" data-col="inline"${+(row.inline || 0) ? " checked" : ""}>
            <label class="form-check-label small">Inline</label></div>` : "";
    return `<div class="notif-row${f.inline ? " has-inline" : ""}">${cells}${inline}
        <button type="button" class="btn btn-sm btn-outline-danger notif-row-del" data-act="del-row" title="Remove" aria-label="Remove">
            <i class="bi bi-x-lg"></i></button></div>`;
}

/** One field of a channel card. id = the element id to use; who = "this trigger's" / "this group's" */
function fieldHtml(id, f, sys, who) {
    const ph = esc(resolve(f.ph, sys));
    const helpText = resolve(f.help, sys);
    const help = helpText ? `<div class="form-text">${esc(helpText)}</div>` : "";
    const req = f.required ? ` <span class="text-danger" title="Needed to turn on ${esc(who)} own alert">*</span>` : "";
    const col = f.col === 6 ? "col-12 col-md-6" : "col-12";
    const label = `<label class="form-label" for="${id}">${esc(f.label)}${req}</label>`;
    let input;
    switch (f.type) {
        case "switch":
            return `<div class="col-12"><div class="form-check form-switch">
                <input class="form-check-input" type="checkbox" role="switch" id="${id}" name="${f.k}"${f.reveals ? ` data-reveals="${f.reveals}"` : ""}>
                <label class="form-check-label" for="${id}">${esc(f.label)}</label>${help}</div></div>`;
        case "fbbg":
            return `<div class="col-12" data-fbbg-wrap><span class="form-label d-block">${esc(f.label)}</span><div data-fbbg></div></div>`;
        case "rows":
            return `<div class="col-12"><span class="form-label d-block">${esc(f.label)}</span>
                <div class="notif-rows" id="${id}" data-rows="${f.k}"></div>
                <button type="button" class="btn btn-sm btn-outline-secondary" data-act="add-row" data-rows="${f.k}">
                    <i class="bi bi-plus-lg"></i> ${esc(f.add)}</button>${help}</div>`;
        case "textarea":
            input = `<textarea class="form-control" id="${id}" name="${f.k}" rows="${f.rows || 3}" placeholder="${ph}"></textarea>`;
            break;
        case "select":
            input = `<select class="form-select" id="${id}" name="${f.k}">${
                f.options.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join("")}</select>`;
            break;
        case "color":
            input = `<div class="input-group">
                <input type="color" class="form-control form-control-color flex-grow-0" data-color-for="${id}" value="#F04646" title="Pick a color">
                <input class="form-control" id="${id}" name="${f.k}" placeholder="Blank = system's color" maxlength="7" autocomplete="off"></div>`;
            break;
        case "password":
            // new-password keeps the browser from filling in the saved login password
            input = `<div class="input-group">
                <input type="password" class="form-control" id="${id}" name="${f.k}" placeholder="${ph}" autocomplete="new-password" spellcheck="false">
                <button class="btn btn-outline-secondary" type="button" data-act="reveal" title="Show / hide" aria-label="Show or hide">
                    <i class="bi bi-eye"></i></button></div>`;
            break;
        default:
            input = `<input type="${f.type === "url" ? "url" : "text"}" class="form-control" id="${id}" name="${f.k}" placeholder="${ph}" autocomplete="off"${
                f.inputmode ? ` inputmode="${f.inputmode}"` : ""}>`;
    }
    return `<div class="${col}">${label}${input}${help}</div>`;
}

/**
 * The channel cards (Telegram, Discord, Make, Pushover, Email, n8n, Facebook) for a trigger or a group.
 *   kind "trigger": include-in-system switch + own alert; shows whether its group's alert covers it.
 *   kind "group":   the group's alert (one per call, naming the group's fired triggers).
 */
function makeNotifierEditor({ kind, acc, countEl, errEl }) {
    const isGroup = kind === "group";
    const who = isGroup ? "this group's" : "this trigger's";
    const prefix = isGroup ? "gnf" : "nf";
    const ownerId = () => (isGroup ? curGroup : curTrig);
    const base = () => `/api/systems/${curSys}/${isGroup ? `trigger-groups/${curGroup}` : `triggers/${curTrig}`}`;
    const fieldId = (ch, k) => `${prefix}-${ch}-${k}`;
    let st = null;   // { channels: {ch: cfg}, system: {...}, system_includes, pushover, group, facebook_background }

    function values(ch) {
        const sys = st.system || {};
        if (ch === "pushover") {
            const p = isGroup ? (st.channels.pushover || {}) : { ...(st.pushover || {}), enabled: +((st.pushover || {}).enable_pushover || 0) };
            return { ...p, pushover_subject: p.pushover_subject || sys.pushover_subject || "",
                     pushover_body: p.pushover_body || sys.pushover_body || "" };
        }
        return st.channels[ch] || {};
    }

    /** Trigger mode: is this channel's alert on for the trigger's group? */
    const groupOn = ch => !isGroup && !!st.group && (st.group.channels_on || []).includes(ch);

    function render() {
        const sys = st.system || {};
        acc.innerHTML = NOTIFIERS.map(n => {
            const plain = n.fields.filter(f => !f.group);
            const groups = [...new Set(n.fields.filter(f => f.group).map(f => f.group))];
            const fh = f => fieldHtml(fieldId(n.key, f.k), f, sys, who);
            // a group of fields sits right after the switch that reveals it
            const groupHtml = g => `<div class="col-12 notif-group" data-group="${g}">
                <div class="row g-3">${n.fields.filter(f => f.group === g).map(fh).join("")}</div></div>`;
            const body = plain.map(f => fh(f) + (f.reveals && groups.includes(f.reveals) ? groupHtml(f.reveals) : "")).join("");
            const note = resolve(n.note, sys);
            const sysOn = !!(sys.enabled || {})[n.key];
            const switches = isGroup
                ? `<div class="form-check form-switch">
                        <input class="form-check-input" type="checkbox" role="switch" id="${fieldId(n.key, "enabled")}" name="enabled">
                        <label class="form-check-label" for="${fieldId(n.key, "enabled")}">Send this group's ${esc(n.name)} alert</label>
                        <div class="form-text mt-0">One alert per call, naming the group's triggers that fired. A trigger with
                            its own ${esc(n.name)} alert sends that instead.</div>
                   </div>`
                : `<div class="form-check form-switch">
                        <input class="form-check-input" type="checkbox" role="switch" id="${fieldId(n.key, "system")}" name="include_system">
                        <label class="form-check-label" for="${fieldId(n.key, "system")}">Include in the system's ${esc(n.name)} alert</label>
                        <div class="form-text mt-0">${sysOn
                            ? `The system's ${esc(n.name)} alert is on.`
                            : `The system's ${esc(n.name)} alert is off (Radio Systems → ${esc(n.name)}), so nothing is sent there yet.`}</div>
                   </div>
                   <div class="form-check form-switch">
                        <input class="form-check-input" type="checkbox" role="switch" id="${fieldId(n.key, "enabled")}" name="enabled">
                        <label class="form-check-label" for="${fieldId(n.key, "enabled")}">Send this trigger's own ${esc(n.name)} alert</label>
                        <div class="form-text mt-0">Uses the settings below.</div>
                   </div>
                   <div class="form-text notif-group-note d-none" data-group-note></div>`;
            return `<div class="accordion-item notif-item" data-ch="${n.key}">
            <h2 class="accordion-header">
                <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse"
                        data-bs-target="#${prefix}-pane-${n.key}" aria-expanded="false">
                    <i class="bi ${n.icon} notif-icon notif-icon-${n.key}"></i>
                    <span class="notif-name">${esc(n.name)}</span>
                    <span class="notif-badges ms-auto">
                        <span class="notif-sys-badge" data-sys-status></span>
                        <span class="notif-grp-badge" data-grp-status></span>
                        <span class="notif-status" data-status></span>
                    </span>
                </button>
            </h2>
            <div id="${prefix}-pane-${n.key}" class="accordion-collapse collapse" data-bs-parent="#${acc.id}">
                <div class="accordion-body">
                    <form class="notif-form" data-ch="${n.key}" novalidate>
                        <div class="notif-switches">${switches}</div>
                        <h6 class="notif-own-title">${isGroup ? "This group's alert" : "This trigger's own alert"}</h6>
                        ${note ? `<p class="small text-body-secondary mb-3">${esc(note)}</p>` : ""}
                        <div class="row g-3">${body}</div>
                        <div class="d-flex flex-wrap gap-2 mt-3">
                            <button type="submit" class="btn btn-sm btn-success"><i class="bi bi-save"></i> Save</button>
                            <button type="button" class="btn btn-sm btn-outline-primary" data-act="test">
                                <i class="bi bi-send-check"></i> Send test</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>`;
        }).join("");
        NOTIFIERS.forEach(n => fill(n.key));
        updateCount();
    }

    function fill(ch) {
        const n = notifDef(ch);
        const v = values(ch);
        const form = acc.querySelector(`form[data-ch="${ch}"]`);
        form.elements.enabled.checked = +(v.enabled || 0) === 1;
        if (!isGroup) form.elements.include_system.checked = +((st.system_includes || {})[ch] ?? 1) === 1;
        for (const f of n.fields) {
            if (f.type === "fbbg") {
                mountFacebookBg(form);
                continue;
            }
            if (f.type === "rows") {
                const box = form.querySelector(`[data-rows="${f.k}"].notif-rows`);
                box.innerHTML = (Array.isArray(v[f.k]) ? v[f.k] : []).map(r => rowHtml(f, r)).join("");
                continue;
            }
            const el = form.elements[f.k];
            if (!el) continue;
            if (f.type === "switch") {
                el.checked = f.on ? v[f.k] === f.on : +(v[f.k] || 0) === 1;
                if (f.reveals) revealGroup(el);
                continue;
            }
            else el.value = v[f.k] ?? (f.type === "select" ? f.options[0][0] : "");
            if (f.type === "color" && /^#?[0-9a-f]{6}$/i.test(el.value)) {
                form.querySelector(`[data-color-for="${el.id}"]`).value = el.value.startsWith("#") ? el.value : `#${el.value}`;
            }
        }
        setStatus(ch);
    }

    /** Facebook card: background picker (own image / clip, else the group's, else the system's), only for video posts */
    function mountFacebookBg(form) {
        const sysBase = `/api/systems/${curSys}`;
        const groupBg = !isGroup && st.group ? st.group.facebook_background : null;
        FbBackground.mount(form.querySelector("[data-fbbg]"), {
            url: `${base()}/facebook/background`,
            previewUrl: `${base()}/facebook/preview`,
            own: st.facebook_background || null,
            fallback: groupBg || (st.system || {}).facebook_background || null,
            fallbackUrl: groupBg ? `${sysBase}/trigger-groups/${st.group.alert_trigger_group_id}/facebook/background`
                                 : `${sysBase}/facebook/background`,
            ownLabel: who,
            fallbackLabel: groupBg ? `the ${st.group.group_name} group's` : "the system's",
            csrf: getCsrfToken,
            onChange: info => { st.facebook_background = info; },
        });
        toggleFacebookBg(form);
    }

    function revealGroup(sw) {
        sw.form.querySelector(`[data-group="${sw.dataset.reveals}"]`)?.classList.toggle("d-none", !sw.checked);
    }

    function toggleFacebookBg(form) {
        form.querySelector("[data-fbbg-wrap]").classList.toggle("d-none", !form.elements.post_type.checked);
    }

    function setStatus(ch) {
        const n = notifDef(ch);
        const v = values(ch);
        const item = acc.querySelector(`.notif-item[data-ch="${ch}"]`);
        const badge = item.querySelector("[data-status]");
        const on = +(v.enabled || 0) === 1;
        const setUp = !!String(v[n.dest] ?? "").trim();
        const word = isGroup ? "Group" : "Own";
        badge.className = "notif-status badge rounded-pill " +
            (on ? "text-bg-success" : setUp ? "text-bg-secondary" : "notif-status-empty");
        badge.textContent = on ? `${word}: on` : setUp ? `${word}: off` : `${word}: not set up`;

        const sysBadge = item.querySelector("[data-sys-status]");
        const grpBadge = item.querySelector("[data-grp-status]");
        if (isGroup) {
            sysBadge.className = grpBadge.className = "d-none";
            return;
        }
        // System badge: only shown when the system's channel is on
        const sysOn = !!((st.system || {}).enabled || {})[ch];
        const included = +((st.system_includes || {})[ch] ?? 1) === 1;
        sysBadge.className = "notif-sys-badge badge rounded-pill " + (!sysOn ? "d-none" : included ? "notif-sys-in" : "notif-sys-out");
        sysBadge.textContent = included ? "System: in" : "System: left out";

        // Group badge + note: only shown when the trigger's group sends on this channel
        const gOn = groupOn(ch);
        const gName = st.group ? st.group.group_name : "";
        grpBadge.className = "notif-grp-badge badge rounded-pill " + (!gOn ? "d-none" : on ? "notif-sys-out" : "notif-sys-in");
        grpBadge.textContent = `${gName}: ${on ? "own instead" : "in"}`;
        const note = item.querySelector("[data-group-note]");
        note.classList.toggle("d-none", !gOn);
        note.textContent = !gOn ? "" : on
            ? `This trigger sends its own ${n.name} alert, so it's left out of the ${gName} group's.`
            : `This trigger is in the ${gName} group's ${n.name} alert.`;
    }

    function updateCount() {
        const on = NOTIFIERS.filter(n => +(values(n.key).enabled || 0) === 1).length;
        countEl.textContent = on;
        countEl.classList.toggle("d-none", on === 0);
        countEl.title = `${on} ${isGroup ? "group" : "own"} alert${on === 1 ? "" : "s"} on`;
    }

    function readForm(form) {
        const n = notifDef(form.dataset.ch);
        const out = { enabled: form.elements.enabled.checked ? 1 : 0 };
        for (const f of n.fields) {
            if (f.type === "fbbg") continue;            // uploaded separately
            if (f.type === "rows") {
                out[f.k] = [...form.querySelectorAll(`.notif-rows[data-rows="${f.k}"] .notif-row`)].map(r => {
                    const row = {};
                    r.querySelectorAll("[data-col]").forEach(el => {
                        row[el.dataset.col] = el.type === "checkbox" ? (el.checked ? 1 : 0) : el.value.trim();
                    });
                    return row;
                });
                continue;
            }
            const el = form.elements[f.k];
            if (el) out[f.k] = f.type === "switch" ? (f.on ? (el.checked ? f.on : f.off) : (el.checked ? 1 : 0)) : el.value.trim();
        }
        return out;
    }

    async function load() {
        if (!curSys || !ownerId()) return;
        const sysId = curSys, id = ownerId();
        acc.innerHTML = `<div class="text-body-secondary small py-3"><span class="spinner-border spinner-border-sm me-2"></span>Loading…</div>`;
        errEl.classList.add("d-none");
        const [n, p] = await Promise.all([
            apiJson(`${base()}/notifiers`),
            isGroup ? Promise.resolve({ success: true, result: {} }) : apiJson(`${base()}/pushover/settings`),
        ]);
        if (sysId !== curSys || id !== ownerId()) return;           // something else was opened meanwhile
        if (!n.success) {
            acc.innerHTML = "";
            errEl.textContent = n.message || "Couldn't load the notifiers.";
            errEl.classList.remove("d-none");
            return;
        }
        st = { ...n.result, pushover: p.success ? p.result : {} };
        render();
    }

    async function save(form) {
        const ch = form.dataset.ch;
        const name = notifDef(ch).name;
        const data = readForm(form);
        let rsp;
        if (ch === "pushover" && !isGroup) {
            const { enabled, ...rest } = data;
            if (enabled && !(rest.pushover_group_token && rest.pushover_app_token)) {
                rsp = { success: false, message: "Enter the Pushover group key and app token." };
            } else {
                rsp = await apiJson(`${base()}/pushover/settings`,
                    { method: "PATCH", body: { ...rest, enable_pushover: enabled } });
                if (rsp.success) st.pushover = rsp.result;
            }
        } else {
            rsp = await apiJson(`${base()}/notifiers/${ch}`, { method: "PUT", body: data });
            if (rsp.success) {
                st.channels[ch] = rsp.result;
                fillRowsOnly(form, ch);          // show the cleaned-up rows (blank ones dropped)
            }
        }
        if (rsp.success) {
            setStatus(ch);
            updateCount();
            const what = isGroup ? "group alert" : "own alert";
            showAlert(`${name} ${data.enabled ? `${what} on and saved` : "saved"}.`, "success");
            if (isGroup) onGroupChannelsChanged();
        } else {
            showAlert(rsp.message || `Couldn't save ${name}.`, "danger");
        }
        return rsp.success;
    }

    function fillRowsOnly(form, ch) {
        const v = values(ch);
        notifDef(ch).fields.filter(f => f.type === "rows").forEach(f => {
            form.querySelector(`.notif-rows[data-rows="${f.k}"]`).innerHTML = (v[f.k] || []).map(r => rowHtml(f, r)).join("");
        });
    }

    async function saveSystemInclude(form, input) {
        const ch = form.dataset.ch;
        const name = notifDef(ch).name;
        const rsp = await apiJson(`${base()}/notifiers/${ch}/system`,
            { method: "PUT", body: { include: input.checked ? 1 : 0 } });
        if (rsp.success) {
            st.system_includes = { ...(st.system_includes || {}), [ch]: rsp.result.include };
            setStatus(ch);
            showAlert(input.checked ? `Included in the system's ${name} alert.` : `Left out of the system's ${name} alert.`, "success");
        } else {
            showAlert(rsp.message || `Couldn't save.`, "danger");
        }
        return rsp.success;
    }

    acc.addEventListener("submit", async ev => {
        ev.preventDefault();
        const form = ev.target.closest("form.notif-form");
        const btn = form.querySelector("button[type=submit]");
        btn.disabled = true;
        await save(form);
        btn.disabled = false;
    });

    acc.addEventListener("input", ev => {
        // keep the color picker and its text box in step
        if (ev.target.dataset.colorFor) {
            document.getElementById(ev.target.dataset.colorFor).value = ev.target.value.toUpperCase();
        } else if (ev.target.closest(".input-group")?.querySelector("[data-color-for]") && /^#[0-9a-f]{6}$/i.test(ev.target.value)) {
            ev.target.closest(".input-group").querySelector("[data-color-for]").value = ev.target.value;
        }
    });

    acc.addEventListener("change", ev => {
        if (ev.target.name === "post_type") toggleFacebookBg(ev.target.form);
        if (ev.target.dataset.reveals) revealGroup(ev.target);
    });

    acc.addEventListener("change", async ev => {
        // Both switches save right away; the alert switch flips back if it can't be turned on yet
        const name = ev.target.name;
        if (name !== "enabled" && name !== "include_system") return;
        const form = ev.target.closest("form.notif-form");
        ev.target.disabled = true;
        const ok = name === "enabled" ? await save(form) : await saveSystemInclude(form, ev.target);
        if (!ok) ev.target.checked = !ev.target.checked;
        ev.target.disabled = false;
    });

    acc.addEventListener("click", async ev => {
        const btn = ev.target.closest("[data-act]");
        if (!btn) return;
        const form = btn.closest("form.notif-form");
        const act = btn.dataset.act;
        if (act === "reveal") {
            const input = btn.parentElement.querySelector("input");
            input.type = input.type === "password" ? "text" : "password";
            btn.querySelector("i").className = input.type === "password" ? "bi bi-eye" : "bi bi-eye-slash";
            return;
        }
        if (act === "add-row") {
            const f = notifDef(form.dataset.ch).fields.find(x => x.k === btn.dataset.rows);
            const box = form.querySelector(`.notif-rows[data-rows="${f.k}"]`);
            box.insertAdjacentHTML("beforeend", rowHtml(f));
            box.lastElementChild.querySelector("input").focus();
            return;
        }
        if (act === "del-row") {
            btn.closest(".notif-row").remove();
            return;
        }
        if (act !== "test") return;
        const ch = form.dataset.ch;
        const name = notifDef(ch).name;
        const old = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>Sending…`;
        const rsp = await apiJson(`${base()}/notifiers/${ch}/test`, { method: "POST", body: readForm(form) });
        btn.disabled = false;
        btn.innerHTML = old;
        showAlert(rsp.message || (rsp.success ? `Test sent to ${name}.` : `${name} test failed.`), rsp.success ? "success" : "danger");
    });

    return { load };
}

const triggerNotifiers = makeNotifierEditor({
    kind: "trigger",
    acc: document.getElementById("notifierAcc"),
    countEl: document.getElementById("notifierOnCount"),
    errEl: document.getElementById("notifierLoadError"),
});
const loadNotifiers = () => triggerNotifiers.load();



/* ===================================================================
   14) TRIGGER GROUPS - e.g. Fire / EMS: each group sends its own alerts
       (one per call) for its triggers, with its own Facebook background
   ===================================================================*/

const groupsCard   = document.getElementById("groupsCard");
const groupChips   = document.getElementById("groupChips");
const groupEdEl    = document.getElementById("groupEditor");
const groupEditor  = bootstrap.Offcanvas.getOrCreateInstance(groupEdEl);
const groupForm    = document.getElementById("groupGeneralForm");
const groupMembers = document.getElementById("groupMembers");
const groupAddEl   = document.getElementById("groupAddModal");
const groupDelEl   = document.getElementById("groupDeleteModal");
const trigGroupSel = document.getElementById("updateTriggerGroup");
const CHANNEL_ICONS = Object.fromEntries(NOTIFIERS.map(n => [n.key, [n.icon, n.name]]));

const groupNotifiers = makeNotifierEditor({
    kind: "group",
    acc: document.getElementById("groupNotifierAcc"),
    countEl: document.getElementById("groupNotifierOnCount"),
    errEl: document.getElementById("groupNotifierLoadError"),
});

function groupById(id) {
    return groupRows.find(g => String(g.alert_trigger_group_id) === String(id));
}

async function loadGroups() {
    if (!curSys) { groupRows = []; return; }
    const rsp = await apiJson(`/api/systems/${curSys}/trigger-groups`);
    groupRows = rsp.success ? (rsp.result || []) : [];
}

/** The chips above the list, and the Group dropdown in the trigger editor */
function renderGroups() {
    groupsCard.classList.toggle("d-none", !curSys);
    document.getElementById("groupsEmpty").classList.toggle("d-none", groupRows.length > 0);
    groupChips.innerHTML = groupRows.map(g => {
        const icons = (g.channels_on || []).map(ch =>
            `<i class="bi ${CHANNEL_ICONS[ch][0]}" title="${esc(CHANNEL_ICONS[ch][1])} alert on"></i>`).join("");
        return `<button type="button" class="btn btn-sm grp-chip" data-group-id="${g.alert_trigger_group_id}" title="Edit group">
            <span class="grp-dot" style="background:${esc(g.group_color)}"></span>${esc(g.group_name)}
            <span class="grp-chip-count" title="Triggers">${g.trigger_count}</span>${icons ? `<span class="grp-chip-icons">${icons}</span>` : ""}</button>`;
    }).join("");
    const cur = trigGroupSel.value;
    trigGroupSel.innerHTML = `<option value="">No group</option>` +
        groupRows.map(g => `<option value="${g.alert_trigger_group_id}">${esc(g.group_name)}</option>`).join("");
    trigGroupSel.value = cur;
}

/** After a group alert is switched on / off: refresh the chips (their channel icons) */
async function onGroupChannelsChanged() {
    await loadGroups();
    renderGroups();
}

function openGroup(id) {
    const g = groupById(id);
    if (!g) return;
    curGroup = String(id);
    document.getElementById("groupEditorTitle").textContent = g.group_name;
    groupForm.elements.group_name.value = g.group_name;
    groupForm.elements.group_color.value = g.group_color || "#6C757D";
    renderGroupMembers();
    bootstrap.Tab.getOrCreateInstance(document.querySelector('#groupTabs [data-bs-target="#grp-general"]')).show();
    groupNotifiers.load();
    groupEditor.show();
}

function renderGroupMembers() {
    if (!triggerRows.length) {
        groupMembers.innerHTML = `<div class="small text-secondary">This system has no triggers yet.</div>`;
        return;
    }
    groupMembers.innerHTML = triggerRows.map(t => {
        const gid = t.alert_trigger_group_id;
        const other = gid && String(gid) !== curGroup ? groupById(gid) : null;
        const id = `grp-m-${t.alert_trigger_id}`;
        return `<div class="form-check grp-member">
            <input class="form-check-input" type="checkbox" id="${id}" data-trigger-id="${t.alert_trigger_id}"${String(gid) === curGroup ? " checked" : ""}>
            <label class="form-check-label" for="${id}">${esc(t.alert_trigger_name)}${
                other ? ` <span class="small text-secondary">(now in ${esc(other.group_name)})</span>` : ""}</label></div>`;
    }).join("");
}

/** Put a trigger in a group (or none) and refresh what shows it */
async function setTriggerGroup(triggerId, groupId) {
    const rsp = await apiJson(`/api/systems/${curSys}/triggers/${triggerId}/group`,
        { method: "PUT", body: { alert_trigger_group_id: groupId || "" } });
    if (!rsp.success) {
        showAlert(rsp.message || "Couldn't change the group.", "danger");
        return false;
    }
    const t = triggerRows.find(x => String(x.alert_trigger_id) === String(triggerId));
    if (t) t.alert_trigger_group_id = rsp.result.alert_trigger_group_id;
    await loadGroups();
    renderGroups();
    renderTriggerList();
    return true;
}

groupChips.addEventListener("click", ev => {
    const chip = ev.target.closest("[data-group-id]");
    if (chip) openGroup(chip.dataset.groupId);
});

groupMembers.addEventListener("change", async ev => {
    const box = ev.target.closest("input[data-trigger-id]");
    if (!box) return;
    box.disabled = true;
    const ok = await setTriggerGroup(box.dataset.triggerId, box.checked ? curGroup : "");
    if (!ok) box.checked = !box.checked;
    else showAlert(box.checked ? `Added to ${groupById(curGroup)?.group_name}.` : "Taken out of the group.", "success");
    renderGroupMembers();
});

trigGroupSel.addEventListener("change", async () => {
    trigGroupSel.disabled = true;
    const t = triggerRows.find(x => String(x.alert_trigger_id) === String(curTrig));
    const before = t?.alert_trigger_group_id ?? "";
    const wanted = trigGroupSel.value;
    if (await setTriggerGroup(curTrig, wanted)) {
        trigGroupSel.value = wanted;
        showAlert(wanted ? `Now in ${groupById(wanted)?.group_name}.` : "No group now.", "success");
        loadNotifiers();                 // the Notifiers tab shows the group's alerts
    } else {
        trigGroupSel.value = String(before ?? "");
    }
    trigGroupSel.disabled = false;
});

document.getElementById("addGroupBtn").addEventListener("click", () => {
    document.getElementById("groupAddForm").reset();
    bootstrap.Modal.getOrCreateInstance(groupAddEl).show();
});
groupAddEl.addEventListener("shown.bs.modal", () => document.getElementById("groupAddName").focus());

document.getElementById("groupAddForm").addEventListener("submit", async ev => {
    ev.preventDefault();
    const f = ev.target;
    const rsp = await apiJson(`/api/systems/${curSys}/trigger-groups`, { method: "POST",
        body: { group_name: f.elements.group_name.value, group_color: f.elements.group_color.value } });
    if (!rsp.success) { showAlert(rsp.message || "Couldn't add the group.", "danger"); return; }
    bootstrap.Modal.getOrCreateInstance(groupAddEl).hide();
    showAlert(`Group “${rsp.result.group_name}” added. Tick its triggers.`, "success");
    await loadGroups();
    renderGroups();
    renderTriggerList();
    openGroup(rsp.result.alert_trigger_group_id);
});

groupForm.addEventListener("submit", async ev => {
    ev.preventDefault();
    const rsp = await apiJson(`/api/systems/${curSys}/trigger-groups/${curGroup}`, { method: "PATCH",
        body: { group_name: groupForm.elements.group_name.value, group_color: groupForm.elements.group_color.value } });
    showAlert(rsp.message || (rsp.success ? "Group saved." : "Couldn't save the group."), rsp.success ? "success" : "danger");
    if (!rsp.success) return;
    document.getElementById("groupEditorTitle").textContent = rsp.result.group_name;
    await loadGroups();
    renderGroups();
    renderTriggerList();
});

document.getElementById("deleteGroupBtn").addEventListener("click", () => {
    document.getElementById("groupDeleteQuestion").textContent = `Delete the group “${groupById(curGroup)?.group_name ?? ""}”?`;
    bootstrap.Modal.getOrCreateInstance(groupDelEl).show();
});

document.getElementById("groupDeleteForm").addEventListener("submit", async ev => {
    ev.preventDefault();
    const rsp = await apiJson(`/api/systems/${curSys}/trigger-groups/${curGroup}`, { method: "DELETE" });
    bootstrap.Modal.getOrCreateInstance(groupDelEl).hide();
    showAlert(rsp.message || (rsp.success ? "Group deleted." : "Couldn't delete the group."), rsp.success ? "success" : "danger");
    if (!rsp.success) return;
    triggerRows.forEach(t => { if (String(t.alert_trigger_group_id) === curGroup) t.alert_trigger_group_id = null; });
    groupEditor.hide();
    await loadGroups();
    renderGroups();
    renderTriggerList();
});

groupEdEl.addEventListener("hidden.bs.offcanvas", () => { curGroup = null; });

// Modals opened from the side panels must live at <body> level to stack above them
document.body.appendChild(groupAddEl);
document.body.appendChild(groupDelEl);
