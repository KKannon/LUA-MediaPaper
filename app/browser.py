"""Hidden Chromium/Edge driven through the DevTools protocol; each tab is a window of Lua OS on /screen."""
import asyncio
import base64
import re
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

PROFILE_IN_USE = 21  # Chromium exit code when another process holds the profile lock.

class BrowserUnavailable(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code

def find_browsers():
    """Installed Chromium browsers, Edge first (always present on Windows)."""
    configured = os.environ.get('LUAMP_BROWSER')
    if configured:
        return [configured]
    found = []
    if sys.platform == 'win32':
        for name in ('Microsoft/Edge/Application/msedge.exe', 'Google/Chrome/Application/chrome.exe'):
            for root in filter(None, (os.environ.get('PROGRAMFILES(X86)'), os.environ.get('PROGRAMFILES'), os.environ.get('LOCALAPPDATA'))):
                path = Path(root) / name
                if path.is_file() and str(path) not in found:
                    found.append(str(path))
                    break
    for name in ('msedge', 'microsoft-edge', 'google-chrome', 'chromium', 'chromium-browser', 'chrome'):
        path = shutil.which(name)
        if path and path not in found:
            found.append(path)
    return found

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
        self.root = Path(data_dir)
        self.choice = self.root / 'browser-profile.txt'
        self.log_path = self.root / 'browser-launch.log'
        try:
            name = self.choice.read_text(encoding='utf-8').strip()
        except OSError:
            name = ''
        self.data_dir = self.root / (name if re.fullmatch(r'browser(-\d+)?', name) else 'browser')
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
            self.data_dir.mkdir(parents=True, exist_ok=True)
            endpoint = await self._existing()
            if endpoint is None:
                endpoint = await self._launch_any()
            from websockets.asyncio.client import connect
            self.connection = await connect(endpoint, max_size=None, ping_interval=None)
            self.reader = asyncio.create_task(self._read())
            await self.send('Target.setDiscoverTargets', {'discover': True})
            # Sites such as YouTube and X degrade or block browsers that announce themselves as headless.
            self.user_agent = (await self.send('Browser.getVersion'))['userAgent'].replace('HeadlessChrome', 'Chrome').replace('HeadlessEdg', 'Edg')
            # Tabs left by a previous run have no window on any device; the blank start page keeps the browser alive.
            for target in (await self.send('Target.getTargets'))['targetInfos']:
                if target.get('type') == 'page' and target.get('url') != 'about:blank':
                    await self.close_target(target['targetId'])

    def _endpoint(self):
        try:
            lines = (self.data_dir / 'DevToolsActivePort').read_text(encoding='utf-8').split()
            return f'ws://127.0.0.1:{int(lines[0])}{lines[1]}' if len(lines) >= 2 else None
        except (OSError, ValueError):
            return None

    async def _existing(self):
        """A hidden browser from an earlier run still owns the profile: reuse it instead of fighting over the lock."""
        endpoint = self._endpoint()
        if not endpoint:
            return None
        from urllib.request import urlopen
        port = endpoint.split(':')[2].split('/')[0]
        try:
            await asyncio.to_thread(lambda: urlopen(f'http://127.0.0.1:{port}/json/version', timeout=2).read())
            logger.info('Reusing hidden browser on port %s', port)
            return endpoint
        except Exception:
            (self.data_dir / 'DevToolsActivePort').unlink(missing_ok=True)
            return None

    async def _launch_any(self):
        executables = find_browsers()
        if not executables:
            raise BrowserUnavailable('Instale o Microsoft Edge ou o Google Chrome para usar as janelas do Lua OS.')
        attempts = [(e, m) for e in executables for m in ('--headless=new', '--headless')]
        reasons = []
        for round in range(2):
            codes = []
            for index, (executable, mode) in enumerate(attempts):
                if round == 0 and index == 1:
                    await asyncio.to_thread(self._kill_stale)  # Usual cause of an instant exit: an orphan holding the profile.
                    await asyncio.sleep(1)
                    endpoint = await self._existing()
                    if endpoint:
                        return endpoint
                try:
                    return await self._launch(executable, mode)
                except BrowserUnavailable as exc:
                    codes.append(exc.code)
                    reasons.append(f'{Path(executable).name} {mode}: {exc}')
                    logger.warning('Hidden browser attempt failed: %s', reasons[-1])
            if round == 0 and codes and all(code == PROFILE_IN_USE for code in codes):
                # Something we cannot end still locks the profile: continue with a fresh one rather than not working.
                self._new_profile()
                continue
            break
        raise BrowserUnavailable(f'Não foi possível abrir o navegador das janelas ({reasons[-1]}). Detalhes em {self.log_path}')

    def _new_profile(self):
        number = 2
        while (self.root / f'browser-{number}').exists():
            number += 1
        self.data_dir = self.root / f'browser-{number}'
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.choice.write_text(self.data_dir.name, encoding='utf-8')
        self._log(f'Perfil em uso por outro processo; usando um perfil novo: {self.data_dir}')
        logger.warning('Hidden browser profile locked; switched to %s', self.data_dir)

    def _log(self, text):
        try:
            with open(self.log_path, 'a', encoding='utf-8') as log:
                log.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {text}\n')
        except OSError:
            pass

    async def _launch(self, executable, mode):
        port_file = self.data_dir / 'DevToolsActivePort'
        port_file.unlink(missing_ok=True)
        args = [executable, mode, f'--user-data-dir={self.data_dir}', '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check',
                '--autoplay-policy=no-user-gesture-required', '--disable-features=Translate,MediaRouter', '--lang=pt-BR', '--window-size=1280,800', 'about:blank']
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        log = open(self.log_path, 'ab')
        log.write(f'\n--- {time.strftime("%Y-%m-%d %H:%M:%S")} {subprocess.list2cmdline(args)}\n'.encode())
        log.flush()
        try:
            self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=flags)
        except OSError as exc:
            raise BrowserUnavailable(f'não abriu: {exc}') from exc
        finally:
            log.close()
        import atexit
        atexit.register(self.process.terminate)  # Quitting from the tray must not leave the hidden browser running.
        for _ in range(300):
            endpoint = self._endpoint()
            if endpoint:
                return endpoint
            if self.process.poll() is not None:
                code = self.process.returncode
                self._log(f'saiu com código {code}' + (' (perfil em uso por outro processo)' if code == PROFILE_IN_USE else ''))
                raise BrowserUnavailable(f'fechou ao iniciar, código {code}' + (', perfil em uso' if code == PROFILE_IN_USE else ''), code)
            await asyncio.sleep(.1)
        self.process.kill()
        raise BrowserUnavailable('não respondeu em 30 s')

    def _kill_stale(self):
        """End browser processes started by earlier runs with this app's profiles, never the user's own browser."""
        root = str(self.root)
        try:
            if sys.platform == 'win32':
                script = ("$root = '" + root.lower().replace("'", "''") + "'; $n = 0; "
                          "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'msedge.exe' -or $_.Name -eq 'chrome.exe') -and $_.CommandLine -and $_.CommandLine.ToLower().Contains($root) } | "
                          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ }; \"processos encerrados: $n\"")
                # -EncodedCommand avoids any quoting problem with paths and the script itself.
                encoded = base64.b64encode(script.encode('utf-16-le')).decode()
                shell = Path(os.environ.get('SYSTEMROOT', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
                result = subprocess.run([str(shell) if shell.is_file() else 'powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                                        capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
                self._log(f'limpeza de processos antigos: {(result.stdout or result.stderr).strip()[:300]}')
            else:
                result = subprocess.run(['pgrep', '-f', '--', f'--user-data-dir={root}'], capture_output=True, text=True, timeout=10)
                pids = [int(pid) for pid in result.stdout.split() if int(pid) != os.getpid()]
                for pid in pids:
                    os.kill(pid, 9)
                self._log(f'limpeza de processos antigos: processos encerrados: {len(pids)}')
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            self._log(f'limpeza de processos antigos falhou: {exc}')
            logger.exception('Could not end stale hidden browsers')

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
