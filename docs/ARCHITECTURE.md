# Sayso architecture

Sayso turns speech into finished text in whatever Windows app has focus:

```
Voice → capture + VAD → STT engine chain → AI rewrite chain → injection method chain → focused app
```

It is a single per-user process (no service, no driver, no admin), started from a portable folder, a single
exe, or a per-user install. Every layer is a chain of interchangeable plugins with a guaranteed last resort,
so a restriction removes quality, never the ability to dictate.

| Layer | Primary | Fallbacks | Always-works floor |
|---|---|---|---|
| Hotkeys | Low-level keyboard hook (hold, toggle, double-tap) | `RegisterHotKey` (toggle only) | Tray menu "Start dictation" |
| Audio | `sounddevice` (WASAPI shared) | MME device | Clear error with the Windows privacy setting to change |
| STT | faster-whisper (local) | whisper.cpp CLI/server, Windows Speech (System.Speech) | cloud Whisper if allowed |
| AI | Configured chain (default: Claude → Ollama) | Any of OpenAI, Azure OpenAI, OpenRouter, LM Studio, local server | Offline rule-based rewriter |
| Injection | Simulated paste with clipboard restore | Accessibility (EM_REPLACESEL / UIA), keyboard simulation | Clipboard replacement + "press Ctrl+V" toast |

## 1. System architecture

```mermaid
flowchart LR
    subgraph User["User session (no admin)"]
        HK[Hotkey service<br/>LL hook thread] -->|start/stop/cancel| CTL
        TRAY[Tray icon] --> CTL
        CTL[Controller<br/>Qt main thread]
        CTL --> OV[Overlay]
        CTL --> SET[Settings window]
        CTL --> HIS[History window]
        CTL -->|record| AUD[Audio capture<br/>+ VAD]
        CTL -->|capture at key-down| CTX[Focus context<br/>Win32 + UIA]
        CTL -->|clip + context| WRK[Worker thread]
        WRK --> PIPE[Pipeline]
        PIPE --> STT[STT chain]
        PIPE --> LLM[AI provider chain]
        WRK --> INJ[Injection chain]
        INJ --> APP[(Focused app)]
        PIPE --> HDB[(history.sqlite3)]
    end
    STT -.local.-> FW[faster-whisper model]
    STT -.local.-> WC[whisper-cli.exe]
    STT -.built-in.-> WS[System.Speech via PowerShell]
    STT -.optional cloud.-> CW[OpenAI / Azure Whisper]
    LLM -.cloud.-> CL[Claude API / OpenAI / Azure / OpenRouter]
    LLM -.localhost.-> LO[Ollama / LM Studio / llama.cpp]
    CFG[(settings.json)] --> CTL
    POL[(policy.json<br/>IT, read-only)] --> CTL
    SEC[(Credential Manager<br/>or DPAPI file)] --> CTL
```

## 2. Components and dependencies

Arrows mean "imports". `core`, `stt` and `llm` never import Qt or Windows APIs, so they are unit-tested on any
OS. `winsys` is the only package that calls Win32. `ui` is the only package that imports Qt, with one declared exception: `winsys/hotkeys.py` is a `QObject` so it can emit signals from its hook thread (`tests/test_layering.py` encodes this). `runtime_probes.py` and `app.py` sit above the layers and wire real Windows probes into `core.capabilities`.

```mermaid
flowchart TB
    main[__main__ / app] --> ui
    main --> core
    ui[ui: controller, overlay, settings, history, tray, theme, waveform] --> core
    ui --> audio
    ui --> winsys
    ui --> stt
    ui --> llm
    core[core: config, paths, modes, context, textproc, pipeline, history, capabilities, telemetry] --> stt
    core --> llm
    stt[stt: base, registry, faster_whisper, whisper_cpp, windows_speech, cloud]
    llm[llm: base, prompts, registry, anthropic, openai_compatible, offline]
    audio[audio: capture, vad]
    winsys[winsys: win32, hotkey_logic, hotkeys, context, clipboard, injection_policy, injection, credentials, single_instance]
    winsys --> core
```

## 3. Sequence: push-to-talk dictation

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant H as Hotkey thread
    participant C as Controller (Qt)
    participant A as Audio
    participant X as Context reader
    participant O as Overlay
    participant W as Worker
    participant S as STT chain
    participant L as AI chain
    participant I as Injector
    participant T as Target app

    U->>H: hold Ctrl+Alt+Space
    H->>C: start(PTT, command=false) [queued signal]
    C->>X: capture(hwnd) async, 300 ms budget
    C->>A: start()
    C->>O: Recording + live waveform
    U->>H: release
    H->>C: stop()
    C->>A: stop() → AudioClip
    C->>W: run(clip, context)
    W->>S: transcribe(clip)
    S-->>W: Transcript(text, confidence)
    W-->>O: Processing + transcript preview + confidence
    W->>L: rewrite(transcript, mode, context)
    L-->>W: streamed tokens → preview
    W->>I: insert(text, context)
    I->>T: Ctrl+V (clipboard restored after 150 ms)
    I-->>W: InsertReport(method, ms)
    W-->>C: DictationResult
    C->>O: Success "Inserted · 1.2 s" (fades)
```

## 4. Sequence: command mode (edit the selection by voice)

```mermaid
sequenceDiagram
    actor U as User
    participant C as Controller
    participant X as Context reader
    participant I as Injector
    participant L as AI chain
    U->>C: hold Shift + push-to-talk, "make this friendlier"
    C->>X: UIA TextPattern selection
    alt UIA gives no selection
        C->>I: copy_selection() (Ctrl+C, clipboard restored)
    end
    C->>L: rewrite(mode=command_mode, selection, instruction)
    L-->>C: replacement text
    C->>I: insert(replace_selection=true)
