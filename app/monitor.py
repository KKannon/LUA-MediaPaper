"""Hub for /screen: devices that act as extra screens, their windows (hidden browser tabs) and the shared cursor."""
import asyncio
import base64
import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)
SIDES = ('left', 'right', 'top', 'bottom')
MAX_DEVICES = 8
MAX_WINDOWS = 8
MAX_APPS = 24
DEFAULT_APPS = [('YouTube', 'https://www.youtube.com/'), ('X', 'https://x.com/'), ('Instagram', 'https://www.instagram.com/'), ('Google', 'https://www.google.com/')]
_lock = threading.RLock()

def _store():
    from django.conf import settings
    return Path(settings.LUAMP_DATA_DIR) / 'monitors.json'

def load_devices():
    with _lock:
        try:
            data = json.loads(_store().read_text(encoding='utf-8'))
            return {key: value for key, value in data.items() if isinstance(value, dict)}
        except (OSError, ValueError):
            return {}

def save_devices(devices):
    with _lock:
        path = _store()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(devices, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)

def host_of(url):
    from urllib.parse import urlparse
    host = (urlparse(url or '').hostname or '').lower()
    return host[4:] if host.startswith('www.') else host

def app_name(title, host):
    """Short app name: the site's own name from the page title, or the domain while the title is unknown."""
    title = (title or '').strip()
    if title and '://' not in title and not re.search(r'[/:]\d|^[\w.-]+\.\w{2,}(/|$)', title) and host_of('http://' + title) != host:
        parts = [part.strip() for part in re.split(r' [-|–—·/] ', title) if part.strip()]
        for part in (parts[-1], parts[0]):
            if len(part) <= 24:
                return part, True
    label = host if re.fullmatch(r'[\d.]+|localhost', host) else host.split('.')[-2] if host.count('.') else host
    return label[:1].upper() + label[1:], False

def default_apps():
    return [{'id': uuid.uuid4().hex[:8], 'name': name, 'url': url, 'host': host_of(url), 'last': url} for name, url in DEFAULT_APPS]

def clean_name(value, fallback='Tela extra'):
    value = re.sub(r'\s+', ' ', str(value or '')).strip()[:40]
    return value or fallback

def number(value, low, high, default):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return default if value != value else min(max(value, low), high)

