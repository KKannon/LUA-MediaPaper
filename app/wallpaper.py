"""Durable shared display state; one atomic transaction for each partial update."""
import json
import sqlite3
from pathlib import Path
from django.conf import settings

DEFAULT_MEDIA = {'id': 'forest', 'name': 'Entre a névoa', 'description': 'Um respiro em meio ao verde.', 'url': '/wallpapers/forest.jpg', 'type': 'image'}
DEFAULT_PREFERENCES = {'clock': True, 'date': True, 'muted': True, 'autoplay': True, 'fit': 'cover', 'dim': 0, 'hour24': True, 'keepAwake': True}

def _connection():
    directory = Path(settings.LUAMP_DATA_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / 'wallpaper.sqlite3', timeout=10)
    connection.execute('CREATE TABLE IF NOT EXISTS wallpaper (id INTEGER PRIMARY KEY CHECK (id = 1), revision INTEGER NOT NULL, payload TEXT NOT NULL)')
    connection.execute('INSERT OR IGNORE INTO wallpaper VALUES (1, 0, ?)', (json.dumps({'media': DEFAULT_MEDIA, 'preferences': DEFAULT_PREFERENCES}),))
    connection.commit()
    return connection

def read_state():
    connection = _connection()
    try:
        revision, raw = connection.execute('SELECT revision, payload FROM wallpaper WHERE id = 1').fetchone()
        result = json.loads(raw)
        result['preferences'] = {**DEFAULT_PREFERENCES, **result['preferences']}
        return {**result, 'revision': revision}
    finally:
        connection.close()

class Conflict(Exception):
    pass

def update_state(changes, initial_revision=None):
    connection = _connection()
    try:
        connection.execute('BEGIN IMMEDIATE')
        revision, raw = connection.execute('SELECT revision, payload FROM wallpaper WHERE id = 1').fetchone()
        if initial_revision is not None and initial_revision != revision:
            raise Conflict()
        state = json.loads(raw)
        if 'media' in changes:
            state['media'] = changes['media']
        state['preferences'] = {**DEFAULT_PREFERENCES, **state['preferences'], **changes.get('preferences', {})}
        connection.execute('UPDATE wallpaper SET revision = ?, payload = ? WHERE id = 1', (revision + 1, json.dumps(state, ensure_ascii=False)))
        connection.commit()
        return {**state, 'revision': revision + 1}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def validate_changes(body):
    from urllib.parse import urlparse
    if not isinstance(body, dict) or not body or set(body) - {'media', 'preferences', 'initialRevision'}:
        raise ValueError('Configuração de wallpaper inválida.')
    if 'initialRevision' in body and (type(body['initialRevision']) is not int or body['initialRevision'] != 0):
        raise ValueError('Revisão inicial inválida.')
    if not any(key in body for key in ('media', 'preferences')):
        raise ValueError('Nenhuma alteração enviada.')
    changes = {}
    if 'media' in body:
        media = body['media']
        if not isinstance(media, dict) or set(media) - {'id', 'name', 'description', 'url', 'type', 'thumbnail'}:
            raise ValueError('Mídia inválida.')
        for field, maximum in (('id', 100), ('name', 150), ('description', 300), ('url', 4096)):
            if not isinstance(media.get(field), str) or not media[field].strip() or len(media[field]) > maximum:
                raise ValueError('Dados da mídia inválidos.')
        if media.get('type') not in ('image', 'video', 'gif'):
            raise ValueError('Tipo de mídia inválido.')
        parsed = urlparse(media['url'])
        builtin = media['url'] in [f'/wallpapers/{name}.jpg' for name in ('forest', 'mountain', 'sea', 'dunes')]
        if not builtin and (parsed.scheme not in ('https', 'http') or not parsed.netloc or parsed.username or parsed.password):
            raise ValueError('Use um link HTTP ou HTTPS direto, sem credenciais.')
        changes['media'] = {key: media[key] for key in ('id', 'name', 'description', 'url', 'type')}
    if 'preferences' in body:
        preferences = body['preferences']
        if not isinstance(preferences, dict) or set(preferences) - set(DEFAULT_PREFERENCES):
            raise ValueError('Preferências inválidas.')
        for key, value in preferences.items():
            if key == 'fit':
                valid = value in ('cover', 'contain')
            elif key == 'dim':
                valid = type(value) is int and 0 <= value <= 70
            else:
                valid = type(value) is bool
            if not valid:
                raise ValueError('Valor de preferência inválido.')
        changes['preferences'] = preferences
    return changes
