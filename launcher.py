"""Lua MediaPaper: portable desktop application or standalone WSGI server."""
import argparse
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from urllib.request import urlopen

def main():
    parser = argparse.ArgumentParser(description='Lua MediaPaper')
    parser.add_argument('--server', action='store_true', help='Run as a server, without tray or startup integration')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', default=8765, type=int)
    parser.add_argument('--background', action='store_true', help='Start in the tray without opening the browser')
    parser.add_argument('--no-autostart', action='store_true', help='Do not register startup on first launch')
    parser.add_argument('--smoke-test', action='store_true', help='Test bundled routes, resources and conversion, then exit')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535')
    desktop = sys.platform == 'win32' and not args.server and not args.smoke_test
    if desktop and args.host != '127.0.0.1':
        parser.error('Desktop mode uses 127.0.0.1. Use --server for network access.')
    os.environ['DJANGO_SETTINGS_MODULE'] = 'mediapaper.settings'
    os.environ['LUAMP_DESKTOP'] = '1' if desktop else '0'
    os.environ['LUAMP_PORT'] = str(args.port)
    if getattr(sys, 'frozen', False):
        os.environ.setdefault('LUAMP_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'LuaMediaPaper' / 'data'))
    # Host validation remains explicit in network mode.
    os.environ.setdefault('LUAMP_ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1]')
    import django
    django.setup()
    from mediapaper.wsgi import application
    from waitress import create_server
    from whitenoise import WhiteNoise
    from django.conf import settings
    application = WhiteNoise(application, root=str(settings.BASE_DIR / 'static' / 'wallpapers'), prefix='wallpapers/')
    if args.smoke_test:
        from app.converter import convert_epub
        from app.tests import sample_epub
        from django.test import Client
        from pypdf import PdfReader
        from io import BytesIO
        client = Client(HTTP_HOST='localhost')
        for route in ('/', '/live', '/definicoes', '/mais', '/mais/epub-pdf', '/api/status'):
            if client.get(route).status_code != 200:
                raise RuntimeError('Route failed: ' + route)
        pdf = convert_epub(sample_epub())
        if 'Olá' not in PdfReader(BytesIO(pdf)).pages[0].extract_text():
            raise RuntimeError('PDF conversion failed')
        report = {'ok': True, 'routes': 6, 'pdfBytes': len(pdf), 'static': (settings.BASE_DIR / 'static/frontend/index.html').exists(), 'wallpapers': len(list((settings.BASE_DIR / 'static/wallpapers').glob('*.jpg')))}
        Path('lua-smoke-test.json').write_text(json.dumps(report), encoding='utf-8')
        return
    url = f'http://127.0.0.1:{args.port}/'
    try:
        server = create_server(application, host=args.host, port=args.port, threads=4, max_request_body_size=35*1024*1024, channel_timeout=180)
    except OSError:
        if desktop:
            try:
                with urlopen(url + 'api/status', timeout=2) as response:
                    existing = json.load(response)
                if existing.get('name') == 'Lua MediaPaper' and existing.get('desktop'):
                    if not args.background:
                        import webbrowser
                        webbrowser.open(url)
                    return
            except Exception:
                pass
        raise RuntimeError(f'A porta {args.port} já está em uso. Escolha outra usando --port.')
    if desktop:
        threading.Thread(target=server.run, daemon=True).start()
        from app.desktop import run_tray
        run_tray(server, url, background=args.background, autostart=not args.no_autostart)
    else:
        print(f'Lua MediaPaper: http://{args.host}:{args.port}/', flush=True)
        try:
            server.run()
        except KeyboardInterrupt:
            server.close()

if __name__ == '__main__':
    log_directory = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'LuaMediaPaper'
    if getattr(sys, 'frozen', False):
        log_directory.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=log_directory / 'lua.log', level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    else:
        logging.basicConfig(level=logging.INFO)
    try:
        main()
    except Exception as exc:
        logging.exception('Lua MediaPaper failed')
        if getattr(sys, 'frozen', False) and sys.platform == 'win32' and '--smoke-test' not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f'{exc}\n\nDetalhes em {log_directory / "lua.log"}', 'Lua MediaPaper', 16)
        raise
