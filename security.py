import sys
import os
import time
import threading
import ctypes
from ctypes import wintypes

def _detect_by_metadata() -> bool:
    FORBIDDEN_KEYWORDS = {
        "cheatengine", "x64dbg", "ollydbg", "ida", "ghidra", "windbg",
        "immunitydebugger", "processhacker", "procexp", "frida", "gdb", "radare",
        "scylla", "dnspy"
    }

    psapi = ctypes.windll.psapi
    kernel32 = ctypes.windll.kernel32
    version = ctypes.windll.version

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010

    pids = (wintypes.DWORD * 2048)()
    bytes_returned = wintypes.DWORD()
    
    if not psapi.EnumProcesses(ctypes.byref(pids), ctypes.sizeof(pids), ctypes.byref(bytes_returned)):
        return False

    num_pids = bytes_returned.value // ctypes.sizeof(wintypes.DWORD)

    for i in range(num_pids):
        pid = pids[i]
        if pid == 0:
            continue

        h_process = kernel32.OpenProcess(
            wintypes.DWORD(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ),
            False,
            pid
        )

        if not h_process:
            continue

        try:
            exe_path_buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if psapi.GetModuleFileNameExW(h_process, None, exe_path_buf, wintypes.MAX_PATH) == 0:
                continue
            
            exe_path = exe_path_buf.value
            if not exe_path:
                continue

            filename = os.path.basename(exe_path).lower()
            if any(name in filename for name in FORBIDDEN_KEYWORDS):
                return True

            info_size = version.GetFileVersionInfoSizeW(exe_path, None)
            if not info_size:
                continue

            info_buf = ctypes.create_string_buffer(info_size)
            if not version.GetFileVersionInfoW(exe_path, 0, info_size, info_buf):
                continue
            
            lp_buffer = ctypes.c_void_p()
            lp_len = wintypes.UINT()
            if not version.VerQueryValueW(info_buf, "\\VarFileInfo\\Translation", ctypes.byref(lp_buffer), ctypes.byref(lp_len)):
                continue
            if lp_len.value < 4 or not lp_buffer.value:
                continue

            trans_ptr = ctypes.cast(lp_buffer.value, ctypes.POINTER(ctypes.c_ushort))
            lang = int(trans_ptr[0])
            codepage = int(trans_ptr[1])
            lang_codepage = f"{lang:04x}{codepage:04x}"

            PROPERTIES = ["OriginalFilename", "FileDescription", "ProductName", "InternalName"]
            for prop in PROPERTIES:
                query = f"\\StringFileInfo\\{lang_codepage}\\{prop}"
                prop_buffer = ctypes.c_void_p()
                prop_len = wintypes.UINT()
                if version.VerQueryValueW(info_buf, query, ctypes.byref(prop_buffer), ctypes.byref(prop_len)) and prop_buffer.value:
                    prop_value = ctypes.wstring_at(prop_buffer.value).lower()
                    if any(name in prop_value for name in FORBIDDEN_KEYWORDS):
                        return True

        finally:
            kernel32.CloseHandle(h_process)
            
    return False

def _detect_suspicious_windows() -> bool:
    try:
        user32 = ctypes.windll.user32
        titles = []
        suspicious = (
            "cheat engine", "x64dbg", "ollydbg", "ida", "windbg", "immunity debugger",
            "process hacker", "process explorer", "frida", "ghidra",
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
            "dbghelp.dll", "dbgcore.dll", "frida", "procexp64.exe", "scylla",
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

    if _detect_by_metadata():
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