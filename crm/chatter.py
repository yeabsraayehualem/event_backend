from chatter import register
from crm.models import Lead
from utils.permissions import IsLeadAssigneeOrSuper, IsSalesOrSuper

register(Lead, permission_classes=[IsSalesOrSuper, IsLeadAssigneeOrSuper])
