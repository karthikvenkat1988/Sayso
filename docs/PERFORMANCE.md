# Performance

## Budget

| Stage | Target | How it is met |
|---|---|---|
| Voice detection | < 100 ms | microphone stream opened on key-down, 30 ms frames, energy VAD fires on the 2nd speech frame (60 ms), 300 ms pre-roll so nothing is clipped |
| Transcription (5 s of audio) | < 1 s | Faster Whisper `base.en`, int8, beam 1, model loaded at start-up, built-in VAD filter |
| Rewrite | < 2 s | Claude with effort `low`, cached system prompt, streamed; 6 s timeout then next provider; utterances of four words or fewer in `rewrite_text` skip the AI entirely |
| Insertion | < 100 ms | one clipboard write and one `SendInput`; the clipboard-restore delay happens after the paste is sent |
| Memory | < 500 MB | `base.en` int8 is about 150 MB; only Qt Essentials; one model loaded at a time |
| Idle CPU | < 1 % | no polling beyond a 50 ms hook-thread timer and the hook itself |

These are design targets measured on a 4-core laptop class CPU with a warm model; verify on your hardware with the
steps below. A cloud model can exceed the rewrite budget on a slow network, in which case the 6 s timeout bounds the wait.

## Reading the latency lines

Each dictation writes one line to `sayso.log`:

```
dictation mode=email_mode stt=faster_whisper(640ms) ai=anthropic(1180ms) chars=212
inserted via paste in 38 ms (tried [])
```

* `stt=` is time spent in the speech engine after you released the key.
* `ai=` is time in the writer (0 for raw transcripts and the short-utterance shortcut).
* `inserted via … in N ms` is insertion; `tried` lists methods that failed first.
* The overlay shows `stt + ai + insert` after "Inserted ·".

## Measuring

1. Quiet room, default microphone, `base.en`. Speak a five-second sentence ten times.
2. Take the median `stt=` and `ai=` values from the log; Tray › Diagnostics shows the engines in use.
3. Memory: Task Manager › Details › `Sayso.exe` private working set after the first dictation.
4. `Sayso.exe --transcribe sample.wav --mode email_mode` times the whole pipeline without the UI.

## Tuning

| Goal | Change |
|---|---|
| Faster transcription | `stt.faster_whisper.model` = `tiny.en`; raise `cpu_threads`; GPU builds are on the roadmap |
| Better accuracy | `small.en` or `large-v3-turbo` (more memory, slower) |
| Faster rewrite | local `ollama` model such as `llama3.2:3b`, or a nearer Azure region; lower `llm.timeout_s` |
| Lower memory | `tiny.en`, or whisper.cpp with `ggml-base.en.bin` |
