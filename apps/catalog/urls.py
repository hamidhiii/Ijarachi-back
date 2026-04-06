from django.urls import path
from .views import (
    CategoryListView,
    ItemListView,
    ItemDetailView,
    ItemCreateView,
    MyItemsView,
    ItemUpdateView,
    ItemImageUploadView,
)

urlpatterns = [
    # Public
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('catalog/', ItemListView.as_view(), name='item-list'),
    path('catalog/<int:pk>/', ItemDetailView.as_view(), name='item-detail'),

    # Private
    path('items/create/', ItemCreateView.as_view(), name='item-create'),
    path('items/my/', MyItemsView.as_view(), name='item-my-list'),
    path('items/<int:pk>/', ItemUpdateView.as_view(), name='item-update'),
    path('items/<int:item_id>/images/', ItemImageUploadView.as_view(), name='item-image-upload'),
    path('items/<int:item_id>/images/<int:image_id>/', ItemImageUploadView.as_view(), name='item-image-delete'),
]
