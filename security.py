import sys
import os
import time
import subprocess
import threading
import ctypes
from ctypes import wintypes

def _detect_forbidden_processes() -> bool:
    try:
        out = subprocess.check_output(
            ["tasklist"], creationflags=0x08000000, stderr=subprocess.DEVNULL
        ).decode().lower()
        for name in (
            "cheatengine",
            "x64dbg",
            "ollydbg",
            "ida",
            "ghidra",
            "windbg",
            "immunitydebugger",
            "processhacker",
            "procexp",
            "frida",
            "gdb",
            "radare",
        ):
            if name in out:
                return True
    except Exception:
        pass
    return False

def _detect_suspicious_windows() -> bool:
    try:
        user32 = ctypes.windll.user32
        titles = []
        suspicious = (
            "cheat engine",
            "x64dbg",
            "ollydbg",
            "ida",
            "windbg",
            "immunity debugger",
            "process hacker",
            "process explorer",
            "frida",
            "ghidra",
        )

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd, lparam):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            title = buf.value.lower()
            for name in suspicious:
                if name in title:
                    titles.append(title)
                    return False
            return True

        user32.EnumWindows(enum_cb, 0)
        return bool(titles)
    except Exception:
        return False

def _detect_suspicious_modules() -> bool:
    try:
        kernel32 = ctypes.windll.kernel32
        for mod in (
            "dbghelp.dll",
            "dbgcore.dll",
            "frida",
            "procexp64.exe",
            "scylla",
        ):
            if kernel32.GetModuleHandleW(mod):
                return True
    except Exception:
        pass
    return False

def _nt_debug_checks() -> bool:
    try:
        ntdll = ctypes.windll.ntdll
        kernel32 = ctypes.windll.kernel32
        process = kernel32.GetCurrentProcess()

        debug_port = ctypes.c_ulong()
        if (
            ntdll.NtQueryInformationProcess(process, 7, ctypes.byref(debug_port), ctypes.sizeof(debug_port), None) == 0
            and debug_port.value != 0
        ):
            return True

        debug_object = ctypes.c_void_p()
        if (
            ntdll.NtQueryInformationProcess(process, 30, ctypes.byref(debug_object), ctypes.sizeof(debug_object), None) == 0
            and debug_object.value
        ):
            return True

        debug_flags = ctypes.c_ulong()
        if (
            ntdll.NtQueryInformationProcess(process, 31, ctypes.byref(debug_flags), ctypes.sizeof(debug_flags), None) == 0
            and debug_flags.value == 0
        ):
            return True
    except Exception:
        pass
    return False

def _hide_from_debugger():
    try:
        ntdll = ctypes.windll.ntdll
        kernel32 = ctypes.windll.kernel32
        ThreadHideFromDebugger = 0x11
        ntdll.NtSetInformationThread(
            kernel32.GetCurrentThread(), ThreadHideFromDebugger, None, 0
        )
    except Exception:
        pass

def _anti_reverse_engineering_guard():
    if sys.gettrace() is not None:
        raise SystemExit()
    if os.environ.get("PYTHONINSPECT") or os.environ.get("PYTHONDEBUG"):
        raise SystemExit()
    if _detect_forbidden_processes():
        raise SystemExit()
    if _detect_suspicious_windows() or _detect_suspicious_modules():
        raise SystemExit()
    try:
        kernel32 = ctypes.windll.kernel32
        if kernel32.IsDebuggerPresent():
            raise SystemExit()
        is_remote = ctypes.c_uint()
        kernel32.CheckRemoteDebuggerPresent(
            kernel32.GetCurrentProcess(), ctypes.byref(is_remote)
        )
        if is_remote.value:
            raise SystemExit()
        if _nt_debug_checks():
            raise SystemExit()
    except Exception:
        pass

def _guard_thread_loop():
    _hide_from_debugger()
    while True:
        try:
            _anti_reverse_engineering_guard()
        except SystemExit:
            os._exit(1)
        time.sleep(1)

def start_security_guard():
    _hide_from_debugger()
    _anti_reverse_engineering_guard()
    threading.Thread(target=_guard_thread_loop, daemon=True).start()