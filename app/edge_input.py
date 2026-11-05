"""Shared cursor for Windows: when the mouse reaches a screen edge assigned to a device, mouse and keyboard
are captured and sent to that device until the cursor comes back across the same edge."""
import logging
import sys
import threading

logger = logging.getLogger(__name__)
AVAILABLE = sys.platform == 'win32'

# Virtual keys without text, as DOM key/code names for the DevTools protocol.
SPECIAL = {8: 'Backspace', 9: 'Tab', 13: 'Enter', 27: 'Escape', 32: ' ', 33: 'PageUp', 34: 'PageDown', 35: 'End', 36: 'Home',
           37: 'ArrowLeft', 38: 'ArrowUp', 39: 'ArrowRight', 40: 'ArrowDown', 45: 'Insert', 46: 'Delete', 20: 'CapsLock',
           16: 'Shift', 160: 'Shift', 161: 'Shift', 17: 'Control', 162: 'Control', 163: 'Control', 18: 'Alt', 164: 'Alt', 165: 'AltGraph',
           91: 'Meta', 92: 'Meta', 93: 'ContextMenu', **{111 + n: f'F{n}' for n in range(1, 13)}}
CODES = {8: 'Backspace', 9: 'Tab', 13: 'Enter', 27: 'Escape', 32: 'Space', 33: 'PageUp', 34: 'PageDown', 35: 'End', 36: 'Home',
         37: 'ArrowLeft', 38: 'ArrowUp', 39: 'ArrowRight', 40: 'ArrowDown', 45: 'Insert', 46: 'Delete', 20: 'CapsLock',
         160: 'ShiftLeft', 161: 'ShiftRight', 162: 'ControlLeft', 163: 'ControlRight', 164: 'AltLeft', 165: 'AltRight', 91: 'MetaLeft', 92: 'MetaRight',
         **{111 + n: f'F{n}' for n in range(1, 13)}, **{48 + n: f'Digit{n}' for n in range(10)}, **{65 + n: 'Key' + chr(65 + n) for n in range(26)}}
SHIFT, CONTROL, ALT, META = (16, 160, 161), (17, 162, 163), (18, 164, 165), (91, 92)

def leave_point(side, start, position, bounds):
    """Point on the PC edge where the cursor reappears after leaving a device."""
    left, top, right, bottom = bounds
    if side in ('left', 'right'):
        y = min(max(top + start + position, top), bottom - 1)
        return (left + 2 if side == 'left' else right - 3, int(y))
    x = min(max(left + start + position, left), right - 1)
    return (int(x), top + 2 if side == 'top' else bottom - 3)

def region_at(regions, x, y, bounds):
    """Region whose edge segment the cursor is touching, and the entry point on the device."""
    left, top, right, bottom = bounds
    for region in regions:
        side, start, width, height = region['side'], region['start'], region['width'], region['height']
        if side == 'right' and x >= right - 1 and start <= y - top < start + height:
            return region, (0, y - top - start)
        if side == 'left' and x <= left and start <= y - top < start + height:
            return region, (width - 1, y - top - start)
        if side == 'bottom' and y >= bottom - 1 and start <= x - left < start + width:
            return region, (x - left - start, 0)
        if side == 'top' and y <= top and start <= x - left < start + width:
            return region, (x - left - start, height - 1)
    return None, None

def crossed_back(side, x, y, width, height):
    return (side == 'right' and x < 0) or (side == 'left' and x >= width) or (side == 'bottom' and y < 0) or (side == 'top' and y >= height)

