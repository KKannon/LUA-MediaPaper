"""Hidden Chromium/Edge driven through the DevTools protocol; each tab is a window of the web OS on /monitor."""
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

class BrowserUnavailable(RuntimeError):
    pass

def find_browser():
    configured = os.environ.get('LUAMP_BROWSER')
    if configured:
        return configured
    candidates = []
    if sys.platform == 'win32':
        for root in filter(None, (os.environ.get('PROGRAMFILES(X86)'), os.environ.get('PROGRAMFILES'), os.environ.get('LOCALAPPDATA'))):
            candidates += [Path(root) / 'Microsoft/Edge/Application/msedge.exe', Path(root) / 'Google/Chrome/Application/chrome.exe']
    for path in candidates:
        if path.is_file():
            return str(path)
    for name in ('msedge', 'microsoft-edge', 'google-chrome', 'chromium', 'chromium-browser', 'chrome'):
        found = shutil.which(name)
        if found:
            return found
    return None

def normalize_url(value):
    value = (value or '').strip()
    if not value:
        return 'https://www.google.com/'
    if value.startswith(('http://', 'https://')):
        return value
    import re
    if re.match(r'^(localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?(/|$)', value):
        return 'http://' + value  # Local network addresses rarely have HTTPS.
    if ' ' in value or '.' not in value:
        from urllib.parse import quote_plus
        return 'https://www.google.com/search?q=' + quote_plus(value)
    return 'https://' + value

class Browser:
    """One browser process and one DevTools connection, used from a single asyncio loop."""
    def __init__(self, data_dir, on_event):
        self.data_dir = Path(data_dir) / 'browser'
        self.on_event = on_event  # Called with (session_id, method, params).
        self.process = None
        self.connection = None
        self.reader = None
        self.next_id = 0
        self.pending = {}
        self.lock = asyncio.Lock()
        self.user_agent = None

    async def start(self):
        async with self.lock:
            if self.connection is not None:
                return
            executable = find_browser()
            if not executable:
                raise BrowserUnavailable('Instale o Microsoft Edge ou o Google Chrome para usar as janelas do /monitor.')
            self.data_dir.mkdir(parents=True, exist_ok=True)
            port_file = self.data_dir / 'DevToolsActivePort'
            port_file.unlink(missing_ok=True)
            args = [executable, '--headless=new', f'--user-data-dir={self.data_dir}', '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
                    '--no-first-run', '--no-default-browser-check', '--autoplay-policy=no-user-gesture-required', '--disable-features=Translate,MediaRouter',
                    '--lang=pt-BR', '--window-size=1280,800', 'about:blank']
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            import atexit
            atexit.register(self.process.terminate)  # Quitting from the tray must not leave the hidden browser running.
            for _ in range(150):
                if port_file.is_file():
                    lines = port_file.read_text(encoding='utf-8').split()
                    if len(lines) >= 2:
                        break
                if self.process.poll() is not None:
                    raise BrowserUnavailable('O navegador das janelas fechou ao iniciar.')
                await asyncio.sleep(.1)
            else:
                self.process.kill()
                raise BrowserUnavailable('O navegador das janelas não respondeu.')
            from websockets.asyncio.client import connect
            self.connection = await connect(f'ws://127.0.0.1:{lines[0]}{lines[1]}', max_size=None, ping_interval=None)
            self.reader = asyncio.create_task(self._read())
            await self.send('Target.setDiscoverTargets', {'discover': True})
            # Sites such as YouTube and X degrade or block browsers that announce themselves as headless.
            self.user_agent = (await self.send('Browser.getVersion'))['userAgent'].replace('HeadlessChrome', 'Chrome').replace('HeadlessEdg', 'Edg')

    async def _read(self):
        try:
            async for raw in self.connection:
                message = json.loads(raw)
                if 'id' in message:
                    future = self.pending.pop(message['id'], None)
                    if future and not future.done():
                        if 'error' in message:
                            future.set_exception(RuntimeError(message['error'].get('message', 'DevTools error')))
                        else:
                            future.set_result(message.get('result', {}))
                else:
                    try:
                        await self.on_event(message.get('sessionId'), message['method'], message.get('params', {}))
                    except Exception:
                        logger.exception('Browser event failed')
        except Exception:
            logger.exception('Browser connection lost')
        finally:
            self.connection = None
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(BrowserUnavailable('O navegador das janelas foi fechado.'))
            self.pending.clear()
            await self.on_event(None, 'Lua.browserClosed', {})

    async def send(self, method, params=None, session=None, wait=True):
        if self.connection is None:
            raise BrowserUnavailable('O navegador das janelas não está em execução.')
        self.next_id += 1
        message = {'id': self.next_id, 'method': method, 'params': params or {}}
        if session:
            message['sessionId'] = session
        future = asyncio.get_running_loop().create_future()
        self.pending[self.next_id] = future
        await self.connection.send(json.dumps(message))
        if not wait:
            future.add_done_callback(lambda f: f.exception())  # Consume errors of fire-and-forget input events.
            return None
        return await asyncio.wait_for(future, 30)

    async def open(self, url, width, height, scale):
        await self.start()
        target = (await self.send('Target.createTarget', {'url': 'about:blank'}))['targetId']
        session = await self.attach(target)
        await self.configure(session, width, height, scale)
        await self.send('Page.navigate', {'url': url}, session)
        return target, session

    async def attach(self, target):
        session = (await self.send('Target.attachToTarget', {'targetId': target, 'flatten': True}))['sessionId']
        await self.send('Page.enable', session=session)
        await self.send('Network.setUserAgentOverride', {'userAgent': self.user_agent, 'acceptLanguage': 'pt-BR,pt;q=0.9,en;q=0.6'}, session)
        return session

    async def configure(self, session, width, height, scale):
        width, height = max(200, min(int(width), 3840)), max(150, min(int(height), 2400))
        scale = max(1, min(float(scale or 1), 2))
        await self.send('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': scale, 'mobile': False}, session)
        await self.send('Page.stopScreencast', session=session)
        # Frames are capped near 1080p; higher densities cost bandwidth without visible gain on small screens.
        limit = min(1.0, 1920 / max(width * scale, 1), 1200 / max(height * scale, 1))
        await self.send('Page.startScreencast', {'format': 'jpeg', 'quality': 72, 'maxWidth': int(width * scale * limit), 'maxHeight': int(height * scale * limit), 'everyNthFrame': 1}, session)

    async def close_target(self, target):
        try:
            await self.send('Target.closeTarget', {'targetId': target})
        except Exception:
            pass
