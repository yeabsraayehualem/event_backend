from chatter import register
from hr.models import Employee
from utils.permissions import HRPermission

register(Employee, permission_classes=[HRPermission])
