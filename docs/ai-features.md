# AI features

Three optional add-ons, each switched on per system: **transcription** turns the voice into text, **address
extraction** finds the address in that text and puts it on a map, and **incident classification** labels the call
("Fire / Structure Fire"). Each step needs the one before it. All results can go into alerts through
[placeholders](alerts.md#placeholders).

These send call audio or transcripts to the service you choose (OpenAI, or your own server).

---

## Transcription

**Radio Systems → (system) → Transcribe.** Uses any OpenAI-compatible speech-to-text service:

- **OpenAI** (hosted): leave **Transcribe URL** blank and enter your OpenAI API key.
- **Your own server**: [iCAD Transcribe](https://github.com/TheGreatCodeholio/icad_transcribe) or
  [Speaches](https://github.com/speaches-ai/speaches). Enter its base address, e.g. `http://192.168.1.50:8000`.

| Setting | |
|---|---|
| **Transcribe URL** | The base address only. Don't add `/v1/audio/transcriptions`; it's added for you |
| **API key** | Your OpenAI key, or whatever your own server expects |
| **Model** | Blank uses the service's default (Whisper on OpenAI) |
| **Language** | e.g. `en`. Setting it improves accuracy and speed |
| **Prompt / hints** | Local names, unit IDs and radio phrases to help recognition. It can occasionally add words that weren't said, so keep it short |

Gives you `{transcript}` and shows the text, timed to the audio, in each call on the Dashboard.

---

## Address extraction

**Radio Systems → (system) → Address Extraction.** Needs transcription.

An OpenAI model picks the address out of the transcript, then Google Maps finds it on the map.

| Setting | |
|---|---|
| **OpenAI API key** | Blank uses `OPENAI_API_KEY` from `.env` |
| **Google Maps API key** | For geocoding (the Geocoding API must be enabled for the key) |
| **OpenAI model** | `gpt-4o-mini` is enough |
| **Default geocode region** | Country, state and optionally city, so "125 Sunset St" is looked up in the right place |

Gives you `{address}`, `{address_city}`, `{address_lat}`, `{address_maps_url}` and the rest, and lets Discord
alerts include a map of the address (**Include a map of the address** on the Discord settings).

---

## Incident classification

**Radio Systems → (system) → Incident Classification.** Needs transcription.

An OpenAI model reads the transcript and picks one category and type from a fixed list, such as *Fire / Structure
Fire*, *Medical / Chest Pain* or *Traffic / MVC (With Injuries)*, with a confidence from 0 to 1. Repeated dispatch
lines and unit acknowledgements are ignored.

| Setting | |
|---|---|
| **OpenAI API key** | Blank uses `OPENAI_API_KEY` from `.env` |
| **Model** | `gpt-4o-mini` (recommended) or `gpt-4o` |
| **Min confidence** | Results below this are dropped. Use `0` while testing, then `0.5`–`0.7` |

Gives you `{incident_category}`, `{incident_type}`, `{incident_confidence}` and `{incident_json}`. When it doesn't
run or isn't sure enough, they show `-` and `0.0`.

| Problem | Check |
|---|---|
| Nothing shows | Transcription is on and working; a key is set; the model is chosen; min confidence isn't too high |
| Confidence is always 0.0 | It didn't run, or every result was below min confidence |
