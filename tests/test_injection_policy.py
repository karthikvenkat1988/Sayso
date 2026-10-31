from sayso.winsys.injection_policy import TargetInfo, choose_methods, is_classic_edit


def T(**kw):
    return TargetInfo(**{"process": "notepad", "control_class": "Edit", "text_len": 20, **kw})


def test_elevated_target_is_clipboard_only():
    assert choose_methods(T(elevated_target=True), "paste", {"notepad": "keyboard"}) == ["clipboard"]


def test_process_override_wins_and_ends_with_clipboard():
    assert choose_methods(T(process="WFICA32.exe"), "auto", {"wfica32": "paste"}) == ["paste", "clipboard"]
    assert choose_methods(T(), "auto", {"Notepad.exe": "keyboard"}) == ["keyboard", "clipboard"]


def test_invalid_override_ignored():
    assert choose_methods(T(), "auto", {"notepad": "nonsense"})[0] == "paste"


def test_explicit_configured_method_then_fallbacks():
    assert choose_methods(T(), "keyboard", {}) == ["keyboard", "paste", "accessibility", "clipboard"]
    assert choose_methods(T(), "clipboard", {}) == ["clipboard"]


def test_remote_clients_prefer_keyboard():
    for proc in ("mstsc", "wfica32", "CDViewer", "vmconnect", "vmware-view", "msrdc"):
        assert choose_methods(T(process=proc), "auto", {}) == ["keyboard", "paste", "clipboard"]
    assert choose_methods(T(remote_session=True), "auto", {})[0] == "keyboard"


def test_terminals_prefer_paste_then_keyboard():
    for proc in ("WindowsTerminal", "conhost", "powershell", "pwsh", "cmd", "mintty", "putty"):
        assert choose_methods(T(process=proc), "auto", {}) == ["paste", "keyboard", "clipboard"]
    assert choose_methods(T(process="cmd", clipboard_ok=False), "auto", {}) == ["keyboard", "clipboard"]


def test_classic_edit_without_clipboard_uses_accessibility_first():
    assert choose_methods(T(control_class="RICHEDIT50W", clipboard_ok=False), "auto", {}) == [
        "accessibility",
        "keyboard",
        "clipboard",
    ]


def test_default_order():
    assert choose_methods(T(control_class="Chrome_RenderWidgetHostHWND"), "auto", {}) == [
        "paste",
        "keyboard",
        "clipboard",
    ]
    assert choose_methods(T(control_class="X", uia_ok=True), "auto", {}) == [
        "paste",
        "accessibility",
        "keyboard",
        "clipboard",
    ]
    assert choose_methods(T(), "auto", {}) == ["paste", "accessibility", "keyboard", "clipboard"]


def test_no_clipboard_and_long_text():
    assert choose_methods(T(control_class="X", clipboard_ok=False), "auto", {}) == ["keyboard", "clipboard"]
    assert choose_methods(T(control_class="X", text_len=5000), "auto", {}) == ["paste", "clipboard"]


def test_always_ends_with_clipboard_once():
    for kw in ({}, {"clipboard_ok": False}, {"uia_ok": True}, {"text_len": 9000}):
        m = choose_methods(T(**kw), "auto", {})
        assert m[-1] == "clipboard" and m.count("clipboard") == 1


def test_classic_edit_detection():
    assert is_classic_edit("Edit") and is_classic_edit("RichEdit20W") and not is_classic_edit("Chrome")
