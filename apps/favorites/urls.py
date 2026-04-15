from django.urls import path
from .views import FavoriteItemListView, FavoriteAddView, FavoriteRemoveView

urlpatterns = [
    path('favorites/', FavoriteItemListView.as_view(), name='favorite-list'),
    path('favorites/add/', FavoriteAddView.as_view(), name='favorite-add'),
    path('favorites/remove/<int:item_id>/', FavoriteRemoveView.as_view(), name='favorite-remove'),
]