class EdgeInput:
    def __init__(self, emit):
        self.emit = emit  # Called from the hook thread; must return quickly.
        self.regions = []
        self.remote = None
        self.leave_requested = False
        self.keys = set()
        self.buttons = 0
        self.thread = None

    def bounds(self):
        if not AVAILABLE:
            return (0, 0, 1920, 1080)
        import ctypes
        metrics = ctypes.windll.user32.GetSystemMetrics
        left, top = metrics(76), metrics(77)
        return (left, top, left + metrics(78), top + metrics(79))

    def set_regions(self, regions):
        self.regions = list(regions)
        if self.remote and self.remote['device'] not in {region['device'] for region in self.regions}:
            self.leave_requested = True

    def leave(self, device=None):
        if self.remote and (device is None or self.remote['device'] == device):
            self.leave_requested = True

    def start(self):
        if AVAILABLE and self.thread is None:
            import ctypes
            # Physical pixels everywhere; otherwise scaled displays (125%, 150%) get mismatched coordinates.
            try:
                ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            except (AttributeError, OSError):
                try:
                    ctypes.windll.shcore.SetProcessDpiAwareness(2)
                except (AttributeError, OSError):
                    pass
            self.thread = threading.Thread(target=self._run, daemon=True, name='lua-edge-input')
            self.thread.start()

    def _run(self):
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        LRESULT = ctypes.c_ssize_t
        HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        class MSLL(ctypes.Structure):
            _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG), ('mouseData', wintypes.DWORD), ('flags', wintypes.DWORD), ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]
        class KBDLL(ctypes.Structure):
            _fields_ = [('vk', wintypes.DWORD), ('scan', wintypes.DWORD), ('flags', wintypes.DWORD), ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]
        user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.restype = LRESULT
        user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.CreateCursor.restype = wintypes.HANDLE
        user32.SetSystemCursor.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.c_void_p)
        user32.GetKeyboardLayout.argtypes = (wintypes.DWORD,)
        user32.GetKeyboardLayout.restype = wintypes.HANDLE
        user32.ToUnicodeEx.argtypes = (wintypes.UINT, wintypes.UINT, ctypes.c_char_p, wintypes.LPWSTR, ctypes.c_int, wintypes.UINT, wintypes.HANDLE)
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        cursor_ids = (32512, 32513, 32514, 32515, 32516, 32642, 32643, 32644, 32645, 32646, 32648, 32649, 32650)
        restore_cursors = lambda: user32.SystemParametersInfoW(0x57, 0, None, 0)  # SPI_SETCURSORS reloads the user's scheme.
        restore_cursors()  # Recover from a previous run that ended while the cursor was hidden.
        capslock = [bool(user32.GetKeyState(20) & 1)]

        def hide_cursor():
            and_mask, xor_mask = (ctypes.c_ubyte * 128)(*([255] * 128)), (ctypes.c_ubyte * 128)()
            for cursor in cursor_ids:
                user32.SetSystemCursor(user32.CreateCursor(None, 0, 0, 32, 32, and_mask, xor_mask), cursor)

        def park():
            left, top, right, bottom = self.bounds()
            primary = (user32.GetSystemMetrics(0) // 2, user32.GetSystemMetrics(1) // 2)
            return primary if left <= primary[0] < right and top <= primary[1] < bottom else ((left + right) // 2, (top + bottom) // 2)

        def leave(point=None):
            remote, self.remote, self.leave_requested = self.remote, None, False
            restore_cursors()
            if remote:
                point = point or leave_point(remote['side'], remote['start'], remote['y'] if remote['side'] in ('left', 'right') else remote['x'], self.bounds())
                user32.SetCursorPos(*point)
                self.emit({'type': 'leave', 'device': remote['device']})
            self.keys.clear()

        def modifiers():
            return (1 if self.keys & set(ALT) else 0) | (2 if self.keys & set(CONTROL) else 0) | (4 if self.keys & set(META) else 0) | (8 if self.keys & set(SHIFT) else 0)

        def text_for(vk, scan):
            state = (ctypes.c_ubyte * 256)()
            for key in self.keys:
                if key < 256:
                    state[key] = 0x80
            for group, generic in ((SHIFT, 16), (CONTROL, 17), (ALT, 18)):
                if self.keys & set(group):
                    state[generic] = 0x80
            state[20] = 1 if capslock[0] else 0
            buffer = ctypes.create_unicode_buffer(8)
            layout = user32.GetKeyboardLayout(user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None))
            count = user32.ToUnicodeEx(vk, scan, ctypes.cast(state, ctypes.c_char_p), buffer, 8, 0, layout)
            return buffer.value[:count] if count > 0 else ''

        @HOOKPROC
        def mouse(code, message, data):
            if code < 0:
                return user32.CallNextHookEx(None, code, message, data)
            event = ctypes.cast(data, ctypes.POINTER(MSLL)).contents
            if event.flags & 1:  # Injected by software (including our own SetCursorPos).
                return user32.CallNextHookEx(None, code, message, data)
            try:
                if message in (0x201, 0x204, 0x207):
                    self.buttons += 1
                elif message in (0x202, 0x205, 0x208):
                    self.buttons = max(0, self.buttons - 1)
                remote = self.remote
                if remote is None:
                    if message == 0x200 and not self.buttons and self.regions:
                        region, entry = region_at(self.regions, event.x, event.y, self.bounds())
                        if region:
                            center = park()
                            self.remote = {'device': region['device'], 'side': region['side'], 'start': region['start'],
                                           'width': region['width'], 'height': region['height'], 'x': entry[0], 'y': entry[1], 'center': center}
                            hide_cursor()
                            user32.SetCursorPos(*center)
                            self.emit({'type': 'enter', 'device': region['device'], 'x': entry[0], 'y': entry[1]})
                            return 1
                    return user32.CallNextHookEx(None, code, message, data)
                if self.leave_requested:
                    leave()
                    return user32.CallNextHookEx(None, code, message, data)
                if message == 0x200:
                    center = remote['center']
                    dx, dy = event.x - center[0], event.y - center[1]
                    if dx or dy:
                        x, y = remote['x'] + dx, remote['y'] + dy
                        if crossed_back(remote['side'], x, y, remote['width'], remote['height']):
                            leave()
                            return 1
                        remote['x'], remote['y'] = min(max(x, 0), remote['width'] - 1), min(max(y, 0), remote['height'] - 1)
                        self.emit({'type': 'move', 'device': remote['device'], 'x': remote['x'], 'y': remote['y']})
                elif message in (0x201, 0x202, 0x204, 0x205, 0x207, 0x208):
                    button = {0x201: 'left', 0x202: 'left', 0x204: 'right', 0x205: 'right', 0x207: 'middle', 0x208: 'middle'}[message]
                    self.emit({'type': 'button', 'device': remote['device'], 'button': button, 'down': message in (0x201, 0x204, 0x207), 'x': remote['x'], 'y': remote['y'], 'modifiers': modifiers()})
                elif message in (0x20A, 0x20E):
                    delta = ctypes.c_short(event.mouseData >> 16).value
                    vertical = message == 0x20A
                    self.emit({'type': 'wheel', 'device': remote['device'], 'x': remote['x'], 'y': remote['y'], 'dx': 0 if vertical else delta, 'dy': -delta if vertical else 0})
                return 1
            except Exception:
                logger.exception('Mouse hook failed')
                leave()
                return user32.CallNextHookEx(None, code, message, data)

        @HOOKPROC
        def keyboard(code, message, data):
            if code < 0 or self.remote is None:
                return user32.CallNextHookEx(None, code, message, data)
            event = ctypes.cast(data, ctypes.POINTER(KBDLL)).contents
            if event.flags & 0x10:  # Injected.
                return user32.CallNextHookEx(None, code, message, data)
            try:
                down = message in (0x100, 0x104)
                vk = event.vk
                if down:
                    self.keys.add(vk)
                    if vk == 20:
                        capslock[0] = not capslock[0]
                else:
                    self.keys.discard(vk)
                mods = modifiers()
                altgr = bool(self.keys & {165}) or (bool(self.keys & set(CONTROL)) and bool(self.keys & set(ALT)))
                text = text_for(vk, event.scan) if down and (vk not in SPECIAL or vk == 32) else ''
                if text and (mods & 2 or mods & 1) and not altgr:
                    text = ''  # Shortcuts such as Ctrl+C carry no text.
                if text and not text.isprintable():
                    text = ''
                key = SPECIAL.get(vk) or text or (chr(vk).lower() if 48 <= vk <= 90 else 'Unidentified')
                self.emit({'type': 'key', 'device': self.remote['device'], 'down': down, 'vk': vk, 'key': key, 'code': CODES.get(vk, ''), 'text': text, 'modifiers': mods & ~3 if altgr and text else mods})
                return 1
            except Exception:
                logger.exception('Keyboard hook failed')
                return user32.CallNextHookEx(None, code, message, data)

        self._procs = (mouse, keyboard)  # Keep the callbacks alive.
        module = kernel32.GetModuleHandleW(None)
        hooks = [user32.SetWindowsHookExW(14, mouse, module, 0), user32.SetWindowsHookExW(13, keyboard, module, 0)]
        if not all(hooks):
            logger.error('Could not install input hooks')
            return
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            restore_cursors()
            for hook in hooks:
                user32.UnhookWindowsHookEx(hook)
