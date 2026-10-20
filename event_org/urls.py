from django.contrib import admin
from django.http import JsonResponse
from django.urls import path,include
from django.conf import settings
from django.conf.urls.static import static


def health(request):
    return JsonResponse({
        "status": "success",
        "message": "Event Org API is running",
    })


urlpatterns = [
    path("api/v1/health/", health, name="health"),
    path("admin/", admin.site.urls),
    path("api/v1/user/",include("accounts.urls")),
    path("api/v1/crm/",include("crm.urls")),
    path("api/v1/event/", include("event.urls")),
    path("api/v1/finance/", include("finance.urls")),
    path("api/v1/website/",include("website.urls"))
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
