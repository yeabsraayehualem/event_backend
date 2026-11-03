from chatter import register
from event.models import Event, Package, Plan, Project
from utils.permissions import CatalogPermission, IsPM, IsSalesOrSuper

register(Event, permission_classes=[IsSalesOrSuper])
register(Project, permission_classes=[IsPM])
register(Plan, permission_classes=[CatalogPermission])
register(Package, permission_classes=[CatalogPermission])
