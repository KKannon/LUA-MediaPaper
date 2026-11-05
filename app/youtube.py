"""Single-job YouTube importer with bounded cache lifetime and atomic activation."""
import json
import logging
import math
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from django.conf import settings
from app.wallpaper import _connection, read_state, update_state, Conflict

logger = logging.getLogger(__name__)
ACTIVE = ('checking', 'downloading', 'processing')
FORMAT = 'bestvideo[height<=2160]+bestaudio/best[height<=2160]'
RESERVE = 512 * 1024 * 1024
_worker = None
_worker_guard = threading.Lock()
_media_guard = threading.RLock()
_initialized = set()
_cleanup_pending = False
_last_cleanup = 0

class ImportError(ValueError):
    pass

class Busy(ImportError):
    pass

class Cancelled(Exception):
    pass

def normalize_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ImportError('Informe um link válido do YouTube.')
    parsed = urlparse(value.strip())
    host = (parsed.hostname or '').lower()
    if parsed.scheme not in ('https', 'http') or parsed.username or parsed.password:
        raise ImportError('Informe um link HTTP ou HTTPS do YouTube, sem credenciais.')
    video_id = None
    if host in ('youtu.be', 'www.youtu.be'):
        video_id = parsed.path.strip('/')
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
        if parsed.path == '/watch':
            video_id = parse_qs(parsed.query).get('v', [''])[0]
        else:
            match = re.fullmatch(r'/(?:shorts|embed|live)/([A-Za-z0-9_-]{11})/?', parsed.path)
            video_id = match[1] if match else None
    if not video_id or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        raise ImportError('Use o link de um vídeo do YouTube, não uma playlist ou canal.')
    return f'https://www.youtube.com/watch?v={video_id}'

def validate_metadata(info):
    duration = info.get('duration')
    if info.get('_type') in ('playlist', 'multi_video') or info.get('is_live') or info.get('live_status') in ('is_live', 'is_upcoming', 'post_live'):
        raise ImportError('Use um vídeo gravado de até 20 minutos. Lives e playlists não são aceitas.')
    if isinstance(duration, bool) or not isinstance(duration, (float, int)) or not math.isfinite(duration) or duration <= 0:
        raise ImportError('Não foi possível confirmar a duração deste vídeo.')
    if duration > 1200:
        raise ImportError('Este vídeo ultrapassa o limite de 20 minutos. Nenhum download foi iniciado.')
    return duration

def tool(name):
    suffix = '.exe' if sys.platform == 'win32' else ''
    bundled = Path(getattr(sys, '_MEIPASS', settings.BASE_DIR)) / 'tools' / (name + suffix)
    executable = str(bundled) if bundled.is_file() else shutil.which(name)
    if not executable:
        raise ImportError(f'O servidor precisa de {name} para preparar vídeos do YouTube.')
    return executable

def _paths():
    root = Path(settings.LUAMP_DATA_DIR).resolve()
    media, staging = root / 'media', root / '.downloads'
    media.mkdir(parents=True, exist_ok=True)
    staging.mkdir(parents=True, exist_ok=True)
    return media, staging

def read_job():
    connection = _connection()
    try:
        row = connection.execute('SELECT payload FROM youtube_job WHERE id=1').fetchone()
        return json.loads(row[0]) if row else {'status':'idle'}
    finally:
        connection.close()

def change_job(job_id, **changes):
    connection = _connection()
    try:
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT payload FROM youtube_job WHERE id=1').fetchone()
        current = json.loads(row[0]) if row else {}
        if current.get('id') == job_id and current.get('status') in ACTIVE:
            current.update(changes)
            connection.execute('UPDATE youtube_job SET payload=? WHERE id=1', (json.dumps(current, ensure_ascii=False),))
        connection.commit()
    finally:
        connection.close()

def cancel():
    current = read_job()
    if current.get('status') in ACTIVE:
        change_job(current['id'], status='cancelled', message='Download cancelado.')
    return read_job()

def _safe_remove_work(path):
    global _cleanup_pending
    _, staging = _paths()
    # Never recursively remove a computed path outside this application's staging root.
    if path.resolve().parent != staging.resolve() or not re.fullmatch(r'[a-f0-9]{32}', path.name):
        return
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass
    except OSError:
        _cleanup_pending = True

def cleanup_media():
    global _cleanup_pending
    with _media_guard:
        media_dir, _ = _paths()
        active = read_state()['media']['url']
        _cleanup_pending = False
        for path in media_dir.iterdir():
            if not re.fullmatch(r'[a-f0-9]{32}\.mp4', path.name) or active == '/media/' + path.name:
                continue
            try:
                path.unlink()
            except OSError:
                _cleanup_pending = True

def retry_cleanup():
    global _last_cleanup
    if _cleanup_pending and time.monotonic() - _last_cleanup > 3:
        _last_cleanup = time.monotonic()
        cleanup_media()
        _, staging = _paths()
        current = read_job()
        for path in staging.iterdir():
            if path.is_dir() and not (_worker is not None and _worker.is_alive() and path.name == current.get('id')):
                _safe_remove_work(path)

def initialize():
    root = str(Path(settings.LUAMP_DATA_DIR).resolve())
    if root in _initialized:
        return
    _initialized.add(root)
    job = read_job()
    if job.get('status') in ACTIVE:
        change_job(job['id'], status='error', message='O aplicativo foi reiniciado. Tente baixar o vídeo novamente.')
    cleanup_media()
    _, staging = _paths()
    for directory in staging.iterdir():
        if directory.is_dir():
            _safe_remove_work(directory)

def _check_cancelled(job_id):
    current = read_job()
    if current.get('id') != job_id or current.get('status') not in ACTIVE:
        raise Cancelled()

