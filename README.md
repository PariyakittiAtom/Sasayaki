# Sasayaki 囁き

Desktop app that turns Japanese / Korean ASMR audio into **context-aware English subtitles**, then plays the
audio with the subtitles running in sync. Audio lives in named **collections** with a cover image.

## How it works

```
audio ─► normalize ─► Whisper large-v3 (VAD, word timestamps) ─► hallucination filter ─► cues
      ─► scene brief (who speaks to whom, tone, terms) ─► chunked contextual translation (Claude)
      ─► optional review pass ─► SQLite ─► player / editor / SRT-VTT-ASS export
```

* **Context-aware:** a whole-track *scene brief* (editable) plus a sliding window of earlier translated lines and
  upcoming source lines drives each translation, so dropped subjects, address terms and tone are resolved from
  context, not line by line. A per-collection **glossary** pins names and terms and also biases the speech
  recogniser.
* **ASMR-specific ASR handling:** level normalization for whispers, VAD tuned for soft speech, no cross-segment
  conditioning, stock-phrase/loop filtering. Suspected mis-hearings are flagged (amber) for review.
* **Fallback:** if Claude refuses or fails on a chunk, it is retried on a local Ollama model (flagged
  `local_fallback`).

## Setup (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

* Needs an NVIDIA GPU for speed (RTX 3050 6 GB works with `large-v3` @ `int8_float16`); falls back to CPU.
* The first transcription downloads the Whisper model (~3 GB for `large-v3`).
* Set your key in **Settings** (stored in Windows Credential Manager) or via the `ANTHROPIC_API_KEY` env var.
* Optional local fallback: install [Ollama](https://ollama.com) and `ollama pull qwen2.5:7b-instruct`.

## Use

```powershell
.\.venv\Scripts\python -m sasayaki                 # open the app
.\.venv\Scripts\python -m sasayaki run track.mp3 --lang ja --hint "girlfriend roleplay, whispers to listener"
```

Player keys: `Space` play/pause · `←/→` ±5 s · `↑/↓` previous/next line · `[` `]` shift subtitles ∓50 ms.

**Tips for accuracy:** write a short *context hint* when adding audio, add character names to the collection
glossary, review amber lines, and correct the *Scene brief* then use **Re-translate** (your edited lines are kept).

## Cloud library and Android app

The desktop app can keep a private copy of your library online (audio, covers, subtitles) in
[Supabase](https://supabase.com); the Android app in `mobile/` plays it with synced subtitles. The PC does all the
transcribing and translating and **pushes**; the phone only reads.

**One-time setup**

1. Create a free Supabase project. *SQL Editor* → paste [supabase/schema.sql](supabase/schema.sql) → *Run*. It creates the
   tables, two private storage buckets (`audio`, `covers`) and row-level security so only your account can see anything.
2. *Authentication → Users → Add user*: create your account (email + password). Then *Authentication → Sign In / Providers*
   and turn **off** "Allow new users to sign up", so nobody else can register on your project.
3. *Storage → Settings*: raise **Global file size limit**. The free plan allows at most 50 MB per file; longer
   recordings need the Pro plan (or compress the audio first). Files over the limit are reported in the sync message.
4. *Project Settings → API*: copy the **Project URL** and the **anon / publishable key**.
5. Desktop: *Settings → Cloud sync*: paste URL, key, email and password, tick *Upload my library automatically*, and use
   *Test cloud connection*. The password is kept in Windows Credential Manager.

After that, finished tracks upload by themselves (and edits, removals and cover changes follow). *Sync now* in the sidebar
or `python -m sasayaki sync` forces it. Only changed things are sent; an unchanged audio file is never uploaded twice.
Removing a track or collection on the PC also removes its online copy.

**Android app** (`mobile/`, Flutter): sign in with the same URL, key, email and password, then browse collections and play.
Subtitles follow playback; tap a line to jump to it; background playback and lock-screen controls work. Display mode, text
size and sync offset are remembered. Lines are read-only on the phone.

```powershell
cd mobile
flutter build apk --release        # -> build/app/outputs/flutter-apk/app-release.apk, copy it to the phone and install
flutter test                       # unit tests
```

Needs Flutter and the Android SDK (Android Studio). The APK is signed with the debug key, which is fine for installing
on your own phone; set up a real keystore before publishing to the Play Store.

## Measuring accuracy

`eval/` scores a clip against a human-verified reference (`eval/gold/<name>/gold.json`, see `eval/run_eval.py`):

```powershell
.\.venv\Scripts\python -m eval.run_eval eval/gold/clip1 --mode translation --quality high   # translator only
.\.venv\Scripts\python -m eval.run_eval eval/gold/clip1 --mode e2e --quality balanced       # audio → subtitles
```

Reports acceptable-line rate (LLM judge), CER, timing error, token usage, and writes a CSV for spot checks.

## Tests

```powershell
.\.venv\Scripts\python -m pytest
```
