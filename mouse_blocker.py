import ctypes
from ctypes import wintypes
from PySide6 import QtCore
from auth_guard import require_auth

user32 = ctypes.WinDLL("user32", use_last_error=True)
WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIDEV_INPUTSINK = 0x00000100
RIM_TYPEMOUSE = 0
WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
VK_ESCAPE = 0x1B
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_RBUTTONDBLCLK = 0x0206
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MBUTTONDBLCLK = 0x0209
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_XBUTTONDBLCLK = 0x020D
WM_MOUSEHWHEEL = 0x020E
XBUTTON1 = 0x0001
XBUTTON2 = 0x0002

try:
    HRAWINPUT = wintypes.HRAWINPUT
except AttributeError:
    HRAWINPUT = wintypes.HANDLE
UINT = getattr(wintypes, "UINT", ctypes.c_uint)

class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]

class RAWMOUSEBUTTONS(ctypes.Structure):
    _fields_ = [
        ("usButtonFlags", wintypes.USHORT),
        ("usButtonData", wintypes.USHORT),
    ]

class RAWMOUSEUNION(ctypes.Union):
    _fields_ = [
        ("ulButtons", wintypes.ULONG),
        ("buttons", RAWMOUSEBUTTONS),
    ]

class RAWMOUSE(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("u", RAWMOUSEUNION),
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInfo", wintypes.ULONG),
    ]

class RAWINPUTUNION(ctypes.Union):
    _fields_ = [("mouse", RAWMOUSE)]

class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("data", RAWINPUTUNION)]

class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]

class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]

GetRawInputData = user32.GetRawInputData
GetRawInputData.restype = UINT
GetRawInputData.argtypes = [HRAWINPUT, UINT, ctypes.c_void_p, ctypes.POINTER(UINT), UINT]
RegisterRawInputDevices = user32.RegisterRawInputDevices
RegisterRawInputDevices.restype = wintypes.BOOL
RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), UINT, UINT]

HHOOK = wintypes.HANDLE

if ctypes.sizeof(ctypes.c_void_p) == ctypes.sizeof(ctypes.c_long):
    WPARAM = ctypes.c_ulong
    LPARAM = ctypes.c_long
    LRESULT = ctypes.c_long
else:
    WPARAM = ctypes.c_ulonglong
    LPARAM = ctypes.c_longlong
    LRESULT = ctypes.c_longlong

HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)
SetWindowsHookEx = user32.SetWindowsHookExW
SetWindowsHookEx.restype = HHOOK
SetWindowsHookEx.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
CallNextHookEx = user32.CallNextHookEx
CallNextHookEx.restype = LRESULT
CallNextHookEx.argtypes = [HHOOK, ctypes.c_int, WPARAM, LPARAM]
UnhookWindowsHookEx = user32.UnhookWindowsHookEx
UnhookWindowsHookEx.restype = wintypes.BOOL
UnhookWindowsHookEx.argtypes = [HHOOK]

class MouseBlocker:
    def __init__(self):
        self._hook = None
        self._proc = None
        self._blocked = {
            'left', 'right', 'middle', 'back', 'forward', 'wheel'
        }

    def set_blocked(self, buttons: set[str]):
        self._blocked = set(buttons)

    def start(self):
        if self._hook:
            return

        def _callback(nCode, wParam, lParam):
            if nCode >= 0:
                if wParam == WM_MOUSEMOVE:
                    return 1
                btn = self._wparam_to_button(wParam, lParam)
                if btn and btn in self._blocked:
                    return 1
            return CallNextHookEx(self._hook, nCode, wParam, lParam)

        try:
            require_auth()
        except Exception:
            raise OSError("Authentication required to start mouse blocker")
        self._proc = HOOKPROC(_callback)
        self._hook = SetWindowsHookEx(WH_MOUSE_LL, self._proc, 0, 0)
        if not self._hook:
            err = ctypes.get_last_error()
            raise OSError(err, ctypes.FormatError(err))

    def stop(self):
        if self._hook:
            UnhookWindowsHookEx(self._hook)
            self._hook = None
            self._proc = None

    def _wparam_to_button(self, wParam, lParam):
        if wParam in (WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK):
            return 'left'
        if wParam in (WM_RBUTTONDOWN, WM_RBUTTONUP, WM_RBUTTONDBLCLK):
            return 'right'
        if wParam in (WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MBUTTONDBLCLK):
            return 'middle'
        if wParam in (WM_XBUTTONDOWN, WM_XBUTTONUP, WM_XBUTTONDBLCLK):
            info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            btn = (info.mouseData >> 16) & 0xffff
            return 'forward' if btn == XBUTTON2 else 'back'
        if wParam in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
            return 'wheel'
        return None

class EscapeListener:
    def __init__(self, on_escape):
        self.on_escape = on_escape
        self._hook = None
        self._proc = None

    def start(self):
        if self._hook:
            return

        def _callback(nCode, wParam, lParam):
            if nCode >= 0 and wParam == WM_KEYDOWN:
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if kb.vkCode == VK_ESCAPE:
                    self.on_escape()
                    return 1
            return CallNextHookEx(self._hook, nCode, wParam, lParam)

        self._proc = HOOKPROC(_callback)
        self._hook = SetWindowsHookEx(WH_KEYBOARD_LL, self._proc, 0, 0)
        if not self._hook:
            err = ctypes.get_last_error()
            raise OSError(err, ctypes.FormatError(err))

    def stop(self):
        if self._hook:
            UnhookWindowsHookEx(self._hook)
            self._hook = None
            self._proc = None

class RawInputFilter(QtCore.QAbstractNativeEventFilter):
    def __init__(self, hwnd: int, on_delta):
        super().__init__()
        self.hwnd = hwnd
        self.on_delta = on_delta
        self._registered = False
        self.register()

    def register(self):
        if self._registered:
            return
        try:
            require_auth()
        except Exception:
            return
        rid = RAWINPUTDEVICE()
        rid.usUsagePage = 0x01
        rid.usUsage = 0x02
        rid.dwFlags = RIDEV_INPUTSINK
        rid.hwndTarget = wintypes.HWND(self.hwnd)
        ok = RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE))
        self._registered = bool(ok)

    def nativeEventFilter(self, eventType, message):
        if eventType != b'windows_generic_MSG':
            return False, 0
        try:
            addr = int(message)
        except TypeError:
            addr = message.__int__()

        pmsg = ctypes.cast(ctypes.c_void_p(addr), ctypes.POINTER(wintypes.MSG))
        msg = pmsg.contents

        if msg.message == WM_INPUT:
            self._handle_wm_input(msg.lParam)
        return False, 0

    def _handle_wm_input(self, lparam):
        size = UINT(0)
        GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER))
        if size.value == 0:
            return
        buf = ctypes.create_string_buffer(size.value)
        got = GetRawInputData(lparam, RID_INPUT, buf, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER))
        if got == 0 or got == 0xFFFFFFFF:
            return
        ri = RAWINPUT.from_buffer_copy(buf)
        if ri.header.dwType != RIM_TYPEMOUSE:
            return
        dx = int(ri.data.mouse.lLastX)
        dy = int(ri.data.mouse.lLastY)
        if dx or dy:
            self.on_delta(dx, dy)