def _probe(path):
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    result = subprocess.run([tool('ffprobe'), '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,height', '-of', 'json', str(path)], capture_output=True, text=True, timeout=60, check=True, creationflags=flags)
    info = json.loads(result.stdout)
    duration = float(info.get('format', {}).get('duration', 0))
    if not math.isfinite(duration) or not 0 < duration <= 1201:
        raise ImportError('O arquivo recebido não corresponde a um vídeo de até 20 minutos.')
    height = max((stream.get('height', 0) for stream in info.get('streams', []) if stream.get('codec_type') == 'video'), default=0)
    if not 0 < height <= 2160:
        raise ImportError('O arquivo recebido não possui uma resolução de vídeo válida até 4K.')
    return duration, height

def _run(job):
    media_dir, staging = _paths()
    work = staging / job['id']
    last_update = 0
    def progress(data):
        nonlocal last_update
        if time.monotonic() - last_update < .35 and data.get('status') != 'finished':
            return
        _check_cancelled(job['id'])
        if shutil.disk_usage(staging).free < RESERVE:
            raise ImportError('Espaço livre insuficiente. O download foi interrompido e os arquivos temporários serão apagados.')
        last_update = time.monotonic()
        total = data.get('total_bytes') or data.get('total_bytes_estimate')
        percent = min(99, round(data.get('downloaded_bytes', 0) / total * 100)) if total else None
        change_job(job['id'], status='downloading', progress=percent, message='Baixando na melhor resolução disponível, até 4K…')
    def postprocess(data):
        _check_cancelled(job['id'])
        change_job(job['id'], status='processing', message='Preparando o vídeo para reprodução…', progress=None)
    def duration_filter(info, *, incomplete):
        if not incomplete:
            validate_metadata(info)
        return None
    try:
        work.mkdir()
        from yt_dlp import YoutubeDL
        options = {'format':FORMAT, 'format_sort':['res:2160', 'fps'], 'noplaylist':True, 'ignoreerrors':False, 'cachedir':False,
                   'outtmpl':str(work / 'source.%(ext)s'), 'merge_output_format':'mp4',
                   'ffmpeg_location':str(Path(tool('ffmpeg')).parent), 'js_runtimes':{'node':{'path':tool('node')}},
                   'postprocessors':[{'key':'FFmpegVideoRemuxer','preferedformat':'mp4'}],
                   'postprocessor_args':{'ffmpeg_o':['-movflags','+faststart']},
                   'progress_hooks':[progress], 'postprocessor_hooks':[postprocess], 'match_filter':duration_filter,
                   'socket_timeout':15, 'retries':2, 'fragment_retries':2, 'extractor_retries':1,
                   'quiet':True, 'no_warnings':True, 'writethumbnail':False, 'writeinfojson':False}
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(job['url'], download=False)
            if not info:
                raise ImportError('O YouTube não disponibilizou este vídeo.')
            validate_metadata(info)
            _check_cancelled(job['id'])
            estimate = sum(item.get('filesize') or item.get('filesize_approx') or 0 for item in info.get('requested_formats', [info]))
            if shutil.disk_usage(staging).free < estimate * 2 + RESERVE:
                raise ImportError('Não há espaço livre suficiente para preparar este vídeo na melhor resolução.')
            change_job(job['id'], title=str(info.get('title') or 'Vídeo do YouTube')[:150], duration=info['duration'], status='downloading', message='Baixando vídeo e áudio…')
            downloader.process_ie_result(info, download=True)
        candidate = work / 'source.mp4'
        if not candidate.is_file():
            raise ImportError('Não foi possível preparar um arquivo de vídeo reproduzível.')
        duration, height = _probe(candidate)
        _check_cancelled(job['id'])
        video_id = job['url'].split('v=')[1]
        title = str(info.get('title') or 'Vídeo do YouTube')[:150]
        media = {'id':'youtube-' + video_id, 'name':title, 'description':f'YouTube · {height}p · {int(duration)//60:02d}:{int(duration)%60:02d}',
                 'url':'/media/' + job['id'] + '.mp4', 'sourceUrl':job['url'], 'type':'video', 'thumbnail':f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'}
        with _media_guard:
            destination = media_dir / (job['id'] + '.mp4')
            candidate.replace(destination)
            try:
                update_state({'media':media}, download_id=job['id'])
            except Conflict:
                destination.unlink(missing_ok=True)
                raise Cancelled()
            cleanup_media()
    except (Cancelled, Conflict):
        change_job(job['id'], status='cancelled', message='Download cancelado.')
    except Exception as exc:
        logger.exception('YouTube import failed')
        message = str(exc) if isinstance(exc, ImportError) else 'Não foi possível baixar este vídeo. O YouTube pode estar bloqueando o acesso ou o vídeo pode ser restrito.'
        change_job(job['id'], status='error', message=message, progress=None)
    finally:
        _safe_remove_work(work)

def start(url):
    global _worker
    canonical = normalize_url(url)
    initialize()
    for name in ('ffmpeg', 'ffprobe', 'node'):
        tool(name)
    with _worker_guard:
        if _worker is not None and _worker.is_alive():
            raise Busy('Já existe um download em andamento. Cancele-o ou aguarde a conclusão.')
        job = {'id':uuid.uuid4().hex, 'url':canonical, 'status':'checking', 'progress':None, 'message':'Verificando a duração e as resoluções disponíveis…'}
        connection = _connection()
        try:
            connection.execute('INSERT OR REPLACE INTO youtube_job VALUES (1, ?)', (json.dumps(job, ensure_ascii=False),))
            connection.commit()
        finally:
            connection.close()
        _worker = threading.Thread(target=_run, args=(job,), daemon=True, name='lua-youtube')
        _worker.start()
        return job
