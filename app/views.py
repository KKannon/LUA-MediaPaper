import json
import logging
import os
import re
from io import BytesIO
from django.http import FileResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST, require_http_methods

logger = logging.getLogger(__name__)
MEDIA_TYPES = {'.mp4': 'video/mp4', '.m4v': 'video/mp4', '.webm': 'video/webm', '.mov': 'video/quicktime', '.jpg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif'}
UPLOAD_KINDS = {'.jpg': ('jpg', 'image'), '.jpeg': ('jpg', 'image'), '.png': ('png', 'image'), '.webp': ('webp', 'image'), '.gif': ('gif', 'gif'),
                '.mp4': ('mp4', 'video'), '.m4v': ('m4v', 'video'), '.webm': ('webm', 'video'), '.mov': ('mov', 'video')}
MAX_UPLOAD_MB = 500

@ensure_csrf_cookie
@require_GET
def player(request):
    return render(request, 'index.html')

@ensure_csrf_cookie
@require_GET
def status(request):
    desktop = os.environ.get('LUAMP_DESKTOP') == '1'
    startup = False
    if desktop:
        from app.desktop import startup_enabled
        startup = startup_enabled()
    from app.network import network_urls
    urls = network_urls(os.environ.get('LUAMP_HOST', '127.0.0.1'), os.environ.get('LUAMP_PORT', '8765'))
    from app.monitor import hub
    return JsonResponse({'name': 'Lua MediaPaper', 'version': '1.2.0', 'desktop': desktop, 'startup': startup, 'maxUploadMB': 30, 'networkUrls': urls,
                         'monitorPort': hub.port if hub.running() else None})

@ensure_csrf_cookie
@require_http_methods(['GET', 'PATCH'])
def wallpaper(request):
    from app.wallpaper import read_state, update_state, validate_changes, Conflict
    from django.http import HttpResponse
    if request.method == 'GET':
        from app.youtube import retry_cleanup
        retry_cleanup()
        state = read_state()
        etag = f'"lua-wallpaper-{state["revision"]}"'
        response = HttpResponse(status=304) if request.headers.get('If-None-Match') == etag else JsonResponse(state)
        response['ETag'] = etag
    else:
        if len(request.body) > 16 * 1024:
            return JsonResponse({'error': 'Configuração muito grande.'}, status=413)
        try:
            body = json.loads(request.body)
            changes = validate_changes(body)
            response = JsonResponse(update_state(changes, body.get('initialRevision')))
            if 'media' in changes:
                from app.youtube import cleanup_media
                cleanup_media()
        except Conflict:
            response = JsonResponse(read_state(), status=409)
        except (ValueError, TypeError):
            return JsonResponse({'error': 'Configuração inválida. Confira o link e as preferências.'}, status=400)
    response['Cache-Control'] = 'no-store'
    return response

@ensure_csrf_cookie
@require_http_methods(['GET', 'POST', 'DELETE'])
def youtube(request):
    from app import youtube as importer
    if request.method == 'GET':
        response = JsonResponse(importer.read_job())
    elif request.method == 'DELETE':
        response = JsonResponse(importer.cancel())
    else:
        try:
            if len(request.body) > 8192:
                raise ValueError()
            body = json.loads(request.body)
            if not isinstance(body, dict):
                raise ValueError()
            response = JsonResponse(importer.start(body.get('url')), status=202)
        except importer.Busy as exc:
            return JsonResponse({'error':str(exc)}, status=409)
        except (ValueError, TypeError) as exc:
            message = str(exc) if isinstance(exc, importer.ImportError) else 'Informe um link válido do YouTube.'
            return JsonResponse({'error':message}, status=400)
    response['Cache-Control'] = 'no-store'
    return response

