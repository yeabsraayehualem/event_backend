# yourproject/middleware.py
from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware


class DevCsrfViewMiddleware(CsrfViewMiddleware):
    """Trust any Origin when DEBUG is on. Never active in production."""

    def _origin_verified(self, request):
        if settings.DEBUG:
            return True
        return super()._origin_verified(request)