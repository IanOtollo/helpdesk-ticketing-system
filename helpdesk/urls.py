from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

admin.site.site_header = "Mombasa County ICT Help Desk Administration"
admin.site.site_title = "ICT Help Desk Admin"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('tickets.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)