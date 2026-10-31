"""Typed settings, user overrides and the IT policy layer.

Precedence, lowest to highest: built-in defaults, the user's settings.json, policy.json.
Every key present in policy.json is locked: the UI shows it read-only and user edits to it are ignored.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
import types
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sayso.core.modes import Mode

log = logging.getLogger(__name__)


@dataclass
class GeneralSettings:
    default_mode: Mode = Mode.REWRITE_TEXT
    show_overlay: bool = True
    overlay_position: str = "bottom"  # bottom | top
    sounds: bool = True
    ui_language: str = "en"


@dataclass
class HotkeySettings:
    # Hold to talk; release to finish.
    push_to_talk: str = "ctrl+alt+space"
    # Press once to start, again to finish. "capslock*2" means double-tap Caps Lock.
    toggle: str = "capslock*2"
    # Turns continuous voice-activity dictation on or off.
    always_listening: str = "ctrl+alt+l"
    # Held together with push-to-talk: speak an instruction that edits the selected text.
    command_modifier: str = "shift"
    cancel: str = "esc"
    double_tap_ms: int = 350


@dataclass
class ActivationSettings:
    push_to_talk: bool = True
    toggle: bool = True
    always_listening_allowed: bool = True


@dataclass
class AudioSettings:
    device: str | None = None
    sample_rate: int = 16000
    # Energy VAD threshold in dBFS. Frames above it count as speech.
    vad_threshold_db: float = -42.0
    # Always-listening: silence that ends a segment.
    end_of_speech_ms: int = 700
    max_seconds: int = 300


@dataclass
class FasterWhisperSettings:
    model: str = "base.en"  # name (downloaded once) or a folder path to a CTranslate2 model
    device: str = "cpu"
    compute_type: str = "int8"
    beam_size: int = 1
    cpu_threads: int = 0


@dataclass
class WhisperCppSettings:
    # "server": a running whisper.cpp server; "cli": call whisper-cli.exe per utterance.
    mode: str = "cli"
    server_url: str = "http://127.0.0.1:8178"
    cli_path: str = "bin/whisper-cli.exe"
    model_path: str = "models/ggml-base.en.bin"
    threads: int = 4


@dataclass
class WindowsSpeechSettings:
    culture: str = "en-US"


@dataclass
class CloudSttSettings:
    base_url: str = "https://api.openai.com/v1"
    model: str = "whisper-1"
    api_key_ref: str = "stt.cloud"
    # Azure OpenAI: set kind="azure" and base_url to https://<res>.openai.azure.com/openai/deployments/<dep>
    kind: str = "openai"
    api_version: str = "2024-06-01"


@dataclass
class SttSettings:
    # Tried in order; the first engine that is available and succeeds wins.
    engines: list[str] = field(default_factory=lambda: ["faster_whisper", "whisper_cpp", "windows_speech"])
    language: str = "en"
    faster_whisper: FasterWhisperSettings = field(default_factory=FasterWhisperSettings)
    whisper_cpp: WhisperCppSettings = field(default_factory=WhisperCppSettings)
    windows_speech: WindowsSpeechSettings = field(default_factory=WindowsSpeechSettings)
    cloud: CloudSttSettings = field(default_factory=CloudSttSettings)


@dataclass
class ProviderSettings:
    # openai | azure | openrouter | ollama | lmstudio | local | anthropic | offline
    kind: str = "openai"
    base_url: str = ""
    model: str = ""
    api_key_ref: str = ""
    api_version: str = ""  # Azure only
    deployment: str = ""  # Azure only
    effort: str = ""  # Anthropic only
    extra_headers: dict[str, str] = field(default_factory=dict)


def _default_providers() -> dict[str, ProviderSettings]:
    return {
        "anthropic": ProviderSettings(
            kind="anthropic", model="claude-opus-5-5", api_key_ref="llm.anthropic", effort="low"
        ),
        "openai": ProviderSettings(
            kind="openai", base_url="https://api.openai.com/v1", model="gpt-4o-mini", api_key_ref="llm.openai"
        ),
        "azure": ProviderSettings(
            kind="azure",
            base_url="https://YOUR-RESOURCE.openai.azure.com",
            deployment="gpt-4o-mini",
            api_version="2024-06-01",
            api_key_ref="llm.azure",
        ),
        "openrouter": ProviderSettings(
            kind="openrouter",
            base_url="https://openrouter.ai/api/v1",
            model="anthropic/claude-sonnet-5.5",
            api_key_ref="llm.openrouter",
        ),
        "ollama": ProviderSettings(kind="ollama", base_url="http://127.0.0.1:11434/v1", model="llama3.2:3b"),
        "lmstudio": ProviderSettings(
            kind="lmstudio", base_url="http://127.0.0.1:1234/v1", model="local-model"
        ),
        "local": ProviderSettings(kind="local", base_url="http://127.0.0.1:8080/v1", model="local"),
        "offline": ProviderSettings(kind="offline"),
    }


@dataclass
class LlmSettings:
    # Tried in order. "offline" is the built-in rule-based rewriter and always succeeds.
    chain: list[str] = field(default_factory=lambda: ["anthropic", "ollama", "offline"])
    timeout_s: float = 6.0
    providers: dict[str, ProviderSettings] = field(default_factory=_default_providers)


@dataclass
class InjectionSettings:
    # auto | paste | clipboard | accessibility | keyboard
    method: str = "auto"
    restore_clipboard: bool = True
    paste_settle_ms: int = 150
    keyboard_chunk: int = 64
    # Per-process method, e.g. {"wfica32": "keyboard"}
    app_overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class AppProfile:
    processes: list[str] = field(default_factory=list)
    mode: Mode | None = None
    tone: str = ""


def _default_profiles() -> list[AppProfile]:
    return [
        AppProfile(["OUTLOOK", "olk"], Mode.EMAIL, "Business email."),
        AppProfile(["ms-teams", "Teams", "slack"], Mode.CHAT, "Workplace chat: brief and friendly."),
        AppProfile(["WINWORD", "POWERPNT"], Mode.PROFESSIONAL, "Clear document prose."),
        AppProfile(["ONENOTE"], Mode.MEETING_NOTES, ""),
        AppProfile(["EXCEL"], Mode.PROFESSIONAL, "Short spreadsheet comment."),
        AppProfile(
            ["Code", "devenv", "WindowsTerminal", "powershell", "cmd"],
            Mode.REWRITE_TEXT,
            "Technical. Keep identifiers, paths and commands verbatim.",
        ),
    ]


@dataclass
class PrivacySettings:
    history_enabled: bool = True
    history_retention_days: int = 30
    # Send window title and nearby text to the AI so it can match context.
    share_context: bool = True
    # Never call any network service. Local STT and local or offline rewriting only.
    offline_only: bool = False
    # Telemetry is not implemented; this flag exists so policy can assert it.
    telemetry: bool = False
    blocked_apps: list[str] = field(
        default_factory=lambda: ["KeePass", "KeePassXC", "1Password", "Bitwarden"]
    )
    # Dictation in these apps never goes to a cloud provider.
    no_cloud_apps: list[str] = field(default_factory=list)


@dataclass
class Settings:
    general: GeneralSettings = field(default_factory=GeneralSettings)
    hotkeys: HotkeySettings = field(default_factory=HotkeySettings)
    activation: ActivationSettings = field(default_factory=ActivationSettings)
    audio: AudioSettings = field(default_factory=AudioSettings)
    stt: SttSettings = field(default_factory=SttSettings)
    llm: LlmSettings = field(default_factory=LlmSettings)
    injection: InjectionSettings = field(default_factory=InjectionSettings)
    profiles: list[AppProfile] = field(default_factory=_default_profiles)
    privacy: PrivacySettings = field(default_factory=PrivacySettings)
    # Misheard word or phrase -> correct spelling.
    vocabulary: dict[str, str] = field(default_factory=dict)
    # Spoken trigger -> expansion.
    snippets: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Settings:
        return _from_dict(cls, data or {})


# ---------------------------------------------------------------- (de)serialisation


def _to_jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return {f.name: _to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Mode):
        return obj.value
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    return obj


def _convert(tp: Any, value: Any) -> Any:
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if value is None:
        return None
    if origin in (typing.Union, types.UnionType):
        inner = [a for a in args if a is not type(None)]
        return _convert(inner[0], value) if inner else value
    if dataclasses.is_dataclass(tp):
        return _from_dict(tp, value)
    if origin is list:
        return [_convert(args[0], v) for v in value] if args else list(value)
    if origin is dict:
        return {k: _convert(args[1], v) for k, v in value.items()} if args else dict(value)
    if tp is Mode:
        return Mode(value)
    if tp is float and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    if tp in (int, float, str, bool) and (
        not isinstance(value, tp) or (tp is not bool and isinstance(value, bool))
    ):
        raise TypeError(f"expected {tp.__name__}, got {type(value).__name__}")
    return value


def _from_dict(cls: type, data: dict[str, Any]) -> Any:
    hints = typing.get_type_hints(cls)
    defaults = cls()
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.name not in data:
            kwargs[f.name] = getattr(defaults, f.name)
            continue
        tp = hints[f.name]
        raw = data[f.name]
        try:
            if dataclasses.is_dataclass(tp) and isinstance(raw, dict):
                kwargs[f.name] = _from_dict(tp, raw)
            elif (
                typing.get_origin(tp) is dict
                and isinstance(raw, dict)
                and dataclasses.is_dataclass(typing.get_args(tp)[1])
            ):
                # Provider maps merge over defaults so a user can override one field of one provider.
                base = getattr(defaults, f.name)
                item_tp = typing.get_args(tp)[1]
                merged = {k: _to_jsonable(v) for k, v in base.items()}
                for k, v in raw.items():
                    merged[k] = deep_merge(merged.get(k, {}), v)
                kwargs[f.name] = {k: _from_dict(item_tp, v) for k, v in merged.items()}
            else:
                kwargs[f.name] = _convert(tp, raw)
        except (ValueError, TypeError, KeyError) as exc:
            log.warning("Ignoring invalid setting %s.%s=%r (%s)", cls.__name__, f.name, raw, exc)
            kwargs[f.name] = getattr(defaults, f.name)
    return cls(**kwargs)


# ---------------------------------------------------------------- policy


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        out = copy.deepcopy(base)
        for k, v in override.items():
            out[k] = deep_merge(out.get(k), v) if k in out else copy.deepcopy(v)
        return out
    return copy.deepcopy(override)


def flatten_keys(data: dict[str, Any], prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for k, v in data.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and v:
            keys |= flatten_keys(v, path)
        else:
            keys.add(path)
    return keys


@dataclass
class LoadedSettings:
    settings: Settings
    locked: set[str]
    policy_present: bool

    def is_locked(self, dotted: str) -> bool:
        return any(
            dotted == k or dotted.startswith(k + ".") or k.startswith(dotted + ".") for k in self.locked
        )


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError) as exc:
        log.error("Could not read %s: %s", path, exc)
        return None


def load_settings(settings_file: Path, policy_file: Path | None) -> LoadedSettings:
    user = _read_json(settings_file) or {}
    policy = (_read_json(policy_file) if policy_file else None) or {}
    policy.pop("$comment", None)
    merged = deep_merge(user, policy) if policy else user
    return LoadedSettings(Settings.from_dict(merged), flatten_keys(policy), bool(policy))


def save_settings(settings: Settings, settings_file: Path, locked: set[str] | None = None) -> None:
    """Writes user settings. Locked keys are dropped so a policy change later is not shadowed by stale values."""
    data = settings.to_dict()
    for key in locked or ():
        _pop_dotted(data, key)
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(settings_file)


def _pop_dotted(data: dict[str, Any], dotted: str) -> None:
    parts = dotted.split(".")
    cur: Any = data
    for p in parts[:-1]:
        if not isinstance(cur, dict) or p not in cur:
            return
        cur = cur[p]
    if isinstance(cur, dict):
        cur.pop(parts[-1], None)
