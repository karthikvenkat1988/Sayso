"""Every ctypes declaration for the Win32 calls Sayso makes. This module imports cleanly on any OS; the DLLs
are only loaded, lazily, the first time a function is used on Windows."""

from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes as wt
from functools import cache

IS_WINDOWS = sys.platform == "win32"

# Marks every input event Sayso injects so its own keyboard hook can ignore it.
SAYSO_TAG = 0x5A7505


class PlatformUnavailable(RuntimeError):
    """A Windows-only facility was used on another OS."""


# ---------------------------------------------------------------- constants

WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
WM_QUIT, WM_TIMER, WM_HOTKEY = 0x0012, 0x0113, 0x0312
WM_GETTEXT, WM_GETTEXTLENGTH = 0x000D, 0x000E
EM_GETSEL, EM_REPLACESEL = 0x00B0, 0x00C2
LLKHF_INJECTED = 0x10
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
INPUT_KEYBOARD = 1
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
SMTO_ABORTIFHUNG = 0x2
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x20, 0x80, 0x80000, 0x08000000
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x2
ERROR_ALREADY_EXISTS = 183
SM_REMOTESESSION = 0x1000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY, TOKEN_ELEVATION = 0x8, 20
CRED_TYPE_GENERIC, CRED_PERSIST_LOCAL_MACHINE = 1, 2
WAIT_OBJECT_0 = 0
VK_BACK, VK_TAB, VK_RETURN, VK_SHIFT, VK_CONTROL, VK_MENU = 0x08, 0x09, 0x0D, 0x10, 0x11, 0x12
VK_CAPITAL, VK_LWIN, VK_RWIN, VK_V, VK_C = 0x14, 0x5B, 0x5C, 0x56, 0x43
VK_DUMMY = 0xE8  # unassigned; pressed between Alt-down and Alt-up so Windows does not open the menu bar

# ---------------------------------------------------------------- structures

ULONG_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    # MOUSEINPUT is the largest member; including it sizes INPUT correctly (40 bytes on 64-bit).
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD), ("hwndActive", wt.HWND), ("hwndFocus", wt.HWND),
                ("hwndCapture", wt.HWND), ("hwndMenuOwner", wt.HWND), ("hwndMoveSize", wt.HWND),
                ("hwndCaret", wt.HWND), ("rcCaret", wt.RECT)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wt.HWND), ("message", wt.UINT), ("wParam", wt.WPARAM), ("lParam", wt.LPARAM),
                ("time", wt.DWORD), ("pt", wt.POINT)]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class CREDENTIALW(ctypes.Structure):
    _fields_ = [("Flags", wt.DWORD), ("Type", wt.DWORD), ("TargetName", wt.LPWSTR), ("Comment", wt.LPWSTR),
                ("LastWritten", wt.FILETIME), ("CredentialBlobSize", wt.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wt.DWORD),
                ("AttributeCount", wt.DWORD), ("Attributes", ctypes.c_void_p), ("TargetAlias", wt.LPWSTR),
                ("UserName", wt.LPWSTR)]


class TOKEN_ELEVATION_T(ctypes.Structure):
    _fields_ = [("TokenIsElevated", wt.DWORD)]


_FUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
HOOKPROC = _FUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)

# ---------------------------------------------------------------- DLL loading

