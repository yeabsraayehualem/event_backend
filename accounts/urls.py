from django.urls import path

from . import admin_views, views

urlpatterns = [
    path("login/", views.Authenticate.as_view(), name="api_login"),
    path("logout/", views.LogountView.as_view(), name="api_logout"),
    path("csrf/", views.CsrfToken.as_view(), name="csrf_token"),
    path("profile/", views.MyAccount.as_view(), name="my_profile"),
    path("profile/password/", admin_views.ChangeOwnPassword.as_view(), name="my_password"),
    path("users/options/", admin_views.UserOptions.as_view(), name="user-options"),
    path("users/", admin_views.UserList.as_view(), name="user-list"),
    path("users/<int:pk>/", admin_views.UserDetail.as_view(), name="user-detail"),
    path("users/<int:pk>/password/", admin_views.UserPasswordReset.as_view(), name="user-password"),
]
