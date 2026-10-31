import pytest

from sayso.winsys.hotkey_logic import (
    VK_CAPITAL,
    VK_ESCAPE,
    VK_LCONTROL,
    VK_LMENU,
    VK_LSHIFT,
    VK_RCONTROL,
    VK_SPACE,
    Action,
    Chord,
    HotkeyStateMachine,
    name_for_vk,
    vk_for_name,
)

L_CTRL, L_ALT, SPACE, L_SHIFT = VK_LCONTROL, VK_LMENU, VK_SPACE, VK_LSHIFT
VK_L = ord("L")


def machine(ptt="ctrl+alt+space", toggle="capslock*2", always="ctrl+alt+l", command="shift", tap=350):
    p = lambda s: Chord.parse(s) if s else None  # noqa: E731
    return HotkeyStateMachine(
        p(ptt), p(toggle), p(always), vk_for_name(command) if command else None, VK_ESCAPE, tap
    )


class Keys:
    def __init__(self, m):
        self.m, self.t = m, 0

    def down(self, vk, dt=10, **kw):
        self.t += dt
        return self.m.on_key(vk, True, self.t, **kw)

    def up(self, vk, dt=10, **kw):
        self.t += dt
        return self.m.on_key(vk, False, self.t, **kw)


# ---- parsing


def test_parse_chords():
    c = Chord.parse("Ctrl+Alt+Space")
    assert c.keys == frozenset({0x11, 0x12, 0x20}) and not c.double_tap
    assert Chord.parse("capslock*2").double_tap
    assert Chord.parse("f9").keys == frozenset({0x78})
    assert Chord.parse("rctrl").keys == frozenset({VK_RCONTROL})
    assert str(Chord.parse("space+alt+ctrl")) == "ctrl+alt+space"
    assert str(Chord.parse("capslock*2")) == "capslock*2"


@pytest.mark.parametrize("bad", ["", "  ", "ctrl+banana", "ctrl+space*3", "ctrl+space*2", "+"])
def test_parse_errors_are_readable(bad):
    with pytest.raises(ValueError) as ei:
        Chord.parse(bad)
    assert str(ei.value)


def test_names_round_trip():
    assert name_for_vk(vk_for_name("f12")) == "f12"
    assert name_for_vk(0xFE).startswith("vk")


def test_generic_modifier_matches_left_or_right():
    c = Chord.parse("ctrl+space")
    assert c.satisfied({L_CTRL, SPACE}) and c.satisfied({VK_RCONTROL, SPACE}) and not c.satisfied({SPACE})


# ---- push to talk


def test_ptt_start_stop_and_space_swallowed():
    k = Keys(machine())
    assert k.down(L_CTRL).actions == [] and k.down(L_ALT).actions == []
    d = k.down(SPACE)
    assert d.actions == [Action.START_PTT] and d.swallow
    assert k.m.recording
    assert k.down(SPACE).swallow and k.down(SPACE).actions == []  # auto-repeat swallowed, no new action
    d = k.up(SPACE)
    assert d.actions == [Action.STOP] and d.swallow
    assert not k.m.recording
    assert not k.up(L_ALT).swallow


def test_ptt_releasing_modifier_first_stops_and_space_up_still_swallowed():
    k = Keys(machine())
    k.down(L_CTRL), k.down(L_ALT), k.down(SPACE)
    assert k.up(L_CTRL).actions == [Action.STOP]
    assert k.up(SPACE).swallow


def test_ptt_wrong_order_still_starts_when_complete():
    k = Keys(machine())
    k.down(SPACE)
    k.down(L_CTRL)
    assert k.down(L_ALT).actions == [Action.START_PTT]


def test_modifier_only_ptt_never_swallowed():
    k = Keys(machine(ptt="rctrl", toggle=None, always=None))
    d = k.down(VK_RCONTROL)
    assert d.actions == [Action.START_PTT] and not d.swallow
    d = k.up(VK_RCONTROL)
    assert d.actions == [Action.STOP] and not d.swallow


def test_command_modifier_with_ptt_and_while_recording():
    k = Keys(machine())
    k.down(L_SHIFT)
    k.down(L_CTRL), k.down(L_ALT)
    assert k.down(SPACE).actions == [Action.START_PTT, Action.COMMAND_ON]
    k2 = Keys(machine())
    k2.down(L_CTRL), k2.down(L_ALT), k2.down(SPACE)
    assert k2.down(L_SHIFT).actions == [Action.COMMAND_ON]
    assert k2.up(L_SHIFT).actions == []
    assert k2.down(L_SHIFT).actions == []  # only once per recording


# ---- toggle and double tap


