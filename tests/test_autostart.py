from sayso.winsys import autostart


class FakeRegistry:
    HKEY_CURRENT_USER, KEY_SET_VALUE, KEY_READ, REG_SZ = 1, 2, 3, 4

    def __init__(self):
        self.values: dict[str, str] = {}

    def OpenKey(self, root, path, reserved, access):  # noqa: N802 - mirrors winreg
        reg = self

        class Key:
            def __enter__(self):
                return reg

            def __exit__(self, *exc):
                return False

        return Key()

    def SetValueEx(self, key, name, reserved, kind, value):  # noqa: N802
        self.values[name] = value

    def QueryValueEx(self, key, name):  # noqa: N802
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def DeleteValue(self, key, name):  # noqa: N802
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


def test_enable_disable_round_trip():
    reg = FakeRegistry()
    r = reg
    assert not autostart.is_enabled(r)
    autostart.enable('"C:\\Sayso\\Sayso.exe"', r)
    assert autostart.is_enabled(r) and reg.values["Sayso"] == '"C:\\Sayso\\Sayso.exe"'
    autostart.disable(r)
    autostart.disable(r)  # already gone: no error
    assert not autostart.is_enabled(r)


def test_frozen_build_starts_the_exe():
    assert autostart.launch_command(frozen=True, executable="C:\\S\\Sayso.exe") == '"C:\\S\\Sayso.exe"'


def test_source_run_starts_the_module_not_a_bare_interpreter(tmp_path):
    py = tmp_path / "python.exe"
    py.write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    cmd = autostart.launch_command(frozen=False, executable=str(py), argv0="-m")
    assert cmd == f'"{tmp_path / "pythonw.exe"}" -m sayso'


def test_zipapp_run_starts_the_pyz(tmp_path):
    py = tmp_path / "python.exe"
    cmd = autostart.launch_command(frozen=False, executable=str(py), argv0=str(tmp_path / "sayso.pyz"))
    assert cmd == f'"{py}" "{(tmp_path / "sayso.pyz").resolve()}"'
