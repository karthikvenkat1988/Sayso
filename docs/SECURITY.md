# Security and privacy

## What leaves the machine

| Component | Data sent | To |
|---|---|---|
| Faster Whisper, whisper.cpp, Windows Speech | none: audio is processed locally | n/a |
| Cloud transcription (off by default) | the recorded audio clip | the OpenAI/Azure endpoint you configure |
| AI provider: Claude, OpenAI, Azure, OpenRouter | the transcript, writing mode and (if "share context" is on) the app name, window title and up to 1,200 characters before the cursor; in edit-selection mode the selected text | the endpoint you configure |
| AI provider: Ollama, LM Studio, llama.cpp | the same, to `127.0.0.1` only | your own machine |
| Offline writer | none | n/a |

Nothing else is sent: no telemetry, no crash reports, no update checks. `privacy.telemetry` exists only so policy can
assert it is false. Turn on **Offline only** (or policy `privacy.offline_only`) to disable every cloud engine and
provider; **no-cloud apps** do the same per program. Password fields (detected through UI Automation or the Windows
password edit style) and apps on the **blocked** list are never recorded or processed.

## Credentials

API keys are never written to `settings.json`, logs or history.

* Installed: Windows Credential Manager, generic credential `Sayso/<ref>`, local-machine persistence (not roamed).
* Portable: `data\secrets.bin`, encrypted with DPAPI (current user, entropy `Sayso.v1`). Copying the folder to another
  user or machine makes the file unreadable by design.
* If Credential Manager is blocked by policy, Sayso falls back to the DPAPI file.
* IT can inject keys through environment variables `SAYSO_SECRET_<REF>` (for example `SAYSO_SECRET_LLM_AZURE`), which
  take precedence and are never stored.

The Settings window shows only "Saved" or "Not set".

## Logging

`%LOCALAPPDATA%\Sayso\logs\sayso.log` (portable: `data\logs\`), rotated at 1 MB × 3. It records stage names, timings,
engine and provider names, and error types. It never records transcripts, inserted text, window titles or keys.

## History

Dictation history is a plaintext SQLite file in the user profile (`history.sqlite3`): text only, no audio. Default
retention is 30 days; users can turn it off, clear it, or policy can set retention. Encrypting it is on the roadmap.
Treat it like any document in the user's profile.

## Input handling and threat model

* **Keyboard hook scope:** a low-level hook sees every key press system-wide. Sayso's callback only feeds a small
  state machine that looks for the configured chords; it stores no keystrokes and returns in under a millisecond.
  Keys are swallowed only for the configured chord's non-modifier key (for example Space in Ctrl+Alt+Space) and for
  Caps Lock while double-tap is configured.
* **Injected input:** every event Sayso sends carries a private tag so its own hook ignores it. Windows UIPI stops
  Sayso from typing into elevated windows; Sayso does not try to bypass this and copies the text instead.
* **Clipboard:** pasted text is placed with the "exclude from history" and "do not sync" formats so it does not appear
  in Win+V history or cloud clipboard, and the previous clipboard contents are restored afterwards (only if the user
  copied nothing in between).
* **Prompt injection:** the transcript is passed to the AI inside tags with closing tags escaped, and the system prompt
  states that it is content, not instructions, except in edit-selection mode, where the user's spoken instruction is
  the intent. Output is plain text inserted at the cursor; the AI cannot run tools or reach files.
* **Updates:** none. Deploy new versions through your normal software channel; release artifacts ship with SHA-256
  checksums and can be Authenticode-signed.
* **Policy file:** read-only to Sayso. Place it where standard users cannot write if you need to prevent tampering.

## Reporting a vulnerability

Open a private security advisory on the GitHub repository.
