from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.runtime_modes import myid_stub_active

from ..models import Profile
from ..serializers import VerificationStatusSerializer


@extend_schema(
    request=None,
    responses={200: VerificationStatusSerializer},
    summary='Заглушка MyID: подтвердить личность без документов',
    description=(
        'Только при MYID_MODE=stub в dev/staging — иначе 404, будто маршрута нет. '
        'Сразу помечает профиль вызывающего проверенным и отвечает так же, как '
        'GET /users/me/verification/. Нужна, чтобы проходить сценарии с KYC до '
        'появления настоящей интеграции с MyID.'
    ),
)
class MyIDStubVerifyView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = 'kyc'

    def post(self, request):
        if not myid_stub_active():
            raise Http404
        profile, _ = Profile.objects.get_or_create(user=request.user)
        profile.mark_kyc_verified()
        profile.mark_myid_verified()
        # Помеченный профиль — это approved и для get_verification_status; сам
        # сервис не импортируем: он тянет opencv ради распознавания документов.
        return Response(VerificationStatusSerializer({
            'phone': request.user.phone,
            'status': 'approved',
            'rejection_reason': None,
            'reviewed_at': profile.kyc_verified_at,
        }).data)
