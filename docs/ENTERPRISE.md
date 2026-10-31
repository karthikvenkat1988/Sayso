# Sayso for managed Windows machines

Sayso needs no admin rights, installs no service or driver, and writes only to its own folders. This page covers
deploying it, what it needs from the network, and what happens when a control blocks something.

## Deployment options

| Option | How | When to use |
|---|---|---|
| Zip on a share or USB | Users unzip `…-portable-…zip` and run `Sayso.exe`. All data stays in `data\` beside it | Fastest; nothing installed |
| Intune Win32 app | Wrap `Sayso-<ver>-setup.exe` with `IntuneWinAppUtil`; install `Sayso-<ver>-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER`; detect `%LOCALAPPDATA%\Programs\Sayso\Sayso.exe` | Managed fleet, per-user install, start menu entry |
| Corporate zip | `…-corporate-win-x64.zip`: offline models and a baked-in `policy.json` | Air-gapped or strictly cloud-free sites |
| Python zipapp | `sayso-<ver>.pyz` + `run_from_source.cmd` with an approved Python | Application control blocks unknown exes |

## Policy file

Put `policy.json` next to `Sayso.exe` (ships inside the zip) or in `%PROGRAMDATA%\Sayso\policy.json` (deploy with
Intune/GPO file copy). It has the same shape as `settings.json` (see `config/policy.example.json`); **every key it
sets is locked**: the Settings window shows it disabled with "Set by your organization", and user edits are ignored.
Changes are picked up within a second without a restart. Policy can disable push to talk, toggle or
always-listening, force offline mode, fix the AI provider chain and endpoint, restrict speech engines, set history
retention, and list apps where Sayso never listens or never uses cloud AI.

## Network endpoints to allow-list

Only what you configure is contacted. There are no update checks and no telemetry.

| Feature | Host | Port |
|---|---|---|
| Claude | `api.anthropic.com` (or your gateway) | 443 |
| OpenAI | `api.openai.com` | 443 |
| Azure OpenAI | `<resource>.openai.azure.com` | 443 |
| OpenRouter | `openrouter.ai` | 443 |
| Cloud transcription (optional) | same as OpenAI or Azure above | 443 |
| Model download (first run, optional) | `huggingface.co`, `cdn-lfs.huggingface.co` | 443 |
| Local models (Ollama, LM Studio, llama.cpp) | `127.0.0.1` only | 11434 / 1234 / 8080 |

Proxy settings from `HTTP_PROXY`/`HTTPS_PROXY` are honoured. To avoid the model download, deploy the offline or
corporate bundle.

## When something is restricted

| Restriction | What Sayso does | User sees |
|---|---|---|
| No internet / proxy blocks AI | Skips that provider for 60 s, tries the next, ends at the offline writer | Nothing, unless everything cloud fails; tray shows an offline badge |
| AI endpoint returns 401/403 | Provider is treated as unavailable | Settings › AI shows "access denied" |
| Executables blocked (AppLocker/WDAC) | The engine is marked unavailable and the next one is used | Diagnostics: "Blocked by application control" |
| `Sayso.exe` blocked | Use the `.pyz` build | none |
| Microphone denied | Clear error with the setting to change | "Microphone access is off. Turn on Settings › Privacy › Microphone…" |
| Clipboard locked (DLP) | Switches to accessibility, then typing | Nothing |
| Keyboard hook blocked (EDR) | Toggle-only shortcuts via `RegisterHotKey` | Balloon: "Push-to-talk unavailable on this PC…" |
| All shortcuts blocked | Tray menu Start/Stop dictation | "Use the tray icon to dictate." |
| Admin window focused | Windows blocks input from a normal app; text is copied | "Can't type into an admin window. Copied. Press Ctrl+V." |
| Citrix / RDP | Types text instead of pasting (client clipboard often not redirected) | Nothing |
| Models missing and offline | Falls to Windows Speech | Diagnostics suggests the offline bundle |

Run **Tray › Diagnostics** (or `Sayso.exe --diagnose --offline`) to see every capability on a machine; the report
is plain JSON and contains no personal data.

## Application control notes

* **AppLocker:** allow by path rule for the folder users unzip to (for example `%OSDRIVE%\Tools\Sayso\*`), or by
  publisher rule once you use signed builds. The onedir build runs from its own folder; the one-file build unpacks
  to `%TEMP%`, which many policies block, so prefer the portable zip.
* **WDAC:** sign with your organisation's code-signing certificate (`build.ps1 -Sign`) and trust that signer.
* **PowerShell:** only the optional Windows Speech engine uses it (`-NoProfile -ExecutionPolicy Bypass` on a bundled
  script, hidden window). Constrained Language Mode will mark that engine unavailable; the others do not need it.
* **EDR:** Sayso uses a standard low-level keyboard hook (like any global hotkey tool) and `SendInput`. Injected keys
  are tagged so Sayso ignores its own. Ask your EDR vendor to allow the signed binary if the hook is blocked.

## Citrix, RDP and virtual desktops

Run Sayso on the **local** machine: it types into the remote window using Unicode key events, which any Citrix
Workspace or RDP client forwards. Running it inside the remote session works too but needs the microphone redirected.
Per-app overrides (`injection.app_overrides`, for example `{"wfica32": "keyboard"}`) are in Settings › Apps.
