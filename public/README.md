# ECRXN Dispatch Demo

`build_demo.py` builds the demo into `ecrxn-dispatch-demo/` (kept off GitHub; host that folder on your site). It is the
real ECRXN Dispatch dashboard running entirely in the browser on made-up data: a demo system, three triggers and three sample calls (synthetic tones, one of them a page no trigger covers yet).
Every button works. Any username and password works on its login page.

**It can't be used for anything real.** There's no server behind it:

- Changes are kept only in that browser tab and reset after an hour, on **Reset**, or when the tab is closed.
- Every page carries a Content-Security-Policy that only allows the demo's own files, so webhooks, tokens,
  addresses or anything else typed in can never be sent anywhere. "Send test" only shows a message.
- Imports and uploads are switched off. Downloads (exports, the tones spreadsheet) are made in the browser from
  the demo data.

**Host it:** upload the `ecrxn-dispatch-demo` folder to any web host (your own site, GitHub Pages, Netlify, an
Apache or nginx folder) and open `index.html`. No server software or database is needed.

**Rebuild it** after changing the dashboard, so it always matches (needs ffmpeg and the app's Python environment):

```bash
.venv/bin/python public/build_demo.py        # Windows: .venv\Scripts\python public\build_demo.py
```

`build_demo.py` runs the app on a temporary database, so your real data is never read, and the demo's API key is
replaced with a dummy. `demo_src/` holds the in-browser stand-in for the server (`demo-api.js`) and the demo
ribbon's styles.
