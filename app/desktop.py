"""Windows tray and per-user startup integration (no administrator required)."""
import os
import subprocess
import sys
from pathlib import Path

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'LuaMediaPaper'

def startup_enabled():
    if sys.platform != 'win32':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except OSError:
        return False

def set_startup(enabled):
    if sys.platform != 'win32':
        raise OSError('Windows only')
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            args = [sys.executable]
            if not getattr(sys, 'frozen', False):
                args.append(str(Path(__file__).resolve().parent.parent / 'launcher.py'))
            args.append('--background')
            args.extend(['--port', os.environ.get('LUAMP_PORT', '8765')])
            args.extend(['--host', os.environ.get('LUAMP_HOST', '0.0.0.0')])
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, subprocess.list2cmdline(args))
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass

def icon_image(size=128):
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 4, fill='#101113')
    draw.ellipse((size*.18, size*.15, size*.83, size*.83), fill='#c1e697')
    draw.ellipse((size*.40, size*.05, size*.93, size*.65), fill='#101113')
    return image

def run_tray(server, url, background=False, autostart=True):
    import pystray
    import webbrowser
    # Register on first normal launch; never change startup during smoke tests.
    state_dir = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'LuaMediaPaper'
    state_dir.mkdir(parents=True, exist_ok=True)
    first_run = state_dir / 'initialized'
    if not first_run.exists():
        if autostart:
            set_startup(True)
        first_run.write_text('1', encoding='utf-8')
    elif startup_enabled():
        set_startup(True)  # Refresh the path if the portable executable was moved.
    def open_app(icon=None, item=None):
        webbrowser.open(url)
    def open_settings(icon=None, item=None):
        webbrowser.open(url + 'definicoes')
    def open_screen(icon=None, item=None):
        webbrowser.open(url + 'screen')
    from app.network import network_urls
    def network_url():
        urls = network_urls(os.environ.get('LUAMP_HOST', '0.0.0.0'), os.environ.get('LUAMP_PORT', '8765'))
        return urls[0] if urls else None
    def open_network(icon=None, item=None):
        if network_url():
            webbrowser.open(network_url() + 'screen')
    def toggle_startup(icon, item):
        set_startup(not startup_enabled())
        icon.update_menu()
    def quit_app(icon, item):
        icon.stop()
    tray = pystray.Icon('LuaMediaPaper', icon_image(), 'Lua MediaPaper', menu=pystray.Menu(
        pystray.MenuItem('Abrir Lua MediaPaper', open_app, default=True),
        pystray.MenuItem('Abrir /screen', open_screen),
        pystray.MenuItem('Definições', open_settings),
        pystray.MenuItem(lambda item: 'Na rede: ' + (network_url() or 'indisponível').removeprefix('http://').rstrip('/'), open_network, enabled=lambda item: network_url() is not None),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Iniciar com o Windows', toggle_startup, checked=lambda item: startup_enabled()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Encerrar', quit_app),
    ))
    if not background:
        open_app()
    try:
        tray.run()
    finally:
        server.close()
