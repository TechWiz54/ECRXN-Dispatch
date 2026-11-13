/*********************************************************************
 *  Facebook video background picker (Radio Systems + Triggers pages)
 *  Upload / remove an image or video clip shown behind the call audio,
 *  and render a short preview of what the post will look like.
 *
 *  FbBackground.mount(el, {
 *      url,          // background endpoint (GET file / POST upload / DELETE)
 *      previewUrl,   // POST -> short MP4
 *      own,          // {name, kind, version} | null   - this level's background
 *      fallback,     // {name, kind, version} | null   - used when own is empty (trigger -> system)
 *      fallbackUrl,  // GET URL of the fallback file
 *      ownLabel,     // "this trigger's" | "this system's"
 *      fallbackLabel,// "the system's"
 *      csrf,         // () => token
 *      onChange,     // (info|null) => void
 *  })
 *********************************************************************/
(function () {
    const ACCEPT = "image/*,video/*,.heic,.heif,.avif,.jfif,.tif,.tiff,.mkv,.mov,.m4v,.avi,.wmv,.flv,.mpg,.mpeg,.3gp,.ts,.mts,.m2ts,.ogv";
    const MAX_IMAGE_MB = 250, MAX_CLIP_MB = 2048;
    const VIDEO_EXT = /\.(mp4|mov|m4v|webm|mkv|avi|wmv|flv|mpe?g|3gp|ts|mts|m2ts|ogv|gif)$/i;
    const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const say = (m, t) => (typeof showAlert === "function" ? showAlert(m, t) : alert(m));

    function thumb(src, kind) {
        if (!src) return `<div class="fb-bg-empty"><i class="bi bi-image"></i><span>Black</span></div>`;
        return kind === "video"
            ? `<video src="${esc(src)}" muted loop autoplay playsinline></video>`
            : `<img src="${esc(src)}" alt="Video background">`;
    }

    function mount(el, opts) {
        let own = opts.own || null;
        el.innerHTML = `
            <div class="fb-bg">
                <div class="fb-bg-thumb" data-thumb></div>
                <div class="fb-bg-body">
                    <div class="fb-bg-status" data-fb-status></div>
                    <div class="progress fb-bg-progress d-none" role="progressbar" aria-label="Upload progress" data-progress>
                        <div class="progress-bar" style="width:0%"></div>
                    </div>
                    <div class="d-flex flex-wrap gap-2">
                        <label class="btn btn-sm btn-outline-primary mb-0" data-upload-btn>
                            <i class="bi bi-upload"></i> <span>Upload image or clip</span>
                            <input type="file" accept="${ACCEPT}" hidden data-file>
                        </label>
                        <button type="button" class="btn btn-sm btn-outline-danger" data-remove><i class="bi bi-trash"></i> Remove</button>
                        <button type="button" class="btn btn-sm btn-outline-secondary" data-preview><i class="bi bi-play-circle"></i> Preview video</button>
                    </div>
                    <div class="form-text">
                        Shown behind the call audio. Calls up to 90 seconds become vertical (9:16) videos, which Facebook
                        shows as Reels; longer calls are widescreen. The picture is cropped to fill, so keep the important
                        part in the middle. Pictures up to 250 MB, clips up to 2 GB in almost any format; they're shrunk
                        automatically when saved (clips keep their first 60 s, loop, and their sound is dropped).
                    </div>
                </div>
            </div>
            <div class="fb-bg-preview d-none" data-preview-box>
                <video controls playsinline data-preview-video></video>
                <div class="small text-body-secondary" data-preview-note></div>
            </div>`;
        const $ = s => el.querySelector(s);

        function render() {
            const fb = opts.fallback;
            const src = own ? `${opts.url}?v=${own.version}` : fb ? `${opts.fallbackUrl}?v=${fb.version}` : "";
            $("[data-thumb]").innerHTML = thumb(src, own ? own.kind : fb?.kind);
            $("[data-fb-status]").innerHTML = own
                ? `<span class="badge text-bg-success">Using ${esc(opts.ownLabel)} ${own.kind === "video" ? "clip" : "image"}</span>`
                : fb ? `<span class="badge text-bg-secondary">Using ${esc(opts.fallbackLabel)} ${fb.kind === "video" ? "clip" : "image"}</span>`
                     : `<span class="badge fb-bg-none">No background: the video will be black</span>`;
            $("[data-remove]").classList.toggle("d-none", !own);
            $("[data-upload-btn] span").textContent = own ? "Replace" : "Upload image or clip";
        }

        /** POST the file with upload progress (fetch can't report it) */
        function upload(file, onProgress) {
            return new Promise(resolve => {
                const body = new FormData();
                body.append("file", file);
                body.append("_csrf_token", opts.csrf());
                const xhr = new XMLHttpRequest();
                xhr.open("POST", opts.url);
                xhr.setRequestHeader("X-CSRFToken", opts.csrf());
                xhr.setRequestHeader("Accept", "application/json");
                xhr.upload.onprogress = e => e.lengthComputable && onProgress(Math.round(e.loaded / e.total * 100));
                xhr.onload = () => {
                    try { resolve(JSON.parse(xhr.responseText)); }
                    catch { resolve({ success: false, message: xhr.status === 413 ? "That file is too big for the server." : "Upload failed." }); }
                };
                xhr.onerror = () => resolve({ success: false, message: "Upload failed - check the connection." });
                xhr.send(body);
            });
        }

        async function busy(btn, on, text) {
            btn.classList.toggle("disabled", on);
            if (on) { btn.dataset.html = btn.innerHTML; btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${text}`; }
            else if (btn.dataset.html) btn.innerHTML = btn.dataset.html;
        }

        el.addEventListener("change", async ev => {
            if (!ev.target.matches("[data-file]")) return;
            const file = ev.target.files[0];
            ev.target.value = "";
            if (!file) return;
            const isClip = (file.type || "").startsWith("video/") || VIDEO_EXT.test(file.name);
            const maxMb = isClip ? MAX_CLIP_MB : MAX_IMAGE_MB;
            if (file.size > maxMb * 1024 * 1024) {
                say(`That file is too big (limit ${maxMb >= 1024 ? maxMb / 1024 + " GB" : maxMb + " MB"} for ${isClip ? "video clips" : "pictures"}).`, "danger");
                return;
            }
            const btn = $("[data-upload-btn]");
            busy(btn, true, "Uploading…");
            const bar = $("[data-progress]");
            const rsp = await upload(file, pct => {
                bar.classList.remove("d-none");
                bar.firstElementChild.style.width = `${pct}%`;
                if (pct >= 100) btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>Converting…`;
            });
            bar.classList.add("d-none");
            busy(btn, false);
            if (rsp.success) {
                own = rsp.result;
                render();
                $("[data-preview-box]").classList.add("d-none");
                opts.onChange?.(own);
                say("Background saved.", "success");
            } else {
                say(rsp.message || "Upload failed.", "danger");
            }
        });

        el.addEventListener("click", async ev => {
            if (ev.target.closest("[data-remove]")) {
                const r = await fetch(opts.url, { method: "DELETE", credentials: "same-origin",
                    headers: { "X-CSRFToken": opts.csrf(), "Accept": "application/json" } });
                const rsp = await r.json().catch(() => ({}));
                if (rsp.success) {
                    own = null; render();
                    $("[data-preview-box]").classList.add("d-none");
                    opts.onChange?.(null);
                    say("Background removed.", "success");
                } else say(rsp.message || "Couldn't remove it.", "danger");
            }
            const pb = ev.target.closest("[data-preview]");
            if (pb) {
                busy(pb, true, "Making preview…");
                try {
                    const r = await fetch(opts.previewUrl, { method: "POST", credentials: "same-origin",
                        headers: { "X-CSRFToken": opts.csrf(), "Content-Type": "application/json" },
                        body: JSON.stringify({ _csrf_token: opts.csrf() }) });
                    if (!r.ok) {
                        const j = await r.json().catch(() => ({}));
                        say(j.message || "Couldn't make a preview.", "danger");
                    } else {
                        const shape = r.headers.get("X-Video-Shape") || "";
                        const vid = $("[data-preview-video]");
                        if (vid.src) URL.revokeObjectURL(vid.src);
                        vid.src = URL.createObjectURL(await r.blob());
                        vid.classList.toggle("is-vertical", shape === "vertical");
                        $("[data-preview-note]").textContent = shape === "vertical"
                            ? "Preview of the latest call (first 15 s). It's up to 90 s long, so it's posted vertical, as a Reel."
                            : "Preview of the latest call (first 15 s). It's over 90 s long, so it's posted widescreen.";
                        $("[data-preview-box]").classList.remove("d-none");
                    }
                } finally { busy(pb, false); }
            }
        });

        render();
        return { set(info) { own = info; render(); } };
    }

    window.FbBackground = { mount };
})();