@require_http_methods(['GET', 'HEAD'])
def downloaded_media(request, filename):
    from pathlib import Path
    from django.conf import settings
    from django.http import HttpResponse, StreamingHttpResponse, Http404
    from app.wallpaper import read_state
    from app.youtube import MEDIA_NAME
    if not re.fullmatch(MEDIA_NAME, filename) or read_state()['media']['url'] != '/media/' + filename:
        raise Http404()
    root = (Path(settings.LUAMP_DATA_DIR) / 'media').resolve()
    path = (root / filename).resolve()
    if path.parent != root or not path.is_file():
        raise Http404()
    size = path.stat().st_size
    start, end, code = 0, size - 1, 200
    header = request.headers.get('Range')
    if header:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', header)
        if not match or not any(match.groups()):
            return HttpResponse(status=416, headers={'Content-Range':f'bytes */{size}'})
        if match[1]:
            start = int(match[1])
            end = min(int(match[2]), size - 1) if match[2] else size - 1
        else:
            start = max(0, size - int(match[2]))
        if start > end or start >= size:
            return HttpResponse(status=416, headers={'Content-Range':f'bytes */{size}'})
        code = 206
    def chunks():
        try:
            with path.open('rb') as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = stream.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
        except FileNotFoundError:
            return
    response = HttpResponse(status=code, content_type=MEDIA_TYPES[path.suffix]) if request.method == 'HEAD' else StreamingHttpResponse(chunks(), status=code, content_type=MEDIA_TYPES[path.suffix])
    response['Content-Length'] = end - start + 1
    response['Accept-Ranges'] = 'bytes'
    response['Cache-Control'] = 'no-store'
    if code == 206:
        response['Content-Range'] = f'bytes {start}-{end}/{size}'
    return response

@require_POST
def startup(request):
    if os.environ.get('LUAMP_DESKTOP') != '1':
        return JsonResponse({'error': 'A inicialização com o Windows está disponível no aplicativo portátil.'}, status=400)
    if request.META.get('REMOTE_ADDR') not in ('127.0.0.1', '::1'):
        return JsonResponse({'error': 'Esta configuração só pode ser alterada no computador local.'}, status=403)
    try:
        body = json.loads(request.body)
        if type(body.get('enabled')) is not bool:
            raise ValueError()
        from app.desktop import set_startup
        set_startup(body['enabled'])
        return JsonResponse({'startup': body['enabled']})
    except (ValueError, TypeError, OSError):
        return JsonResponse({'error': 'Não foi possível atualizar a inicialização do Windows.'}, status=400)

@require_POST
def convert(request):
    upload = request.FILES.get('file')
    if upload is None or not upload.name.lower().endswith('.epub'):
        return JsonResponse({'error': 'Selecione um arquivo .epub válido.'}, status=400)
    if upload.size > 30 * 1024 * 1024:
        return JsonResponse({'error': 'O arquivo deve ter no máximo 30 MB.'}, status=413)
    from app.converter import convert_epub, InvalidEpub
    try:
        size = request.POST.get('pageSize', 'A4')
        font_size = int(request.POST.get('fontSize', '11'))
        if size not in ('A4', 'LETTER') or font_size not in (10, 11, 12, 14):
            raise ValueError('Opção de formatação inválida.')
        result = convert_epub(upload.read(), page_size=size, font_size=font_size)
    except (ValueError, InvalidEpub) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except Exception:
        logger.exception('EPUB conversion failed')
        return JsonResponse({'error': 'Não foi possível converter este EPUB. Confira se o arquivo está íntegro e sem DRM.'}, status=422)
    filename = re.sub(r'[^\w .-]', '', upload.name.rsplit('.', 1)[0])[:100] or 'livro'
    response = FileResponse(BytesIO(result), content_type='application/pdf', as_attachment=True, filename=filename + '.pdf')
    response['Cache-Control'] = 'no-store'
    return response

