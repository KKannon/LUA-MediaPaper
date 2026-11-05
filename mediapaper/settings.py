"""Settings shared by the portable desktop app and self-hosted server."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LUAMP_DATA_DIR = Path(os.environ.get('LUAMP_DATA_DIR', str(Path.home() / '.lua-mediapaper')))
SECRET_KEY = os.environ.get('LUAMP_SECRET_KEY') or secrets.token_urlsafe(48)
DEBUG = os.environ.get('LUAMP_DEBUG') == '1'
ALLOWED_HOSTS = [s.strip() for s in os.environ.get('LUAMP_ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1],testserver').split(',') if s.strip()]
INSTALLED_APPS = ['django.contrib.staticfiles', 'app']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'whitenoise.middleware.WhiteNoiseMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'mediapaper.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'static' / 'frontend'], 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request']}}]
WSGI_APPLICATION = 'mediapaper.wsgi.application'
DATABASES = {}
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
WHITENOISE_ROOT = BASE_DIR / 'static' / 'frontend'
WHITENOISE_MAX_AGE = 3600
DATA_UPLOAD_MAX_MEMORY_SIZE = 35 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
CSRF_TRUSTED_ORIGINS = [s for s in os.environ.get('LUAMP_CSRF_ORIGINS', '').split(',') if s]
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
