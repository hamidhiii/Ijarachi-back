from django.contrib.auth import get_user_model
from rest_framework import generics
from rest_framework.permissions import AllowAny, IsAuthenticated
from apps.catalog.models import Item
from apps.catalog.serializers import ItemListSerializer
from ..serializers import ProfileSerializer, PublicUserSerializer
from ..models import Profile

User = get_user_model()


class ProfileView(generics.RetrieveUpdateAPIView):
    """
    GET/PATCH /api/v1/profile/
    Просмотр и редактирование своего профиля.
    """
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        profile, _ = Profile.objects.get_or_create(user=self.request.user)
        return profile


class PublicUserView(generics.RetrieveAPIView):
    serializer_class = PublicUserSerializer
    permission_classes = [AllowAny]
    queryset = User.objects.select_related('profile').filter(is_active=True)


class PublicUserListingsView(generics.ListAPIView):
    serializer_class = ItemListSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return (
            Item.objects
            .filter(owner_id=self.kwargs['pk'], status=Item.STATUS_APPROVED)
            .select_related('category', 'owner__profile')
            .prefetch_related('images')
        )
