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
    return JsonResponse({'name': 'Lua MediaPaper', 'version': '1.2.0', 'desktop': desktop, 'startup': startup, 'maxUploadMB': 30, 'networkUrls': urls})

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
    if not re.fullmatch(r'[a-f0-9]{32}\.mp4', filename) or read_state()['media']['url'] != '/media/' + filename:
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
    response = HttpResponse(status=code, content_type='video/mp4') if request.method == 'HEAD' else StreamingHttpResponse(chunks(), status=code, content_type='video/mp4')
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
