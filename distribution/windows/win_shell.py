import ctypes
from ctypes import wintypes


kernel = ctypes.WinDLL("kernel32", use_last_error=True)
user = ctypes.WinDLL("user32", use_last_error=True)
shell = ctypes.WinDLL("shell32", use_last_error=True)
kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel.CreateMutexW.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
kernel.CreateJobObjectW.restype = wintypes.HANDLE
kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel.GetModuleHandleW.restype = wintypes.HMODULE


class JobLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]


class IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in
                ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", JobLimits), ("io", IoCounters), ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]


class ProcessGroup:
    def __init__(self):
        self.handle = kernel.CreateJobObjectW(None, None)
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000
        if not self.handle or not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def add(self, process):
        if not kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            process.terminate()
            process.wait(timeout=10)
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            kernel.CloseHandle(self.handle)
            self.handle = None


def acquire_instance():
    handle = kernel.CreateMutexW(None, False, "Local\\Michelin.PlanningScheduling")
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle, ctypes.get_last_error() != 183


def alert(message):
    user.MessageBoxW(None, message, "Planning & Scheduling", 0x10)


WindowProcedure = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WindowClass(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("procedure", WindowProcedure), ("class_extra", ctypes.c_int),
                ("window_extra", ctypes.c_int), ("instance", wintypes.HINSTANCE), ("icon", wintypes.HICON),
                ("cursor", wintypes.HANDLE), ("background", wintypes.HBRUSH),
                ("menu_name", wintypes.LPCWSTR), ("class_name", wintypes.LPCWSTR)]


class NotifyIcon(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("window", wintypes.HWND), ("identifier", wintypes.UINT),
                ("flags", wintypes.UINT), ("message", wintypes.UINT), ("icon", wintypes.HICON),
                ("tip", wintypes.WCHAR * 128), ("state", wintypes.DWORD), ("state_mask", wintypes.DWORD),
                ("info", wintypes.WCHAR * 256), ("timeout", wintypes.UINT),
                ("info_title", wintypes.WCHAR * 64), ("info_flags", wintypes.DWORD),
                ("guid", ctypes.c_byte * 16), ("balloon_icon", wintypes.HICON)]


user.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user.DefWindowProcW.restype = ctypes.c_ssize_t
user.RegisterClassW.argtypes = [ctypes.POINTER(WindowClass)]
user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                               ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                               wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
user.CreateWindowExW.restype = wintypes.HWND
user.CreatePopupMenu.restype = wintypes.HMENU
user.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
user.DestroyMenu.argtypes = [wintypes.HMENU]
user.SetForegroundWindow.argtypes = [wintypes.HWND]
user.DestroyWindow.argtypes = [wintypes.HWND]
user.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user.LoadImageW.restype = wintypes.HANDLE
user.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
shell.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NotifyIcon)]


def run_tray(executable, open_app, authenticate, open_logs, services_alive):
    @WindowProcedure
    def procedure(window, message, word, detail):
        if message == 0x8001:
            if detail == 0x202:
                open_app()
            elif detail == 0x205:
                menu = user.CreatePopupMenu()
                for identifier, label in ((1, "Abrir Planning & Scheduling"), (2, "Autenticar BMA"),
                                          (3, "Abrir logs"), (4, "Encerrar")):
                    user.AppendMenuW(menu, 0, identifier, label)
                point = wintypes.POINT()
                user.GetCursorPos(ctypes.byref(point))
                user.SetForegroundWindow(window)
                selected = user.TrackPopupMenu(menu, 0x100 | 0x2, point.x, point.y, 0, window, None)
                user.DestroyMenu(menu)
                if selected == 1:
                    open_app()
                elif selected == 2:
                    authenticate()
                elif selected == 3:
                    open_logs()
                elif selected == 4:
                    user.DestroyWindow(window)
            return 0
        if message == 0x113 and not services_alive():
            alert("Um servico local foi interrompido. Reabra o aplicativo. Consulte os logs se persistir.")
            user.DestroyWindow(window)
            return 0
        if message == 2:
            user.PostQuitMessage(0)
            return 0
        return user.DefWindowProcW(window, message, word, detail)

    instance = kernel.GetModuleHandleW(None)
    window_class = WindowClass()
    window_class.procedure = procedure
    window_class.instance = instance
    window_class.class_name = "MichelinPlanningSchedulingTray"
    if not user.RegisterClassW(ctypes.byref(window_class)):
        raise ctypes.WinError(ctypes.get_last_error())
    window = user.CreateWindowExW(0, window_class.class_name, "Planning & Scheduling", 0,
                                 0, 0, 0, 0, None, None, instance, None)
    if not window:
        raise ctypes.WinError(ctypes.get_last_error())
    notification = NotifyIcon()
    notification.size = ctypes.sizeof(notification)
    notification.window = window
    notification.identifier = 1
    notification.flags = 1 | 2 | 4
    notification.message = 0x8001
    notification.tip = "MICHELIN - Planning & Scheduling"
    notification.icon = user.LoadImageW(None, str(executable), 1, 16, 16, 0x10)
    if not notification.icon:
        shell.ExtractIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT]
        shell.ExtractIconW.restype = wintypes.HICON
        notification.icon = shell.ExtractIconW(instance, str(executable), 0)
    if not shell.Shell_NotifyIconW(0, ctypes.byref(notification)):
        user.DestroyWindow(window)
        raise RuntimeError("Nao foi possivel criar o icone na bandeja.")
    user.SetTimer(window, 1, 2000, None)
    message = wintypes.MSG()
    try:
        while user.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user.TranslateMessage(ctypes.byref(message))
            user.DispatchMessageW(ctypes.byref(message))
    finally:
        shell.Shell_NotifyIconW(2, ctypes.byref(notification))