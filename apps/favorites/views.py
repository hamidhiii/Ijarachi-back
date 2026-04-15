from rest_framework import generics, permissions, status
from rest_framework.response import Response
from .models import FavoriteItem
from .serializers import FavoriteItemSerializer

class FavoriteItemListView(generics.ListAPIView):
    """
    List user's favorite items.
    """
    serializer_class = FavoriteItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return FavoriteItem.objects.filter(user=self.request.user).select_related('item', 'item__owner__profile')

class FavoriteAddView(generics.CreateAPIView):
    """
    Add an item to favorites.
    """
    serializer_class = FavoriteItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        item_id = serializer.validated_data['item_id']
        FavoriteItem.objects.get_or_create(user=self.request.user, item_id=item_id)

class FavoriteRemoveView(generics.DestroyAPIView):
    """
    Remove an item from favorites by item_id.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get_object(self):
        item_id = self.kwargs.get('item_id')
        return generics.get_object_or_404(FavoriteItem, user=self.request.user, item_id=item_id)
