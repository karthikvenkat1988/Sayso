"""Writing modes exposed by the AI layer."""

from __future__ import annotations

from enum import StrEnum


class Mode(StrEnum):
    RAW_TRANSCRIPT = "raw_transcript"
    REWRITE_TEXT = "rewrite_text"
    PROFESSIONAL = "professional_mode"
    EMAIL = "email_mode"
    MEETING_NOTES = "meeting_notes_mode"
    CHAT = "chat_mode"
    # Internal: the utterance is an instruction applied to the selected text.
    COMMAND = "command_mode"

    @property
    def label(self) -> str:
        return MODE_LABELS[self]

    @property
    def needs_llm(self) -> bool:
        return self is not Mode.RAW_TRANSCRIPT


MODE_LABELS: dict[Mode, str] = {
    Mode.RAW_TRANSCRIPT: "Raw transcript",
    Mode.REWRITE_TEXT: "Clean rewrite",
    Mode.PROFESSIONAL: "Professional",
    Mode.EMAIL: "Email",
    Mode.MEETING_NOTES: "Meeting notes",
    Mode.CHAT: "Chat",
    Mode.COMMAND: "Edit selection",
}

USER_MODES: list[Mode] = [m for m in Mode if m is not Mode.COMMAND]
