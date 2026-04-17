import logging
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken

from ..models import CustomUser, Profile, OTPCode, KYCDocument
from ..serializers import (
    SendOTPSerializer, VerifyOTPSerializer,
    KYCUploadSerializer, KYCStatusSerializer,
)
from ..emails import send_otp_email, generate_otp

logger = logging.getLogger(__name__)


class SendOTPView(APIView):
    """
    POST /api/v1/auth/send-otp/
    Отправляет OTP на номер телефона.
    """
    permission_classes = []

    def post(self, request):
        serializer = SendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        # Rate-limit: не чаще раза в 60 секунд
        recent = OTPCode.objects.filter(
            email=email,
            created_at__gte=timezone.now() - timedelta(seconds=60),
            is_used=False,
        ).exists()
        if recent:
            return Response(
                {'detail': 'Подождите 60 секунд перед повторной отправкой.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        code = generate_otp()
        OTPCode.objects.create(email=email, code=code)

        sent = send_otp_email(email, code)
        if not sent:
            return Response(
                {'detail': 'Не удалось отправить письмо. Попробуйте позже.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({'detail': 'Код отправлен.', 'email': email})


class VerifyOTPView(APIView):
    """
    POST /api/v1/auth/verify-otp/
    Проверяет OTP и возвращает JWT пару. Создаёт пользователя если новый.
    """
    permission_classes = []

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        code = serializer.validated_data['code']

        expiry = timezone.now() - timedelta(seconds=settings.OTP_EXPIRY_SECONDS)
        otp = OTPCode.objects.filter(
            email=email,
            code=code,
            is_used=False,
            created_at__gte=expiry,
        ).order_by('-created_at').first()

        if not otp:
            return Response(
                {'detail': 'Неверный или устаревший код.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp.is_used = True
        otp.save(update_fields=['is_used'])

        user, is_new = CustomUser.objects.get_or_create(email=email)
        if is_new:
            Profile.objects.create(user=user)
            logger.info('New user registered: %s', email)

        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'is_new_user': is_new,
        })


class LogoutView(APIView):
    """
    POST /api/v1/auth/logout/
    Инвалидирует refresh токен.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            token = RefreshToken(request.data.get('refresh'))
            token.blacklist()
            return Response({'detail': 'Выход выполнен.'})
        except Exception:
            return Response(
                {'detail': 'Неверный токен.'},
                status=status.HTTP_400_BAD_REQUEST,
            )


class KYCUploadView(APIView):
    """
    POST /api/v1/kyc/upload/
    Загрузка документов для верификации.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = KYCUploadSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        kyc = serializer.save()
        return Response(
            KYCStatusSerializer(kyc).data,
            status=status.HTTP_201_CREATED,
        )

    def get(self, request):
        try:
            kyc = request.user.kyc
        except KYCDocument.DoesNotExist:
            return Response(
                {'detail': 'KYC не найден.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(KYCStatusSerializer(kyc).data)