```

## 5. Sequence: enterprise degradation

```mermaid
sequenceDiagram
    participant W as Worker
    participant S as STT chain
    participant L as AI chain
    participant I as Injector
    W->>S: faster-whisper
    S--xW: EngineUnavailable (model missing, offline)
    W->>S: whisper.cpp
    S--xW: EngineUnavailable (exe blocked by AppLocker)
    W->>S: Windows Speech
    S-->>W: transcript
    W->>L: Claude
    L--xW: ProviderUnavailable (proxy blocks api.anthropic.com) → 60 s cool-down
    W->>L: Ollama localhost
    L--xW: connection refused
    W->>L: offline rules
    L-->>W: cleaned text
    W->>I: paste
    I--xW: clipboard locked by DLP
    W->>I: accessibility (EM_REPLACESEL / UIA)
    I-->>W: ok
```

## 6. Class diagram

```mermaid
classDiagram
    class STTEngine {
        <<abstract>>
        +name: str
        +is_cloud: bool
        +load()
        +transcribe(clip, language, prompt) Transcript
        +close()
    }
    STTEngine <|-- FasterWhisperEngine
    STTEngine <|-- WhisperCppEngine
    STTEngine <|-- WindowsSpeechEngine
    STTEngine <|-- CloudWhisperEngine
    class SttChain {
        +from_settings(cfg, ...) SttChain
        +warm_up()
        +transcribe(clip) SttOutcome
        +status()
    }
    SttChain o-- STTEngine

    class LLMProvider {
        <<abstract>>
        +name: str
        +is_cloud: bool
        +rewrite(transcript, mode, ctx, share_context, timeout, on_delta) RewriteResult
        +health_check() bool
    }
    LLMProvider <|-- AnthropicProvider
    LLMProvider <|-- OpenAICompatibleProvider
    OpenAICompatibleProvider <|-- AzureOpenAIProvider
    LLMProvider <|-- OfflineRewriter
    class ProviderChain {
        +rewrite(...) ChainOutcome
        +status
    }
    ProviderChain o-- LLMProvider

    class Pipeline {
        +run(clip, ctx, mode_override, command, callbacks) DictationResult
    }
    Pipeline --> SttChain
    Pipeline --> ProviderChain

    class InjectionMethod {
        <<abstract>>
        +name: str
        +available(ctx) bool
        +insert(text, ctx, replace_selection) None
    }
    InjectionMethod <|-- PasteMethod
    InjectionMethod <|-- ClipboardOnlyMethod
    InjectionMethod <|-- AccessibilityMethod
    InjectionMethod <|-- KeyboardMethod
    class Injector {
        +insert(text, ctx, replace_selection) InsertReport
        +copy_selection() str
    }
    Injector o-- InjectionMethod
    Injector --> InjectionPolicy

    class HotkeyStateMachine {
        +on_key(vk, down, t_ms) list~Action~
    }
    class HotkeyService {
        +start()
        +stop()
        signals started, stopped, cancelled, toggled_always_listening
    }
    HotkeyService --> HotkeyStateMachine

    class Controller {
        +start()
        +shutdown()
    }
    Controller --> HotkeyService
    Controller --> AudioCapture
    Controller --> Pipeline
    Controller --> Injector
    Controller --> Overlay
    Controller --> History
    Controller --> CredentialStore
```

## 7. Threads

| Thread | Owns | Rule |
|---|---|---|
| Qt main | UI, Controller, signals | Never blocks on I/O |
| Hotkey | `SetWindowsHookEx` + `GetMessage` loop | Callback returns in < 1 ms; only runs the state machine and posts Qt signals |
| Audio | PortAudio callback | Copies frames into a ring buffer, computes level, runs VAD; nothing else |
| Worker (1, `ThreadPoolExecutor(max_workers=1)`) | STT, AI, injection | One dictation at a time, serialised |
| Warm-up (startup) | Model load, provider health checks | Never delays the tray appearing |

## 8. Data and file locations

| Item | Installed / single exe | Portable (`portable` file next to exe) |
|---|---|---|
| Settings | `%APPDATA%\Sayso\settings.json` | `.\data\config\settings.json` |
| Policy (IT, read-only) | `.\policy.json` next to exe, else `%PROGRAMDATA%\Sayso\policy.json` | same |
| Models | `%LOCALAPPDATA%\Sayso\models` | `.\data\models` (or `.\models` bundled) |
| History | `%LOCALAPPDATA%\Sayso\history.sqlite3` | `.\data\history.sqlite3` |
| Logs (no dictated text) | `%LOCALAPPDATA%\Sayso\logs\sayso.log` | `.\data\logs\sayso.log` |
| Secrets | Windows Credential Manager (`Sayso/<ref>`) | DPAPI file `.\data\secrets.bin` (user+machine bound) |

## 9. Plugins

STT engines and AI providers register through Python entry points, so a separate wheel can add one without
changing Sayso:

```toml
[project.entry-points."sayso.stt"]
azure_speech = "sayso_azure_speech:create"   # create(stt_settings, models_dir, secrets) -> STTEngine

[project.entry-points."sayso.llm"]
bedrock = "sayso_bedrock:BedrockProvider"     # BedrockProvider(name, provider_settings, api_key) -> LLMProvider
```

A plugin name is then used in `stt.engines` or as a provider `kind`. Frozen builds include only the plugins
listed in `packaging/pyinstaller/sayso.spec` `hiddenimports`.