@require_POST
def convert_pdf(request):
    upload = request.FILES.get('file')
    if upload is None or not upload.name.lower().endswith('.pdf'):
        return JsonResponse({'error': 'Selecione um arquivo .pdf válido.'}, status=400)
    if upload.size > 30 * 1024 * 1024:
        return JsonResponse({'error': 'O arquivo deve ter no máximo 30 MB.'}, status=413)
    from app.pdf_epub import convert_pdf as convert, InvalidPdf
    try:
        title = request.POST.get('title', '').strip()[:200] or None
        result = convert(upload.read(), title=title)
    except InvalidPdf as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except Exception:
        logger.exception('PDF conversion failed')
        return JsonResponse({'error': 'Não foi possível converter este PDF. Confira se o arquivo está íntegro e sem senha.'}, status=422)
    filename = re.sub(r'[^\w .-]', '', upload.name.rsplit('.', 1)[0])[:100] or 'livro'
    response = FileResponse(BytesIO(result), content_type='application/epub+zip', as_attachment=True, filename=filename + '.epub')
    response['Cache-Control'] = 'no-store'
    return response

@ensure_csrf_cookie
@require_GET
def monitors(request):
    from app.monitor import hub
    response = JsonResponse(hub.snapshot())
    response['Cache-Control'] = 'no-store'
    return response

@require_http_methods(['PATCH', 'DELETE'])
def monitor_device(request, device_id):
    from app.monitor import hub
    local = request.META.get('REMOTE_ADDR') in ('127.0.0.1', '::1')
    # In the portable app, approving or removing a screen is reserved to the PC itself.
    if os.environ.get('LUAMP_DESKTOP') == '1' and not local:
        try:
            body = json.loads(request.body or b'{}')
        except ValueError:
            body = {}
        if request.method == 'DELETE' or 'approved' in body:
            return JsonResponse({'error': 'Aprove ou remova telas no próprio computador.'}, status=403)
    try:
        if request.method == 'DELETE':
            hub.forget(device_id)
            return JsonResponse({'ok': True})
        body = json.loads(request.body)
        if not isinstance(body, dict) or set(body) - {'name', 'side', 'offset', 'approved'}:
            raise ValueError('Alteração inválida.')
        return JsonResponse(hub.update(device_id, body))
    except KeyError:
        return JsonResponse({'error': 'Tela não encontrada.'}, status=404)
    except (ValueError, TypeError) as exc:
        return JsonResponse({'error': str(exc) or 'Alteração inválida.'}, status=400)

def _looks_valid(upload, extension, kind):
    """Content must match the extension: images are decoded, videos need a container signature."""
    upload.seek(0)
    head = upload.read(64)
    upload.seek(0)
    if kind == 'video':
        return head[:4] == b'\x1a\x45\xdf\xa3' or head[4:8] in (b'ftyp', b'moov', b'wide', b'mdat', b'free', b'skip')
    from PIL import Image
    try:
        with Image.open(upload) as image:
            image.verify()
            return image.format == {'jpg': 'JPEG', 'png': 'PNG', 'webp': 'WEBP', 'gif': 'GIF'}[extension]
    except Exception:
        return False
    finally:
        upload.seek(0)

@require_POST
def upload_media(request):
    import shutil
    import uuid
    from pathlib import Path
    from app import youtube
    from app.wallpaper import update_state
    upload = request.FILES.get('file')
    suffix = Path(upload.name).suffix.lower() if upload else ''
    if upload is None or suffix not in UPLOAD_KINDS:
        return JsonResponse({'error': 'Envie uma imagem (JPG, PNG, WebP), GIF ou vídeo (MP4, WebM, MOV).'}, status=400)
    if upload.size > MAX_UPLOAD_MB * 1024 * 1024:
        return JsonResponse({'error': f'O arquivo deve ter no máximo {MAX_UPLOAD_MB} MB.'}, status=413)
    extension, kind = UPLOAD_KINDS[suffix]
    if not _looks_valid(upload, extension, kind):
        return JsonResponse({'error': 'O conteúdo do arquivo não corresponde ao formato informado.'}, status=400)
    media_dir, _ = youtube._paths()
    if shutil.disk_usage(media_dir).free < upload.size + youtube.RESERVE:
        return JsonResponse({'error': 'Não há espaço livre suficiente no computador para este arquivo.'}, status=507)
    name = f'{uuid.uuid4().hex}.{extension}'
    partial = media_dir / (name + '.part')
    try:
        with partial.open('wb') as output:
            for chunk in upload.chunks():
                output.write(chunk)
    except OSError:
        partial.unlink(missing_ok=True)
        return JsonResponse({'error': 'Não foi possível salvar o arquivo.'}, status=500)
    title = re.sub(r'\s+', ' ', Path(upload.name).stem).strip()[:150] or 'Arquivo enviado'
    media = {'id': 'upload-' + name[:12], 'name': title, 'description': f'Arquivo do computador · {upload.size / 1024 / 1024:.1f} MB'.replace('.', ','), 'url': '/media/' + name, 'type': kind}
    with youtube._media_guard:
        partial.replace(media_dir / name)
        state = update_state({'media': media})
        youtube.cleanup_media()  # The previous upload or download is deleted to save space.
    return JsonResponse(state)

