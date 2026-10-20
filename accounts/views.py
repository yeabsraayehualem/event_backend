from email import message

from accounts.models import User
from accounts.serializer import UserSerializer
from rest_framework.views import APIView
from rest_framework import status
from utils.formatter import Formatter
from utils.views import InternalView
from rest_framework.response import Response
from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie



@method_decorator(ensure_csrf_cookie, name="dispatch")
class Authenticate(APIView):
    authentication_classes = []
    permission_classes = []


    def post(self, request, *args, **kwargs):
        phone = request.data.get("phone")
        password = request.data.get("password")

        if not phone or not password:
            return Response(
                Formatter.error_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                    message="Phone and password are required",
                    data=None,
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(
            request,
            phone=phone,
            password=password,
        )

        if user is None:
            return Response(
                Formatter.error_response(
                    status_code=401,
                    message="Invalid phone number or password",
                    data=None,
                ),
                status=status.HTTP_401_UNAUTHORIZED,
            )

        login(request, user)

        return Response(
            Formatter.success(
                status_code=200,
                message="Authentication successful",
                data=UserSerializer(user).data,
            ),
            status=status.HTTP_200_OK,
        )


class CsrfToken(APIView):
    authentication_classes = []
    permission_classes = []

    @method_decorator(ensure_csrf_cookie)
    def get(self, request, *args, **kwargs):
        return Response({"csrf_token": get_token(request._request)})


class LogountView(InternalView):
    def post(self,request,*a,**kw):
        logout(request)
        return Response(Formatter.success(data=None,message="Logout Successfull!!",status_code=401))


class MyAccount(InternalView):
    userSerialiser = UserSerializer

    def get(self,request,*args,**kw):
        user = request.user
        serializer = self.userSerialiser(user)

        data = Formatter.success(data=serializer.data)
        print(data)

        return Response(data)