_P = ctypes.POINTER
_SIGNATURES: dict[str, dict[str, tuple[object, list[object]]]] = {
    "user32": {
        "SetWindowsHookExW": (wt.HHOOK, [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]),
        "UnhookWindowsHookEx": (wt.BOOL, [wt.HHOOK]),
        "CallNextHookEx": (LRESULT, [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]),
        "GetMessageW": (wt.BOOL, [_P(MSG), wt.HWND, wt.UINT, wt.UINT]),
        "PostThreadMessageW": (wt.BOOL, [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]),
        "SetTimer": (ctypes.c_size_t, [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p]),
        "RegisterHotKey": (wt.BOOL, [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]),
        "UnregisterHotKey": (wt.BOOL, [wt.HWND, ctypes.c_int]),
        "SendInput": (wt.UINT, [wt.UINT, _P(INPUT), ctypes.c_int]),
        "GetAsyncKeyState": (ctypes.c_short, [ctypes.c_int]),
        "GetKeyState": (ctypes.c_short, [ctypes.c_int]),
        "GetLastInputInfo": (wt.BOOL, [_P(LASTINPUTINFO)]),
        "GetForegroundWindow": (wt.HWND, []),
        "SetForegroundWindow": (wt.BOOL, [wt.HWND]),
        "GetWindowTextW": (ctypes.c_int, [wt.HWND, wt.LPWSTR, ctypes.c_int]),
        "GetClassNameW": (ctypes.c_int, [wt.HWND, wt.LPWSTR, ctypes.c_int]),
        "GetWindowThreadProcessId": (wt.DWORD, [wt.HWND, _P(wt.DWORD)]),
        "GetGUIThreadInfo": (wt.BOOL, [wt.DWORD, _P(GUITHREADINFO)]),
        "SendMessageTimeoutW": (LRESULT, [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT, _P(ctypes.c_size_t)]),
        "OpenClipboard": (wt.BOOL, [wt.HWND]),
        "CloseClipboard": (wt.BOOL, []),
        "EmptyClipboard": (wt.BOOL, []),
        "GetClipboardData": (wt.HANDLE, [wt.UINT]),
        "SetClipboardData": (wt.HANDLE, [wt.UINT, wt.HANDLE]),
        "EnumClipboardFormats": (wt.UINT, [wt.UINT]),
        "RegisterClipboardFormatW": (wt.UINT, [wt.LPCWSTR]),
        "GetClipboardSequenceNumber": (wt.DWORD, []),
        "GetWindowLongPtrW": (ctypes.c_ssize_t, [wt.HWND, ctypes.c_int]),
        "SetWindowLongPtrW": (ctypes.c_ssize_t, [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]),
        "GetSystemMetrics": (ctypes.c_int, [ctypes.c_int]),
    },
    "kernel32": {
        "GetCurrentThreadId": (wt.DWORD, []),
        "GetModuleHandleW": (wt.HMODULE, [wt.LPCWSTR]),
        "GetTickCount": (wt.DWORD, []),
        "OpenProcess": (wt.HANDLE, [wt.DWORD, wt.BOOL, wt.DWORD]),
        "QueryFullProcessImageNameW": (wt.BOOL, [wt.HANDLE, wt.DWORD, wt.LPWSTR, _P(wt.DWORD)]),
        "GlobalAlloc": (wt.HANDLE, [wt.UINT, ctypes.c_size_t]),
        "GlobalLock": (ctypes.c_void_p, [wt.HANDLE]),
        "GlobalUnlock": (wt.BOOL, [wt.HANDLE]),
        "GlobalSize": (ctypes.c_size_t, [wt.HANDLE]),
        "GlobalFree": (wt.HANDLE, [wt.HANDLE]),
        "LocalFree": (wt.HANDLE, [wt.HANDLE]),
        "CloseHandle": (wt.BOOL, [wt.HANDLE]),
        "CreateMutexW": (wt.HANDLE, [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]),
        "CreateEventW": (wt.HANDLE, [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]),
        "OpenEventW": (wt.HANDLE, [wt.DWORD, wt.BOOL, wt.LPCWSTR]),
        "SetEvent": (wt.BOOL, [wt.HANDLE]),
        "WaitForSingleObject": (wt.DWORD, [wt.HANDLE, wt.DWORD]),
        "GetLastError": (wt.DWORD, []),
    },
    "advapi32": {
        "CredWriteW": (wt.BOOL, [_P(CREDENTIALW), wt.DWORD]),
        "CredReadW": (wt.BOOL, [wt.LPCWSTR, wt.DWORD, wt.DWORD, _P(_P(CREDENTIALW))]),
        "CredDeleteW": (wt.BOOL, [wt.LPCWSTR, wt.DWORD, wt.DWORD]),
        "CredFree": (None, [ctypes.c_void_p]),
        "OpenProcessToken": (wt.BOOL, [wt.HANDLE, wt.DWORD, _P(wt.HANDLE)]),
        "GetTokenInformation": (wt.BOOL, [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, _P(wt.DWORD)]),
    },
    "crypt32": {
        "CryptProtectData": (wt.BOOL, [_P(DATA_BLOB), wt.LPCWSTR, _P(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
                                       wt.DWORD, _P(DATA_BLOB)]),
        "CryptUnprotectData": (wt.BOOL, [_P(DATA_BLOB), ctypes.c_void_p, _P(DATA_BLOB), ctypes.c_void_p,
                                         ctypes.c_void_p, wt.DWORD, _P(DATA_BLOB)]),
    },
    "dwmapi": {
        "DwmSetWindowAttribute": (ctypes.c_long, [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]),
    },
}
_load_lock = threading.Lock()


@cache
def _dll(name: str):
    if not IS_WINDOWS:
        raise PlatformUnavailable(f"{name}.dll is only available on Windows")
    with _load_lock:
        lib = ctypes.WinDLL(name, use_last_error=True)
        for fn, (restype, argtypes) in _SIGNATURES.get(name, {}).items():
            f = getattr(lib, fn)
            f.restype, f.argtypes = restype, argtypes
        return lib


def user32():
    return _dll("user32")


def kernel32():
    return _dll("kernel32")


def advapi32():
    return _dll("advapi32")


def crypt32():
    return _dll("crypt32")


def dwmapi():
    return _dll("dwmapi")


def last_error() -> int:
    return ctypes.get_last_error() if IS_WINDOWS else 0


# ---------------------------------------------------------------- small helpers

def send_key_events(events: list[tuple[int, bool]]) -> int:
    """Sends tagged virtual-key events; each item is (vk, is_key_up). Returns how many were accepted."""
    arr = (INPUT * len(events))()
    for i, (vk, up) in enumerate(events):
        arr[i].type = INPUT_KEYBOARD
        arr[i].ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, SAYSO_TAG)
    return int(user32().SendInput(len(events), arr, ctypes.sizeof(INPUT)))


