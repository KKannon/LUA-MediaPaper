from django.urls import path, re_path
from . import views

urlpatterns = [
    path('api/status', views.status),
    path('api/startup', views.startup),
    path('api/convert', views.convert),
    path('api/wallpaper', views.wallpaper),
    re_path(r'^(?:|home/?|live/?|definicoes/?|mais/?|mais/epub-pdf/?)$', views.player),
]
