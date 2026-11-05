from django.urls import path, re_path
from . import views

urlpatterns = [
    path('api/status', views.status),
    path('api/startup', views.startup),
    path('api/convert', views.convert),
    path('api/wallpaper', views.wallpaper),
    path('api/youtube', views.youtube),
    path('media/<str:filename>', views.downloaded_media),
    re_path(r'^(?:|home/?|live/?|definicoes/?|mais/?|mais/epub-pdf/?)$', views.player),
]