WEATHER_CODES = {0: 'Céu limpo', 1: 'Poucas nuvens', 2: 'Parcialmente nublado', 3: 'Nublado', 45: 'Neblina', 48: 'Neblina', 51: 'Garoa', 53: 'Garoa', 55: 'Garoa forte',
                 61: 'Chuva fraca', 63: 'Chuva', 65: 'Chuva forte', 66: 'Chuva congelante', 67: 'Chuva congelante', 71: 'Neve', 73: 'Neve', 75: 'Neve forte', 80: 'Pancadas de chuva',
                 81: 'Pancadas de chuva', 82: 'Temporal', 95: 'Trovoadas', 96: 'Trovoadas com granizo', 99: 'Trovoadas com granizo'}
_weather_cache = {}

def _fetch_json(url):
    from urllib.request import Request, urlopen
    with urlopen(Request(url, headers={'User-Agent': 'LuaMediaPaper'}), timeout=8) as response:
        return json.loads(response.read(1024 * 1024))

@require_GET
def weather_search(request):
    from urllib.parse import urlencode
    query = re.sub(r'\s+', ' ', request.GET.get('q', '')).strip()[:80]
    if len(query) < 2:
        return JsonResponse({'results': []})
    try:
        data = _fetch_json('https://geocoding-api.open-meteo.com/v1/search?' + urlencode({'name': query, 'count': 6, 'language': 'pt', 'format': 'json'}))
    except Exception:
        return JsonResponse({'error': 'Não foi possível buscar cidades agora. Verifique a internet.'}, status=502)
    results = []
    for item in data.get('results', []):
        label = ', '.join(dict.fromkeys(x for x in (item.get('name'), item.get('admin1'), item.get('country')) if x))
        results.append({'name': label[:120], 'lat': round(float(item['latitude']), 4), 'lon': round(float(item['longitude']), 4)})
    return JsonResponse({'results': results})

@require_GET
def weather(request):
    import time
    from urllib.parse import urlencode
    from app.wallpaper import read_state
    preferences = read_state()['preferences']
    city = preferences.get('city')
    if not preferences.get('weather') or not city:
        return JsonResponse({'enabled': False})
    key = (city['lat'], city['lon'])
    cached = _weather_cache.get(key)
    if not cached or time.monotonic() - cached[0] > 600:
        try:
            data = _fetch_json('https://api.open-meteo.com/v1/forecast?' + urlencode({'latitude': city['lat'], 'longitude': city['lon'], 'current': 'temperature_2m,weather_code,is_day', 'timezone': 'auto'}))
            current = data['current']
            cached = (time.monotonic(), {'temperature': round(current['temperature_2m']), 'code': current['weather_code'], 'day': bool(current.get('is_day', 1)),
                                         'description': WEATHER_CODES.get(current['weather_code'], '')})
            _weather_cache[key] = cached
        except Exception:
            if not cached:
                return JsonResponse({'enabled': True, 'city': city['name'], 'error': 'Temperatura indisponível no momento.'})
    return JsonResponse({'enabled': True, 'city': city['name'].split(',')[0], **cached[1]})
