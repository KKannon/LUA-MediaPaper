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
    parser.add_argument('--host', default='0.0.0.0', help='Address to listen on. 0.0.0.0 exposes the app on the local network; use 127.0.0.1 for this computer only')
    parser.add_argument('--port', default=8765, type=int)
    parser.add_argument('--background', action='store_true', help='Start in the tray without opening the browser')
    parser.add_argument('--no-autostart', action='store_true', help='Do not register startup on first launch')
    parser.add_argument('--smoke-test', action='store_true', help='Test bundled routes, resources and conversion, then exit')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535')
    desktop = sys.platform == 'win32' and not args.server and not args.smoke_test
    os.environ['DJANGO_SETTINGS_MODULE'] = 'mediapaper.settings'
    os.environ['LUAMP_DESKTOP'] = '1' if desktop else '0'
    os.environ['LUAMP_PORT'] = str(args.port)
    os.environ['LUAMP_HOST'] = args.host
    if getattr(sys, 'frozen', False):
        os.environ.setdefault('LUAMP_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'LuaMediaPaper' / 'data'))
    # Accept this computer's own names and LAN addresses; other Host headers stay blocked.
    from app.network import allowed_hosts, network_urls
    os.environ.setdefault('LUAMP_ALLOWED_HOSTS', allowed_hosts(args.host))
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
        for route in ('/', '/live', '/definicoes', '/mais', '/mais/epub-pdf', '/mais/pdf-epub', '/api/status'):
            if client.get(route).status_code != 200:
                raise RuntimeError('Route failed: ' + route)
        pdf = convert_epub(sample_epub())
        if 'Olá' not in PdfReader(BytesIO(pdf)).pages[0].extract_text():
            raise RuntimeError('PDF conversion failed')
        from app.pdf_epub import convert_pdf
        from zipfile import ZipFile
        epub = convert_pdf(pdf)
        if 'Olá' not in ZipFile(BytesIO(epub)).read('OEBPS/text/section0001.xhtml').decode():
            raise RuntimeError('EPUB conversion failed')
        # The portable build must ship everything the YouTube importer needs.
        from app.youtube import tool
        import subprocess, yt_dlp, yt_dlp_ejs
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        tools = {}
        for name, option in (('ffmpeg', '-version'), ('ffprobe', '-version'), ('node', '--version')):
            result = subprocess.run([tool(name), option], capture_output=True, text=True, timeout=60, creationflags=flags)
            if result.returncode:
                raise RuntimeError('Tool failed: ' + name)
            tools[name] = result.stdout.split('\n')[0].strip()
        report = {'ok': True, 'routes': 7, 'pdfBytes': len(pdf), 'epubBytes': len(epub), 'static': (settings.BASE_DIR / 'static/frontend/index.html').exists(), 'wallpapers': len(list((settings.BASE_DIR / 'static/wallpapers').glob('*.jpg'))), 'ytDlp': yt_dlp.version.__version__, 'tools': tools}
        Path('lua-smoke-test.json').write_text(json.dumps(report), encoding='utf-8')
        return
    local_host = '127.0.0.1' if args.host in ('0.0.0.0', '::', '') else args.host
    url = f'http://{local_host}:{args.port}/'
    from app.youtube import initialize
    initialize()
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
    logging.info('Listening on %s:%s; network: %s', args.host, args.port, ', '.join(network_urls(args.host, args.port)) or 'none')
    if desktop:
        threading.Thread(target=server.run, daemon=True).start()
        from app.desktop import run_tray
        run_tray(server, url, background=args.background, autostart=not args.no_autostart)
    else:
        print(f'Lua MediaPaper: {url}', flush=True)
        for address in network_urls(args.host, args.port):
            print(f'Na rede: {address}', flush=True)
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
