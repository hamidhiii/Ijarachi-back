from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from ..serializers import ProfileSerializer
from ..models import Profile


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
