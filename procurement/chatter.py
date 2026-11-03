from chatter import register
from procurement.models import PurchaseOrder, Vendor
from utils.permissions import ProcurementPermission

register(Vendor, permission_classes=[ProcurementPermission])
register(PurchaseOrder, name="purchaseorder", permission_classes=[ProcurementPermission])
