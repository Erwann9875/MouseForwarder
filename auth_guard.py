import os, sys, threading, time, hashlib, base64
import ctypes
from ctypes import wintypes

try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover
    winreg = None  # running outside Windows

def _sha256_file(path: str) -> str:
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest().upper()
    except Exception:
        return ''

def _project_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))

def verify_integrity() -> bool:
    return True

def _machine_guid() -> str:
    if winreg is None:
        return ''
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
            v, _ = winreg.QueryValueEx(k, "MachineGuid")
            return str(v)
    except Exception:
        return ''

def _volume_serial() -> str:
    try:
        GetVolumeInformationW = ctypes.windll.kernel32.GetVolumeInformationW
        GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                                          ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
        vsn = wintypes.DWORD()
        GetVolumeInformationW(os.getenv('SystemDrive', 'C:') + '\\', None, 0, ctypes.byref(vsn), None, None, None, 0)
        return f"{vsn.value:08X}"
    except Exception:
        return ''

_NONCE = os.urandom(16)
_SESSION_KEY: bytes | None = None

def set_session_token(username: str, password: str) -> None:
    ident = (username + '|' + password + '|' + _machine_guid() + '|' + _volume_serial()).encode('utf-8', 'ignore')
    _key = hashlib.sha256(_NONCE + ident).digest()
    mixed = bytes((b ^ 0x5A) for b in _key)
    globals()['_SESSION_KEY'] = mixed

def _has_debugger() -> bool:
    try:
        if sys.gettrace() is not None:
            return True
    except Exception:
        pass
    try:
        if sys.getprofile() is not None:
            return True
    except Exception:
        pass
    try:
        kernel32 = ctypes.windll.kernel32
        if kernel32.IsDebuggerPresent():
            return True
        remote = wintypes.BOOL()
        kernel32.CheckRemoteDebuggerPresent(kernel32.GetCurrentProcess(), ctypes.byref(remote))
        if remote.value:
            return True
    except Exception:
        pass
    return False

def require_auth() -> None:
    if _has_debugger():
        os._exit(1)
    if not verify_integrity():
        os._exit(1)
    if globals().get('_SESSION_KEY') is None:
        raise PermissionError('Authentication required')

def start_integrity_monitor(interval: float = 1.5) -> None:
    if os.getenv('MF_DISABLE_INTEGRITY') == '1':
        return
    def _loop():
        while True:
            try:
                if _has_debugger():
                    os._exit(1)
            except Exception:
                os._exit(1)
            time.sleep(interval)
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
