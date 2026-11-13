/*********************************************************************
 *  Export / import (Radio Systems + Triggers pages)
 *   - Radio Systems: "Import" creates a system from a file; each system's
 *                    Export tab downloads it (everything, tokens included)
 *   - Triggers:      download the tones spreadsheet / a triggers file,
 *                    import triggers (JSON export or tones CSV)
 *********************************************************************/
(function () {
    const csrf = () => document.querySelector('input[name="_csrf_token"]')?.value || "";
    const say = (m, t) => (typeof showAlert === "function" ? showAlert(m, t) : alert(m));

    async function postFile(url, form) {
        try {
            const r = await fetch(url, { method: "POST", body: form, credentials: "same-origin",
                headers: { "X-CSRFToken": csrf(), "Accept": "application/json" } });
            return await r.json().catch(() => ({ success: false, message: `The server answered ${r.status}.` }));
        } catch {
            return { success: false, message: "Couldn't reach the server." };
        }
    }

    function download(url) {
        // a plain navigation: the server sends the file as an attachment, the page stays put
        const a = document.createElement("a");
        a.href = url;
        a.rel = "noopener";
        document.body.appendChild(a);
        a.click();
        a.remove();
    }

    function busy(btn, on, text) {
        if (!btn) return;
        btn.disabled = on;
        if (on) { btn.dataset.html = btn.innerHTML; btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${text}`; }
        else if (btn.dataset.html) btn.innerHTML = btn.dataset.html;
    }

    // ── Radio Systems page ────────────────────────────────────────────
    const importForm = document.getElementById("importSystemForm");
    importForm?.addEventListener("submit", async ev => {
        ev.preventDefault();
        const btn = importForm.querySelector("[type=submit]");
        busy(btn, true, "Importing…");
        const rsp = await postFile("/api/systems/import", new FormData(importForm));
        busy(btn, false);
        if (!rsp.success) { say(rsp.message || "Import failed.", "danger"); return; }
        say(rsp.message, "success");
        bootstrap.Modal.getInstance(document.getElementById("importSystemModal"))?.hide();
        setTimeout(() => { location.href = `/dashboard/systems?system=${rsp.result.radio_system_id}`; }, 900);
    });

    // A system's Export tab
    const exportBtn = document.getElementById("exportSystemBtn");
    const sysSelect = document.getElementById("systemSelect");
    const nameExport = () => {
        const opt = sysSelect?.selectedOptions?.[0];
        const label = document.getElementById("exportSystemName");
        if (label) label.textContent = opt?.value ? opt.textContent.trim() : "this system";
    };
    document.getElementById("export-tab")?.addEventListener("shown.bs.tab", nameExport);
    sysSelect?.addEventListener("change", nameExport);
    exportBtn?.addEventListener("click", () => {
        const id = sysSelect?.value;
        if (!id) { say("Open a system first.", "warning"); return; }
        download(`/api/systems/${encodeURIComponent(id)}/export`);
    });

    // ── Triggers page ─────────────────────────────────────────────────
    const sysSel = document.getElementById("triggerSystemSelect");
    const trigBtn = document.getElementById("trigTransferBtn");
    const fileIn = document.getElementById("trigImportFile");
    if (!sysSel || !trigBtn) return;

    trigBtn.disabled = false;      // the page picks the system in code (no change event), so check on use instead

    // the menu always works on the system picked at the top of the page; say which
    trigBtn.parentElement.addEventListener("show.bs.dropdown", () => {
        const name = sysSel.selectedOptions[0]?.value ? sysSel.selectedOptions[0].textContent.trim() : "this system";
        trigBtn.parentElement.querySelectorAll("[data-trans-sys]").forEach(el => { el.textContent = name; });
    });

    trigBtn.parentElement.addEventListener("click", ev => {
        const item = ev.target.closest("[data-transfer]");
        if (!item) return;
        ev.preventDefault();
        if (!sysSel.value) { say("Pick a system first.", "warning"); return; }
        const id = encodeURIComponent(sysSel.value);
        switch (item.dataset.transfer) {
            case "tones-csv": download(`/api/systems/${id}/tones.csv`); break;
            case "triggers-json": download(`/api/systems/${id}/triggers/export`); break;
            case "import": fileIn.click(); break;
        }
    });

    fileIn.addEventListener("change", async () => {
        const file = fileIn.files[0];
        fileIn.value = "";
        if (!file) return;
        const form = new FormData();
        form.append("file", file);
        form.append("_csrf_token", csrf());
        busy(trigBtn, true, "Importing…");
        const rsp = await postFile(`/api/systems/${encodeURIComponent(sysSel.value)}/triggers/import`, form);
        busy(trigBtn, false);
        if (!rsp.success) { say(rsp.message || "Import failed.", "danger"); return; }
        say(rsp.message, rsp.result?.skipped?.length ? "warning" : "success");
        if (rsp.result?.triggers) setTimeout(() => location.reload(), 1200);
    });
})();
