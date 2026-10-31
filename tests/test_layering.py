import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "sayso"
PURE = ["core", "stt", "llm"]
FORBIDDEN_PREFIXES = ("PySide6", "sayso.winsys", "sayso.ui", "sayso.audio")


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
            if node.module == "ctypes":
                for a in node.names:
                    yield f"ctypes.{a.name}"
        elif isinstance(node, ast.Attribute) and node.attr == "windll":
            yield "ctypes.windll"


def test_pure_layers_do_not_import_platform_code():
    offenders = []
    for pkg in PURE:
        for f in (SRC / pkg).rglob("*.py"):
            for mod in _imports(f):
                if mod.startswith(FORBIDDEN_PREFIXES) or mod == "ctypes.windll":
                    offenders.append(f"{f.relative_to(SRC)} imports {mod}")
    assert not offenders, offenders


def test_only_ui_imports_qt():
    offenders = []
    for f in SRC.rglob("*.py"):
        rel = f.relative_to(SRC)
        if rel.parts[0] == "ui" or rel.name in {"app.py"}:
            continue
        for mod in _imports(f):
            if mod.startswith("PySide6"):
                offenders.append(f"{rel} imports {mod}")
    # winsys hotkeys/service wrappers are the declared exception (they emit Qt signals).
    offenders = [o for o in offenders if not o.startswith("winsys/hotkeys.py")]
    assert not offenders, offenders
