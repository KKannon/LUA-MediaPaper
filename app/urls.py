from django.urls import path, re_path
from . import views

urlpatterns = [
    path('api/status', views.status),
    path('api/startup', views.startup),
    path('api/convert', views.convert),
    path('api/convert-pdf', views.convert_pdf),
    path('api/wallpaper', views.wallpaper),
    path('api/youtube', views.youtube),
    path('media/<str:filename>', views.downloaded_media),
    path('api/monitors', views.monitors),
    path('api/monitors/<str:device_id>', views.monitor_device),
    re_path(r'^(?:|home/?|live/?|definicoes/?|mais/?|mais/epub-pdf/?|mais/pdf-epub/?|monitor/?)$', views.player),
]
