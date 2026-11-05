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
    return JsonResponse({'name': 'Lua MediaPaper', 'version': '1.1.0', 'desktop': desktop, 'startup': startup, 'maxUploadMB': 30})

@ensure_csrf_cookie
@require_http_methods(['GET', 'PATCH'])
def wallpaper(request):
    from app.wallpaper import read_state, update_state, validate_changes, Conflict
    from django.http import HttpResponse
    if request.method == 'GET':
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
        except Conflict:
            response = JsonResponse(read_state(), status=409)
        except (ValueError, TypeError):
            return JsonResponse({'error': 'Configuração inválida. Confira o link e as preferências.'}, status=400)
    response['Cache-Control'] = 'no-store'
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
