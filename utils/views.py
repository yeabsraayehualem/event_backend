from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from utils.permissions import IsSalesOrSuper, IsSuperUser
from . import permissions
class InternalView(APIView):

   permission_classes = [IsAuthenticated] 


class SuperView(InternalView):
    permission_classes = [IsSuperUser]


class SalesView(InternalView):
    permission_classes = [IsSalesOrSuper]
