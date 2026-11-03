from accounts.admin_views import IsUserAdmin
from accounts.models import User
from chatter import register

register(User, name="user", permission_classes=[IsUserAdmin])
