# Sayso

Voice to text, anywhere. Hold a shortcut, talk, let go, and polished text appears in whatever Windows app you are
typing in. Built for locked-down corporate laptops: it runs without admin rights, from a zip folder, with no
install, no browser extension, no WSL and no background service.

```
Voice → speech recognition → AI writer → insert anywhere
```

> "hey can you tell john I'll be late" → "Hi John, I'll be running a few minutes late. I'll join as soon as I can."

Everything still works when a restriction removes something: no internet means local speech recognition and the
offline writer; a blocked executable means the next engine in the chain; a locked clipboard means typing or
accessibility insertion. See [docs/ENTERPRISE.md](docs/ENTERPRISE.md).

## Quick start (portable zip)

1. Download `Sayso-<version>-portable-win-x64.zip` from the Releases page and unzip it anywhere.
2. Run `Sayso.exe`. Look for the icon by the clock.
3. Hold **Ctrl+Alt+Space**, say something, release.
4. Optional: open Settings from the tray icon and add an AI key. Without one, Sayso still removes filler words,
   fixes punctuation and capitalisation, and formats "tell John …" messages offline.

Use `…-portable-offline-…zip` if the machine cannot download the speech model on first use.

## Shortcuts

| Action | Default | Notes |
|---|---|---|
| Push to talk | hold `Ctrl+Alt+Space` | release to insert |
| Toggle (hands free) | double-tap `Caps Lock` | tap twice to start, twice to stop; a single tap still toggles Caps Lock |
| Always listening | `Ctrl+Alt+L` | detects phrases by voice; a pill shows while the microphone is live |
| Edit selection by voice | hold `Shift` with either of the above | "make this shorter" replaces the selected text |
| Cancel | `Esc` | while recording or processing |

Change all of them in Settings › Shortcuts. If the keyboard hook is blocked, Sayso falls back to a toggle shortcut
and the tray menu (Start dictation).

## Writing styles

| Mode | What you get |
|---|---|
| `raw_transcript` | exactly what was heard, with spoken punctuation ("comma", "new line") applied |
| `rewrite_text` | your words, cleaned up: fillers, repeats, punctuation, self-corrections |
| `professional_mode` | clear, courteous workplace prose |
| `email_mode` | ready-to-send email body with greeting and closing |
| `meeting_notes_mode` | concise bullets with decisions and action items |
| `chat_mode` | short, friendly message |

Styles are chosen per app automatically (Outlook → email, Teams/Slack → chat, Word → professional, OneNote →
meeting notes) and can be overridden from the tray or in Settings › Apps.

## AI providers

Sayso asks providers in order and falls through on failure; a built-in offline writer is always last. API keys are
stored in Windows Credential Manager (installed) or a DPAPI-encrypted file next to the app (portable), never in
`settings.json`. Add keys in Settings › AI, or set `SAYSO_SECRET_LLM_OPENAI` etc. in the environment.

Provider settings live in `settings.json` (`%APPDATA%\Sayso\settings.json`, or `data\config\` when portable):

```jsonc
{
  "llm": {
    "chain": ["anthropic", "ollama", "offline"],
    "providers": {
      "anthropic":  { "kind": "anthropic", "model": "claude-haiku-5-5", "effort": "low", "api_key_ref": "llm.anthropic" },
      "openai":     { "kind": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "api_key_ref": "llm.openai" },
      "azure":      { "kind": "azure", "base_url": "https://YOUR-RESOURCE.openai.azure.com", "deployment": "gpt-4o-mini",
                      "api_version": "2024-06-01", "api_key_ref": "llm.azure" },
      "openrouter": { "kind": "openrouter", "base_url": "https://openrouter.ai/api/v1", "model": "anthropic/claude-sonnet-5.5",
                      "api_key_ref": "llm.openrouter" },
      "ollama":     { "kind": "ollama", "base_url": "http://127.0.0.1:11434/v1", "model": "llama3.2:3b" },
      "lmstudio":   { "kind": "lmstudio", "base_url": "http://127.0.0.1:1234/v1", "model": "local-model" },
      "llamacpp":   { "kind": "local", "base_url": "http://127.0.0.1:8080/v1", "model": "local" }
    }
  }
}
```

Any OpenAI-compatible endpoint, including Microsoft-hosted ones, works with `kind: "custom"` and a `base_url`.
Every key is documented in `config/settings.example.json`.

## Speech engines

1. **Faster Whisper** (local, default `base.en`, int8 CPU). Downloaded once to the models folder.
2. **whisper.cpp** (local): `bin\whisper-cli.exe` and `models\ggml-base.en.bin`, or a running whisper.cpp server.
3. **Windows Speech** (built in, no download): the enterprise floor.
4. **Cloud transcription** (optional, off by default): OpenAI or Azure OpenAI.

More engines and providers plug in through Python entry points; see `docs/ARCHITECTURE.md`.

## Building from source

```powershell
git clone https://github.com/karthikvenkat1988/Sayso
cd Sayso
.\scripts\dev.ps1            # venv, editable install with all extras, runs Sayso in portable mode
```

Tests run on Linux or Windows: `pip install -e ".[dev]"` then `pytest` (Qt tests use `QT_QPA_PLATFORM=offscreen`).

## Packaging

`packaging\build.ps1 -Target <name>` (Windows, Python 3.12, no admin) writes to `dist\`:

| Target | Output |
|---|---|
| `portable` | `Sayso-<ver>-portable-win-x64.zip` (folder build + `portable` flag file) |
| `portable-offline` | portable plus speech models and `whisper-cli.exe` |
| `onefile` | `Sayso-<ver>-win-x64.exe` (extracts to `%TEMP%` on start; some AV tools slow this) |
| `installer` | `Sayso-<ver>-setup.exe` (Inno Setup, per user, no admin) |
| `corporate` | offline bundle with `packaging\corporate\policy.json` baked in; add `-NoCloud` to leave cloud SDKs out |
| `zipapp` | `sayso-<ver>.pyz` + `run_from_source.cmd` for PCs that allow an approved Python but block unknown exes |
| `all` | everything above, plus `SHA256SUMS.txt` |

Add `-Sign -CertThumbprint <sha1>` to sign with `signtool`. Pushing a `v*` tag runs the release workflow.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Microphone access is off" | Settings › Privacy › Microphone › Let desktop apps access your microphone |
| Nothing happens on the shortcut | Tray › Diagnostics. If "keyboard hook" is blocked, use the toggle shortcut or the tray menu |
| Text appears as "Copied. Press Ctrl+V" | The target is an admin window or blocks input; paste manually |
| First dictation is slow | The speech model is loading; it is loaded at start-up after that |
| Defender or SmartScreen warns about the exe | Use the signed build, or the zipapp; see docs/ENTERPRISE.md |
| Logs | Tray › Open log folder. Logs never contain what you said |

## Docs

[Architecture](docs/ARCHITECTURE.md) · [Enterprise deployment](docs/ENTERPRISE.md) · [Security](docs/SECURITY.md) ·
[Performance](docs/PERFORMANCE.md) · [Roadmap](docs/ROADMAP.md) · [Implementation plan](docs/IMPLEMENTATION_PLAN.md)
