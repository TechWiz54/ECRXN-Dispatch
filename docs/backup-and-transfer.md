# Backup and copying

Download a system's settings as one file and load it again, here or on another ECRXN Dispatch. Handy for backups,
for moving to a new computer, or for setting up a second server the same way.

---

## A whole system

- **Export:** open the system on **Radio Systems** and go to its **Export** tab, then **Download**. One file
  with **everything** for that system: every tab (upload, storage, tones, AI, every alert channel with its
  messages, webhook URLs, tokens and passwords) plus all its triggers, their tones and their own alerts.
- **Import:** **Radio Systems → Import** (next to **Add System**) creates a new system from such a file. If this
  server already has one with the same System ID or name, enter a new one in the boxes.

The imported system works straight away with every alert as it was. It gets a **new upload API key**, so point
your uploader at the new key. Not included: call history (calls, tone hits) and uploaded Facebook backgrounds.

> The file holds your tokens, passwords and webhook URLs. Keep it private, like a password.

---

## Triggers only

**Triggers → Export / import**. It always works on the system picked at the top of the Triggers page (the menu
names it), so switch systems there first:

- **Tones spreadsheet (CSV)**: one row per tone, for Excel or Google Sheets (below).
- **Triggers file (JSON)**: every trigger of the selected system, with its tones, settings and own alerts.
- **Import triggers or tones…**: adds the triggers from a triggers file, a whole-system file, or a tones
  spreadsheet to the selected system. Existing triggers aren't changed.

---

## Tones spreadsheet

| Trigger | Talkgroup | Enabled | Match | Type | Tone A (Hz) | Tone A length (s) | Tone B (Hz) | Tone B length (s) | Tolerance (%) | Other |
|---|---|---|---|---|---|---|---|---|---|---|
| Station 4 Fire | 100 | Yes | OR | Two-tone | 433.8 | 0.7 | 1641.7 | 2.6 | | |
| County EMS | | Yes | OR | Long tone | 1200 | 2 | | | | |
| Station 9 | | Yes | OR | DTMF | | | | | | 123# |

Fill in the same columns to add many triggers at once:

- Only **Trigger** is needed. Rows with the same trigger name become one trigger with several tones.
- **Type**: *Two-tone*, *Long tone*, *Hi-low*, *Pulsed* or *DTMF*. Left blank, two tones mean two-tone and one
  tone means long tone.
- Blank lengths use the system's defaults from its **Tones** tab.
- DTMF digits go in **Other**; hi-low and pulsed settings go there as `name=value`, e.g. `min_alternations=6`.
- A trigger whose name already exists is skipped, so importing the same sheet twice doesn't make duplicates.
  Rows with no usable tones are skipped too. Skipped rows are listed after the import.
