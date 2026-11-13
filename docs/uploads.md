# Uploads

How call audio gets into ECRXN Dispatch, and how tones and voice that arrive as two clips become one call.

- [The upload address](#the-upload-address) · [Fields](#fields) · [Responses](#responses) · [Examples](#examples)
- [Split uploads (tones first, voice after)](#split-uploads-tones-first-voice-after)

---

## The upload address

`POST http://<server>:9911/api/call-upload` as `multipart/form-data`. Scanner software that uploads
"RDIO-style" (RDIO Scanner downstreams, SDRTrunk, Trunk Recorder) already speaks this format.

Every upload needs the system's **API key** and **System ID** (both on **Radio Systems → General**):

| | Send it as any of |
|---|---|
| API key | header `Authorization: Bearer <key>`, or field `key` |
| System ID | field `system` or `system_id`, or header `X-System-ID` |

## Fields

| Field | |
|---|---|
| `audio` | **Required.** The audio file (MP3, WAV, M4A… anything ffmpeg reads) |
| `talkgroup` | The talkgroup; triggers with a talkgroup only match their own |
| `talkgroupLabel` | Optional talkgroup name, shown as `{talkgroup_name}` (RDIO uploaders send it) |
| `start_time` | When the call started, in seconds since 1970 |
| `dateTime` | Or the start as UTC ISO-8601, e.g. `2026-11-12T21:01:17Z` |

Without a start time, the time it arrived is used. Other fields are kept with the call.

## Responses

| Status | Meaning |
|---|---|
| **200** | Received. `result.triggers_fired` lists the triggers that fired, `result.merged` says if it was joined to an earlier tones clip |
| **202** | Tones only: held for a few seconds to join the voice clip that follows ([split uploads](#split-uploads-tones-first-voice-after)) |
| **400 / 401 / 403 / 404** | System ID missing / API key missing / API key for another system / no such system. The body has `error.code` and a `hint` |
| **422** | The audio couldn't be used (too short, unreadable) |
| **500** | Something failed on the server; see the log |

```json
{ "success": true, "message": "Call imported successfully",
  "result": { "radio_system_id": 1, "merged": false, "triggers_fired": ["Station 4 Fire"] } }
```

## Examples

```bash
curl -X POST http://localhost:9911/api/call-upload \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -F system=6643 -F talkgroup=100 -F audio=@dispatch.mp3
```

Or the included Python uploader, [`upload_example.py`](upload_example.py):

```bash
python docs/upload_example.py --url http://localhost:9911/api/call-upload \
    --system 6643 --token YOUR_API_KEY --audio dispatch.mp3 --talkgroup 100
```

---

## Split uploads (tones first, voice after)

Some systems send a page as two uploads: a short clip of tones, then the voice a few seconds later. Treated
separately you'd get a tones-only call and a voice call missing its tones. **Split Dispatch** (on the system's
**Upload** tab) holds a tones-only clip briefly and joins it to the next clip on the same talkgroup.

| Setting | What it does | Start with |
|---|---|---|
| **Split Dispatch** | On: hold tones-only clips and join them to the next voice clip. Off: every upload is its own call | On if you see tones and voice as separate calls |
| **Required voice after tones** (s) | How much voice must follow the tones for a clip to count as complete. Higher holds more clips | 2–3 |
| **Merge window** (s) | How long to wait for the voice clip. Too short misses joins; too long can join unrelated calls on busy talkgroups | 20–45 |

| Problem | Try |
|---|---|
| Unrelated calls are joined | A shorter merge window, or less required voice |
| Tones-only calls still show up alone | Split Dispatch on, a longer merge window, or slightly more required voice |
| Full calls are treated as tones-only | Less required voice; check the audio isn't very quiet or clipped |