class Hub:
    def __init__(self):
        self.loop = None
        self.port = None
        self.connections = {}   # device id -> websocket
        self.windows = {}       # window id -> state
        self.sessions = {}      # DevTools session -> window id
        self.screens = {}       # device id -> {'rects': [...], 'focus': window id}
        self.cursor = {}        # device id -> {'x', 'y', 'capture', 'last_click'}
        self.browser = None
        self.edge = None
        self.adopting = set()

    # Thread-safe API used by Django views.
    def running(self):
        return self.loop is not None

    def screen_size(self):
        if self.edge:
            left, top, right, bottom = self.edge.bounds()
            return {'width': right - left, 'height': bottom - top}
        return {'width': 1920, 'height': 1080}

    def snapshot(self):
        devices = load_devices()
        return {'screen': self.screen_size(), 'edgeInput': bool(self.edge and self.edge.thread), 'running': self.running(),
                'devices': [{**device, 'online': key in self.connections} for key, device in sorted(devices.items(), key=lambda item: item[1].get('created', 0))]}

    def update(self, device_id, changes):
        with _lock:
            devices = load_devices()
            device = devices.get(device_id)
            if device is None:
                raise KeyError(device_id)
            if 'name' in changes:
                device['name'] = clean_name(changes['name'], device.get('name', 'Tela extra'))
            if 'side' in changes:
                if changes['side'] not in SIDES + (None,):
                    raise ValueError('Lado inválido.')
                device['side'] = changes['side']
            if 'offset' in changes:
                device['offset'] = int(number(changes['offset'], -20000, 20000, 0))
            if 'approved' in changes:
                device['approved'] = bool(changes['approved'])
            save_devices(devices)
        self._call(self._device_changed, device_id)
        return device

    def forget(self, device_id):
        with _lock:
            devices = load_devices()
            if devices.pop(device_id, None) is None:
                raise KeyError(device_id)
            save_devices(devices)
        self._call(self._device_forgotten, device_id)

    def _call(self, function, *args):
        if self.loop:
            asyncio.run_coroutine_threadsafe(function(*args), self.loop)

    # Server.
    def start(self, host, port):
        if self.loop is not None:
            return
        from app.edge_input import EdgeInput, AVAILABLE
        import os
        self.port = port
        ready = threading.Event()
        def run():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._serve(host, port, ready))
        threading.Thread(target=run, daemon=True, name='lua-monitor').start()
        if not ready.wait(10):
            raise RuntimeError('Monitor hub did not start')
        if AVAILABLE and os.environ.get('LUAMP_DESKTOP') == '1':
            self.edge = EdgeInput(lambda event: self.loop.call_soon_threadsafe(self._edge, event))
            self.edge.start()
            self._update_regions()

    async def _serve(self, host, port, ready):
        from websockets.asyncio.server import serve
        from django.conf import settings
        from app.browser import Browser
        self.browser = Browser(settings.LUAMP_DATA_DIR, self._browser_event)
        async with serve(self._client, host, port, process_request=self._check_origin, max_size=256 * 1024, ping_interval=20, ping_timeout=20):
            ready.set()
            await asyncio.get_running_loop().create_future()

    def _check_origin(self, connection, request):
        # Only pages served by this app may connect; blocks other websites from driving the browser.
        from urllib.parse import urlparse
        from django.conf import settings
        from django.http.request import validate_host
        origin = urlparse(request.headers.get('Origin', ''))
        expected_port = str(self.port - 1)
        if not origin.hostname or not validate_host(origin.hostname if ':' not in origin.hostname else f'[{origin.hostname}]', settings.ALLOWED_HOSTS) or str(origin.port or 80) != expected_port:
            return connection.respond(403, 'Origin not allowed\n')
        return None

    async def _client(self, connection):
        device_id = None
        try:
            hello = json.loads(await asyncio.wait_for(connection.recv(), 10))
            if hello.get('type') != 'hello' or not re.fullmatch(r'[a-f0-9-]{8,64}', str(hello.get('id', ''))):
                return
            device_id = hello['id']
            with _lock:
                devices = load_devices()
                if device_id not in devices and len(devices) >= MAX_DEVICES:
                    await connection.send(json.dumps({'type': 'error', 'message': 'Limite de telas extras atingido. Remova uma tela na Home do PC.'}))
                    return
                device = devices.setdefault(device_id, {'id': device_id, 'name': clean_name(hello.get('name')), 'approved': False, 'side': None, 'offset': 0, 'created': time.time()})
                device.setdefault('apps', default_apps())
                device.update(self._size(hello))
                save_devices(devices)
            previous = self.connections.get(device_id)
            self.connections[device_id] = connection
            if previous:
                await previous.close(4000, 'Aberto em outra aba')
            await self._send_state(device_id)
            self._update_regions()
            async for raw in connection:
                if isinstance(raw, bytes):
                    continue
                try:
                    await self._message(device_id, json.loads(raw))
                except Exception as exc:
                    logger.exception('Monitor message failed')
                    from app.browser import BrowserUnavailable
                    message = str(exc) if isinstance(exc, (BrowserUnavailable, ValueError)) else 'Não foi possível concluir a ação.'
                    await self._send(device_id, {'type': 'error', 'message': message})
        except Exception:
            pass
        finally:
            if device_id and self.connections.get(device_id) is connection:
                del self.connections[device_id]
                if self.edge:
                    self.edge.leave(device_id)
                self._update_regions()

    def _size(self, message):
        return {'width': int(number(message.get('width'), 200, 8000, 1280)), 'height': int(number(message.get('height'), 200, 8000, 800)), 'scale': number(message.get('scale'), 1, 4, 1)}

    def _approved(self, device_id):
        return bool(load_devices().get(device_id, {}).get('approved'))

    async def _send(self, device_id, message):
        connection = self.connections.get(device_id)
        if connection:
            try:
                await connection.send(json.dumps(message, ensure_ascii=False) if isinstance(message, dict) else message)
            except Exception:
                pass

    def _public(self, window):
        return {key: window[key] for key in ('id', 'url', 'title', 'loading')}

    async def _send_state(self, device_id):
        device = load_devices().get(device_id)
        if device is None:
            await self._send(device_id, {'type': 'forgotten'})
            return
        windows = [self._public(window) for window in self.windows.values() if window['device'] == device_id] if device.get('approved') else []
        await self._send(device_id, {'type': 'state', 'device': device, 'windows': windows, 'edgeInput': bool(self.edge and self.edge.thread)})

    async def _device_changed(self, device_id):
        await self._send_state(device_id)
        self._update_regions()

    async def _device_forgotten(self, device_id):
        for window in [w for w in self.windows.values() if w['device'] == device_id]:
            await self._close(window['id'])
        await self._send(device_id, {'type': 'forgotten'})
        connection = self.connections.get(device_id)
        if connection:
            await connection.close(4001, 'Tela removida')
        self._update_regions()

    def _update_regions(self):
        if not self.edge:
            return
        regions = []
        for device_id, device in load_devices().items():
            if device.get('approved') and device.get('side') in SIDES and device_id in self.connections:
                regions.append({'device': device_id, 'side': device['side'], 'start': device.get('offset', 0), 'width': device['width'], 'height': device['height']})
        self.edge.set_regions(regions)

    # Messages from devices.
    async def _message(self, device_id, message):
        kind = message.get('type')
        if kind == 'size':
            with _lock:
                devices = load_devices()
                if device_id in devices:
                    devices[device_id].update(self._size(message))
                    save_devices(devices)
            self._update_regions()
            return
        if not self._approved(device_id):
            return
        window = self.windows.get(message.get('win'))
        if window is not None and window['device'] != device_id:
            return
        if kind in ('pin', 'unpin', 'launch'):
            await self._apps(device_id, kind, message, window)
            return
        if kind == 'open':
            from app.browser import normalize_url
            if sum(1 for w in self.windows.values() if w['device'] == device_id) >= MAX_WINDOWS:
                raise ValueError(f'Feche uma janela para abrir outra (máximo de {MAX_WINDOWS}).')
            url = normalize_url(message.get('url'))
            width, height, scale = number(message.get('w'), 200, 3840, 1000), number(message.get('h'), 150, 2400, 700), load_devices()[device_id].get('scale', 1)
            target, session = await self.browser.open(url, width, height, scale)
            self._add_window(device_id, target, session, url, width, height, scale)
        elif kind == 'layout':
            rects = []
            for rect in message.get('rects', [])[:MAX_WINDOWS]:
                if rect.get('win') in self.windows:
                    rects.append({key: number(rect.get(key), -10000, 10000, 0) for key in ('x', 'y', 'w', 'h', 'fx', 'fy', 'fw', 'fh')} | {'win': rect['win']})
            focus = message.get('focus') if message.get('focus') in self.windows else None
            self.screens[device_id] = {'rects': rects, 'focus': focus}
        elif window is None:
            return
        elif kind == 'close':
            await self._close(window['id'])
        elif kind == 'resize':
            window['w'], window['h'] = number(message.get('w'), 200, 3840, window['w']), number(message.get('h'), 150, 2400, window['h'])
            await self.browser.configure(window['session'], window['w'], window['h'], window['scale'])
        elif kind == 'nav':
            await self._navigate(window, message.get('action'), message.get('url'))
        elif kind == 'ack':
            frame, window['frame'] = window.get('frame'), None
            if frame is not None:
                await self.browser.send('Page.screencastFrameAck', {'sessionId': frame}, window['session'], wait=False)
        elif kind == 'mouse':
            await self._mouse(window, message.get('action'), number(message.get('x'), -10000, 10000, 0), number(message.get('y'), -10000, 10000, 0),
                              message.get('button', 'left'), number(message.get('dx'), -10000, 10000, 0), number(message.get('dy'), -10000, 10000, 0), int(number(message.get('modifiers'), 0, 15, 0)))
        elif kind == 'key':
            await self._key(window, bool(message.get('down')), int(number(message.get('vk'), 0, 255, 0)), str(message.get('key', ''))[:20], str(message.get('code', ''))[:20], str(message.get('text', ''))[:4], int(number(message.get('modifiers'), 0, 15, 0)))
        elif kind == 'text':
            text = str(message.get('text', ''))[:500]
            if text:
                await self.browser.send('Input.insertText', {'text': text}, window['session'], wait=False)

    async def _apps(self, device_id, kind, message, window):
        with _lock:
            devices = load_devices()
            apps = devices[device_id].setdefault('apps', default_apps())
            if kind == 'pin' and window is not None and window['url'].startswith(('http://', 'https://')):
                host = host_of(window['url'])
                if host and not any(app['host'] == host for app in apps) and len(apps) < MAX_APPS:
                    from urllib.parse import urlparse
                    origin = urlparse(window['url'])
                    name, named = app_name(window['title'], host)
                    apps.append({'id': uuid.uuid4().hex[:8], 'name': clean_name(name, host)[:24], 'named': named, 'url': f'{origin.scheme}://{origin.netloc}/', 'host': host, 'last': window['url']})
            elif kind == 'unpin':
                apps[:] = [app for app in apps if app['id'] != message.get('app')]
            elif kind == 'launch':
                app = next((dict(app) for app in apps if app['id'] == message.get('app')), None)
            if kind != 'launch':
                save_devices(devices)
        if kind != 'launch':
            await self._send(device_id, {'type': 'apps', 'apps': apps})
        elif app is not None:
            # An app already open is brought to the front instead of opening twice.
            for open_window in self.windows.values():
                if open_window['device'] == device_id and host_of(open_window['url']) == app['host']:
                    await self._send(device_id, {'type': 'focus', 'win': open_window['id']})
                    return
            await self._message(device_id, {'type': 'open', 'url': app.get('last') or app['url'], 'w': message.get('w'), 'h': message.get('h')})

    def _remember(self, window):
        """Pinned apps reopen at the last page visited on their site."""
        host = host_of(window['url'])
        if not host or not window['url'].startswith(('http://', 'https://')):
            return
        with _lock:
            devices = load_devices()
            device = devices.get(window['device'])
            for app in (device or {}).get('apps', []):
                if app['host'] != host:
                    continue
                changed = app.get('last') != window['url']
                app['last'] = window['url']
                if app.get('named') is False:
                    name, named = app_name(window['title'], host)
                    if named:
                        app['name'], app['named'], changed = clean_name(name, host)[:24], True, True
                if changed:
                    save_devices(devices)
                    if app.get('named'):
                        asyncio.ensure_future(self._send(window['device'], {'type': 'apps', 'apps': device['apps']}))
                return

    def _add_window(self, device_id, target, session, url, width, height, scale):
        window = {'id': uuid.uuid4().hex[:12], 'device': device_id, 'target': target, 'session': session, 'url': url, 'title': '', 'loading': True,
                  'w': width, 'h': height, 'scale': scale, 'frame': None}
        self.windows[window['id']] = window
        self.sessions[session] = window['id']
        asyncio.ensure_future(self._send(device_id, {'type': 'window', 'window': self._public(window)}))
        return window

    async def _close(self, window_id):
        window = self.windows.pop(window_id, None)
        if window is None:
            return
        self.sessions.pop(window['session'], None)
        await self.browser.close_target(window['target'])
        await self._send(window['device'], {'type': 'closed', 'win': window_id})

    async def _navigate(self, window, action, url=None):
        session = window['session']
        if action == 'go':
            from app.browser import normalize_url
            await self.browser.send('Page.navigate', {'url': normalize_url(url)}, session)
        elif action == 'reload':
            await self.browser.send('Page.reload', {}, session)
        elif action in ('back', 'forward'):
            history = await self.browser.send('Page.getNavigationHistory', {}, session)
            index = history['currentIndex'] + (-1 if action == 'back' else 1)
            if 0 <= index < len(history['entries']):
                await self.browser.send('Page.navigateToHistoryEntry', {'entryId': history['entries'][index]['id']}, session)

    async def _mouse(self, window, action, x, y, button='left', dx=0, dy=0, modifiers=0, clicks=1):
        session = window['session']
        button = button if button in ('left', 'right', 'middle') else 'left'
        if action == 'wheel':
            await self.browser.send('Input.dispatchMouseEvent', {'type': 'mouseWheel', 'x': x, 'y': y, 'deltaX': dx, 'deltaY': dy, 'modifiers': modifiers}, session, wait=False)
        elif action in ('down', 'up'):
            event = {'type': 'mousePressed' if action == 'down' else 'mouseReleased', 'x': x, 'y': y, 'button': button, 'clickCount': clicks, 'modifiers': modifiers,
                     'buttons': {'left': 1, 'right': 2, 'middle': 4}[button] if action == 'down' else 0}
            await self.browser.send('Input.dispatchMouseEvent', event, session, wait=False)
        else:
            held = window.get('held')
            await self.browser.send('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y, 'modifiers': modifiers, 'button': held or 'none', 'buttons': {'left': 1, 'right': 2, 'middle': 4}.get(held, 0)}, session, wait=False)
        if action == 'down':
            window['held'] = button
        elif action == 'up':
            window['held'] = None

    async def _key(self, window, down, vk, key, code, text, modifiers):
        event = {'type': ('keyDown' if text else 'rawKeyDown') if down else 'keyUp', 'windowsVirtualKeyCode': vk, 'nativeVirtualKeyCode': vk, 'key': key, 'code': code, 'modifiers': modifiers}
        if text and down:
            event.update(text=text, unmodifiedText=text)
        await self.browser.send('Input.dispatchKeyEvent', event, window['session'], wait=False)

    # Events from the hidden browser.
    async def _browser_event(self, session, method, params):
        if method == 'Page.screencastFrame':
            window = self.windows.get(self.sessions.get(session))
            if window is None:
                return
            if window['device'] not in self.connections:
                await self.browser.send('Page.screencastFrameAck', {'sessionId': params['sessionId']}, session, wait=False)
                return
            window['frame'] = params['sessionId']  # Acknowledged when the device has drawn it, so slow devices get fewer frames.
            prefix = window['id'].encode()
            await self._send(window['device'], bytes([len(prefix)]) + prefix + base64.b64decode(params['data']))
        elif method == 'Target.targetInfoChanged':
            info = params['targetInfo']
            for window in self.windows.values():
                if window['target'] == info['targetId']:
                    window['title'], window['url'] = info.get('title', '')[:200], info.get('url', '')[:2000]
                    window['loading'] = False
                    self._remember(window)
                    await self._send(window['device'], {'type': 'title', 'win': window['id'], 'title': window['title'], 'url': window['url']})
        elif method == 'Target.targetCreated':
            info = params['targetInfo']
            if info.get('type') == 'page' and info.get('openerId'):
                asyncio.ensure_future(self._adopt(info))
        elif method == 'Target.targetDestroyed':
            for window in [w for w in self.windows.values() if w['target'] == params['targetId']]:
                self.windows.pop(window['id'], None)
                self.sessions.pop(window['session'], None)
                await self._send(window['device'], {'type': 'closed', 'win': window['id']})
        elif method == 'Lua.browserClosed':
            for window in list(self.windows.values()):
                await self._send(window['device'], {'type': 'closed', 'win': window['id']})
            self.windows.clear()
            self.sessions.clear()

    async def _adopt(self, info):
        """Pages opened by a site (target=_blank, popups) become a new window on the same device."""
        await asyncio.sleep(.3)
        opener = next((w for w in self.windows.values() if w['target'] == info['openerId']), None)
        if opener is None or any(w['target'] == info['targetId'] for w in self.windows.values()) or info['targetId'] in self.adopting:
            return
        self.adopting.add(info['targetId'])
        try:
            if sum(1 for w in self.windows.values() if w['device'] == opener['device']) >= MAX_WINDOWS:
                await self.browser.close_target(info['targetId'])
                return
            session = await self.browser.attach(info['targetId'])
            await self.browser.configure(session, opener['w'], opener['h'], opener['scale'])
            self._add_window(opener['device'], info['targetId'], session, info.get('url', ''), opener['w'], opener['h'], opener['scale'])
        finally:
            self.adopting.discard(info['targetId'])

    # Shared cursor from the PC.
    def _hit(self, device_id, x, y):
        # Rects are top-most first: the first frame under the point wins; its title bar belongs to the shell.
        for rect in self.screens.get(device_id, {}).get('rects', []):
            if rect['fx'] <= x < rect['fx'] + rect['fw'] and rect['fy'] <= y < rect['fy'] + rect['fh']:
                if rect['x'] <= x < rect['x'] + rect['w'] and rect['y'] <= y < rect['y'] + rect['h']:
                    return self.windows.get(rect['win']), rect
                return None, None
        return None, None

    def _edge(self, event):
        asyncio.ensure_future(self._edge_event(event))

    async def _edge_event(self, event):
        device_id = event['device']
        state = self.cursor.setdefault(device_id, {'capture': None, 'last': (0, 0, 0)})
        kind = event['type']
        if kind == 'leave':
            state['capture'] = None
            await self._send(device_id, {'type': 'cursor', 'visible': False})
            return
        if kind == 'key':
            screen = self.screens.get(device_id, {})
            window = self.windows.get(screen.get('focus'))
            if window and window['device'] == device_id:
                await self._key(window, event['down'], event['vk'], event['key'], event['code'], event['text'], event['modifiers'])
            else:
                await self._send(device_id, {'type': 'key', **{k: event[k] for k in ('down', 'key', 'code', 'text', 'modifiers')}})
            return
        x, y = event['x'], event['y']
        await self._send(device_id, {'type': 'cursor', 'visible': True, 'x': x, 'y': y})
        if kind == 'enter':
            return
        captured = self.windows.get(state['capture']) if state['capture'] else None
        window, rect = self._hit(device_id, x, y)
        if captured is not None:
            window = captured
            rect = next((r for r in self.screens.get(device_id, {}).get('rects', []) if r['win'] == captured['id']), None)
        if window is None or rect is None:
            # Over the shell (dock, title bars, desktop): the device page handles it.
            if kind in ('button', 'wheel'):
                await self._send(device_id, {'type': 'pointer', 'action': ('down' if event['down'] else 'up') if kind == 'button' else 'wheel', 'button': event.get('button', 'left'), 'x': x, 'y': y, 'dx': event.get('dx', 0), 'dy': event.get('dy', 0)})
            return
        local_x, local_y = x - rect['x'], y - rect['y']
        if kind == 'move':
            await self._mouse(window, 'move', local_x, local_y)
        elif kind == 'wheel':
            await self._mouse(window, 'wheel', local_x, local_y, dx=event['dx'], dy=event['dy'])
        elif kind == 'button':
            clicks = 1
            if event['down']:
                previous = state['last']
                now = time.monotonic()
                clicks = 2 if now - previous[0] < .45 and abs(previous[1] - x) < 6 and abs(previous[2] - y) < 6 else 1
                state['last'] = (now, x, y)
                state['capture'] = window['id']
                self.screens.setdefault(device_id, {'rects': []})['focus'] = window['id']
                await self._send(device_id, {'type': 'focus', 'win': window['id']})  # Also takes focus away from the shell's fields.
            else:
                state['capture'] = None
            await self._mouse(window, 'down' if event['down'] else 'up', local_x, local_y, event['button'], modifiers=event.get('modifiers', 0), clicks=clicks)

hub = Hub()
