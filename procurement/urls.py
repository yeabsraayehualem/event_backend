from django.urls import path

from procurement import views

urlpatterns = [
    path("options/", views.ProcurementOptions.as_view(), name="procurement-options"),
    path("categories/", views.VendorCategoryList.as_view(), name="vendor-categories"),
    path("vendors/", views.VendorList.as_view(), name="vendor-list"),
    path("vendors/<int:pk>/", views.VendorDetail.as_view(), name="vendor-detail"),
    path("vendors/<int:vendor_pk>/documents/", views.VendorDocuments.as_view(), name="vendor-documents"),
    path("vendors/<int:vendor_pk>/documents/<int:pk>/", views.VendorDocumentDetail.as_view(), name="vendor-document"),
    path("purchase-orders/", views.PurchaseOrderList.as_view(), name="purchase-order-list"),
    path("purchase-orders/<int:pk>/", views.PurchaseOrderDetail.as_view(), name="purchase-order-detail"),
    path("purchase-orders/<int:pk>/transition/", views.PurchaseOrderTransition.as_view(), name="purchase-order-transition"),
    path("events/<int:event_pk>/", views.EventProcurementSummary.as_view(), name="event-procurement"),
]
