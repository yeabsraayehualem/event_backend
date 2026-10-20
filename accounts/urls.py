from django.urls import path 
from . import views


urlpatterns = [
        path("login/",views.Authenticate.as_view(),name="api_login"),
        path("logout/",views.LogountView.as_view(),name="api_logout"),
        path("csrf/",views.CsrfToken.as_view(),name="csrf_token"),
        path("profile/",views.MyAccount.as_view(), name="my_profile")
        ]
