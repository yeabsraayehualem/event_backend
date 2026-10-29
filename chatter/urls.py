from django.urls import path

from chatter.views import RecordChatter

urlpatterns = [
    path("<str:model>/<int:pk>/", RecordChatter.as_view(), name="record-chatter"),
]