def test_chord_toggle():
    k = Keys(machine(ptt=None, toggle="f9", always=None))
    assert k.down(0x78).actions == [Action.START_TOGGLE]
    k.up(0x78)
    assert k.m.recording
    assert k.down(0x78).actions == [Action.STOP]


def test_capslock_double_tap_toggles_and_swallows():
    k = Keys(machine())
    d = k.down(VK_CAPITAL)
    assert d.swallow and d.actions == []
    assert k.up(VK_CAPITAL).swallow
    d = k.down(VK_CAPITAL, dt=100)
    assert d.actions == [Action.START_TOGGLE] and d.swallow
    k.up(VK_CAPITAL)
    k.down(VK_CAPITAL, dt=500), k.up(VK_CAPITAL)
    assert k.down(VK_CAPITAL, dt=100).actions == [Action.STOP]


def test_single_tap_reinjects_capslock_via_tick():
    k = Keys(machine())
    k.down(VK_CAPITAL), k.up(VK_CAPITAL)
    assert k.m.tick(k.t + 100).actions == []
    assert k.m.tick(k.t + 400).actions == [Action.REINJECT_CAPSLOCK]
    assert k.m.tick(k.t + 900).actions == []


def test_single_tap_reinjects_on_next_event():
    k = Keys(machine())
    k.down(VK_CAPITAL), k.up(VK_CAPITAL)
    d = k.down(ord("A"), dt=600)
    assert d.actions == [Action.REINJECT_CAPSLOCK] and not d.swallow


def test_slow_second_tap_is_a_new_first_tap():
    k = Keys(machine())
    k.down(VK_CAPITAL), k.up(VK_CAPITAL)
    d = k.down(VK_CAPITAL, dt=800)
    assert d.actions == [Action.REINJECT_CAPSLOCK] and not k.m.recording


# ---- cancel, always, injected, repeat


def test_escape_cancels_recording_and_processing_but_is_not_swallowed():
    k = Keys(machine())
    assert k.down(VK_ESCAPE).actions == []  # idle: Esc is just Esc
    k.up(VK_ESCAPE)
    k.down(L_CTRL), k.down(L_ALT), k.down(SPACE)
    d = k.down(VK_ESCAPE)
    assert d.actions == [Action.CANCEL] and not d.swallow and not k.m.recording
    k.up(VK_ESCAPE)
    k.m.notify_processing(True)
    assert k.down(VK_ESCAPE).actions == [Action.CANCEL]


def test_always_listening_chord():
    k = Keys(machine())
    k.down(L_CTRL), k.down(L_ALT)
    d = k.down(VK_L)
    assert d.actions == [Action.TOGGLE_ALWAYS] and d.swallow
    assert k.up(VK_L).swallow


def test_always_chord_disabled_when_none():
    k = Keys(machine(always=None))
    k.down(L_CTRL), k.down(L_ALT)
    assert k.down(VK_L).actions == []


def test_injected_events_are_ignored():
    k = Keys(machine())
    k.down(L_CTRL), k.down(L_ALT)
    d = k.down(SPACE, injected=True)
    assert d.actions == [] and not d.swallow and not k.m.recording
    # an injected caps lock press (our re-inject) must not count as a tap
    k.down(VK_CAPITAL, injected=True)
    assert k.m.tick(10_000).actions == []


def test_force_idle_after_external_stop():
    k = Keys(machine())
    k.down(L_CTRL), k.down(L_ALT), k.down(SPACE)
    k.m.force_idle()
    assert not k.m.recording


# ---- lost key-ups (secure desktop)


def test_stale_modifiers_after_secure_desktop_do_not_start_ptt():
    # Ctrl+Alt+Del: the hook sees Ctrl and Alt go down, but the key-ups happen on the secure desktop.
    k = Keys(machine())
    k.down(L_CTRL), k.down(L_ALT)
    physically_down: set[int] = set()  # back on the desktop, nothing is held
    assert k.m.resync(physically_down.__contains__, except_vk=SPACE).actions == []
    d = k.down(SPACE)
    assert d.actions == [] and not d.swallow and not k.m.recording


def test_resync_keeps_held_and_swallowed_keys():
    k = Keys(machine())
    k.down(L_CTRL), k.down(L_ALT), k.down(SPACE)
    # Space was swallowed, so Windows reports it up even while it is held; Ctrl and Alt really are held.
    assert k.m.resync({L_CTRL, L_ALT}.__contains__).actions == []
    assert k.m.recording and k.up(SPACE).actions == [Action.STOP]


def test_resync_stops_ptt_when_a_chord_key_was_released_unseen():
    k = Keys(machine())
    k.down(L_CTRL), k.down(L_ALT), k.down(SPACE)
    assert k.m.resync({L_ALT}.__contains__).actions == [Action.STOP]
    assert not k.m.recording
