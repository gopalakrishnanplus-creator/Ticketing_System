# task_manage/urls.py

from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(url='/tasks/create/', permanent=True)),
    path('tasks/', include('task_app.urls')),
    path('accounts/', include('django.contrib.auth.urls')),  # Linking to task_app URLs
    
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
