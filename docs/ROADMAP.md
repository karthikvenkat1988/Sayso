# Roadmap

## MVP (this release)

Push to talk, toggle (including Caps Lock double-tap) and always-listening dictation; Faster Whisper, whisper.cpp,
Windows Speech and optional cloud transcription; Claude, OpenAI, Azure OpenAI, OpenRouter, Ollama, LM Studio, local
servers and an offline writer; four insertion methods chosen automatically per app; overlay with waveform, transcript
preview, confidence and latency; tray, settings and history; per-app writing styles, vocabulary and snippets;
enterprise policy file; portable, one-file, installer, corporate and zipapp builds; CI and release automation.

## Beta

* Streaming transcription with partial text in the overlay while speaking
* Per-app learned vocabulary from corrections
* Voice commands ("press enter", "select last sentence", "undo that")
* Outlook and Teams context through UI Automation (thread subject, recipient names)
* Signed builds
* Encrypted history (DPAPI-wrapped SQLCipher key)

## v1.0

* Windows.Media.SpeechRecognition (WinRT) engine
* GPU builds (CUDA, DirectML)
* Admin console that generates `policy.json`
* Per-user MSIX package
* Multilingual auto-detect and translation mode
* Accessibility review: screen-reader announcements, high-contrast theme

## v2.0

* Team dictionaries and style guides synced from a company endpoint
* Bundled on-device small LLM (1–3B quantised through llama.cpp) for fully offline rewriting quality
* macOS port of the `winsys` and `ui` layers
* Meeting capture mode that produces notes from long recordings