def send_unicode(text: str) -> int:
    """Types text as Unicode key events (surrogate pairs for characters outside the BMP)."""
    units = []
    raw = text.encode("utf-16-le")
    for i in range(0, len(raw), 2):
        units.append(int.from_bytes(raw[i:i + 2], "little"))
    arr = (INPUT * (len(units) * 2))()
    for i, u in enumerate(units):
        for j, flags in enumerate((KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)):
            item = arr[i * 2 + j]
            item.type = INPUT_KEYBOARD
            item.ki = KEYBDINPUT(0, u, flags, 0, SAYSO_TAG)
    return int(user32().SendInput(len(arr), arr, ctypes.sizeof(INPUT))) if units else 0


def is_key_down(vk: int) -> bool:
    return bool(user32().GetAsyncKeyState(vk) & 0x8000)


def window_text(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32().GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32().GetClassNameW(hwnd, buf, len(buf))
    return buf.value


def process_id_and_thread(hwnd: int) -> tuple[int, int]:
    pid = wt.DWORD(0)
    tid = user32().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value), int(tid)


def process_image_name(pid: int) -> str:
    """Executable name without extension, or "" when the process cannot be opened."""
    h = kernel32().OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(buf))
        if not kernel32().QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value.replace("/", "\\").rsplit("\\", 1)[-1].rsplit(".", 1)[0]
    finally:
        kernel32().CloseHandle(h)


def process_elevated(pid: int) -> bool | None:
    """True/False, or None when the answer cannot be determined (treated as elevated by callers: access
    denied to a process we could normally open means it runs at a higher integrity level)."""
    k, a = kernel32(), advapi32()
    h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        token = wt.HANDLE()
        if not a.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            info, ret = TOKEN_ELEVATION_T(), wt.DWORD()
            if not a.GetTokenInformation(token, TOKEN_ELEVATION, ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(ret)):
                return None
            return bool(info.TokenIsElevated)
        finally:
            k.CloseHandle(token)
    finally:
        k.CloseHandle(h)


def global_alloc(data: bytes) -> int:
    k = kernel32()
    h = k.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h:
        raise MemoryError("GlobalAlloc failed")
    ptr = k.GlobalLock(h)
    ctypes.memmove(ptr, data, len(data))
    k.GlobalUnlock(h)
    return h


def global_read(handle: int) -> bytes:
    k = kernel32()
    size = k.GlobalSize(handle)
    ptr = k.GlobalLock(handle)
    if not ptr or not size:
        return b""
    try:
        return ctypes.string_at(ptr, size)
    finally:
        k.GlobalUnlock(handle)


def _blob(data: bytes) -> tuple[DATA_BLOB, object]:
    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return DATA_BLOB(len(data), ctypes.cast(buf, _P(ctypes.c_ubyte))), buf


def _take_blob(out: DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32().LocalFree(ctypes.cast(out.pbData, wt.HANDLE))


def dpapi_protect(data: bytes, entropy: bytes) -> bytes:
    src, keep1 = _blob(data)
    ent, keep2 = _blob(entropy)
    out = DATA_BLOB()
    if not crypt32().CryptProtectData(ctypes.byref(src), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out)):
        raise OSError(f"CryptProtectData failed ({last_error()})")
    del keep1, keep2
    return _take_blob(out)


def dpapi_unprotect(data: bytes, entropy: bytes) -> bytes:
    src, keep1 = _blob(data)
    ent, keep2 = _blob(entropy)
    out = DATA_BLOB()
    if not crypt32().CryptUnprotectData(ctypes.byref(src), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out)):
        raise OSError(f"CryptUnprotectData failed ({last_error()})")
    del keep1, keep2
    return _take_blob(out)


def cred_write(target: str, secret: bytes) -> None:
    blob = (ctypes.c_ubyte * len(secret)).from_buffer_copy(secret)
    cred = CREDENTIALW()
    cred.Type, cred.TargetName, cred.UserName = CRED_TYPE_GENERIC, target, "Sayso"
    cred.CredentialBlobSize, cred.CredentialBlob = len(secret), ctypes.cast(blob, _P(ctypes.c_ubyte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    if not advapi32().CredWriteW(ctypes.byref(cred), 0):
        raise OSError(f"CredWrite failed ({last_error()})")


def cred_read(target: str) -> bytes | None:
    ptr = _P(CREDENTIALW)()
    if not advapi32().CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)):
        return None
    try:
        c = ptr.contents
        return ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize) if c.CredentialBlobSize else b""
    finally:
        advapi32().CredFree(ptr)


def cred_delete(target: str) -> None:
    advapi32().CredDeleteW(target, CRED_TYPE_GENERIC, 0)
