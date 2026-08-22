import re

from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from .models import Profile, KYCDocument, PassportDocument, FaceVerification

User = get_user_model()

re_series = re.compile(r'[A-Z]{2}')


def normalize_uz_phone(value: str) -> str:
    import re
    value = re.sub(r'\D', '', value or '')
    if value.startswith('998') and len(value) == 12:
        return '+' + value
    raise serializers.ValidationError(
        'Поддерживаются только номера Узбекистана в формате +998901234567.'
    )


# ─── Auth ─────────────────────────────────────────────────────────────────────

class SendOTPSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)

    def validate_phone(self, value):
        return normalize_uz_phone(value)


class VerifyOTPSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    code = serializers.CharField(max_length=6, min_length=6)

    def validate_phone(self, value):
        return normalize_uz_phone(value)


class TokenPairSerializer(serializers.Serializer):
    """Response schema for JWT token pair."""
    access = serializers.CharField()
    refresh = serializers.CharField()
    is_new_user = serializers.BooleanField()


# ─── Profile ──────────────────────────────────────────────────────────────────

class ProfileSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source='user.id', read_only=True)
    phone = serializers.CharField(source='user.phone', read_only=True)
    email = serializers.EmailField(source='user.email', required=False)
    verified = serializers.BooleanField(source='is_verified_kyc', read_only=True)
    role = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = [
            'id', 'phone', 'email', 'full_name', 'avatar',
            'rating', 'verified', 'role',
            # Доп. поля для обратной совместимости с мобильным клиентом.
            'rating_count', 'verification_status', 'wallet_balance',
            'is_verified_kyc', 'kyc_verified_at',
        ]
        read_only_fields = [
            'rating',
            'rating_count',
            'verification_status',
            'wallet_balance',
            'is_verified_kyc',
            'kyc_verified_at',
        ]

    def get_role(self, obj):
        return 'admin' if obj.user.is_staff else 'user'

    def update(self, instance, validated_data):
        user_data = validated_data.pop('user', {})
        if 'email' in user_data:
            instance.user.email = user_data['email']
            instance.user.save(update_fields=['email'])
        return super().update(instance, validated_data)


class PublicUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()
    rating_count = serializers.SerializerMethodField()
    verified = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    is_verified_kyc = serializers.SerializerMethodField()
    verification_status = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'full_name',
            'avatar',
            'rating',
            'verified',
            'role',
            # Доп. поля для обратной совместимости с мобильным клиентом.
            'rating_count',
            'is_verified_kyc',
            'verification_status',
            'date_joined',
        ]
        read_only_fields = fields

    def get_avatar(self, obj):
        try:
            avatar = obj.profile.avatar
        except Exception:
            return None
        if not avatar:
            return None
        request = self.context.get('request')
        return request.build_absolute_uri(avatar.url) if request else avatar.url

    def get_full_name(self, obj):
        try:
            return obj.profile.full_name
        except Exception:
            return ''

    def get_rating(self, obj):
        try:
            return obj.profile.rating
        except Exception:
            return 0

    def get_rating_count(self, obj):
        try:
            return obj.profile.rating_count
        except Exception:
            return 0

    def get_is_verified_kyc(self, obj):
        try:
            return obj.profile.is_verified_kyc
        except Exception:
            return False

    get_verified = get_is_verified_kyc

    def get_role(self, obj):
        return 'admin' if obj.is_staff else 'user'

    def get_verification_status(self, obj):
        try:
            return obj.profile.verification_status
        except Exception:
            return Profile.VERIFICATION_NONE


# ─── KYC ──────────────────────────────────────────────────────────────────────

class KYCUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = KYCDocument
        fields = ['doc_image', 'selfie']

    def create(self, validated_data):
        user = self.context['request'].user
        # Update existing or create new
        kyc, _ = KYCDocument.objects.update_or_create(
            user=user,
            defaults={**validated_data, 'status': KYCDocument.STATUS_PENDING}
        )
        # Set profile to pending
        user.profile.verification_status = Profile.VERIFICATION_PENDING
        user.profile.save(update_fields=['verification_status'])
        return kyc


class KYCStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = KYCDocument
        fields = ['status', 'submitted_at', 'reviewed_at', 'reject_reason']
        read_only_fields = fields


class VerificationStatusSerializer(serializers.Serializer):
    """
    GET /users/me/verification/ — сводный статус KYC (паспорт + сверка лица).
    Собирается сервисом `apps.users.services.kyc.get_verification_status`, а не
    напрямую из модели, т.к. объединяет несколько таблиц (Passport/FaceVerification).
    """
    phone = serializers.CharField()
    status = serializers.ChoiceField(choices=['none', 'review', 'approved', 'rejected'])
    rejection_reason = serializers.CharField(allow_null=True)
    reviewed_at = serializers.DateTimeField(allow_null=True)


# ─── KYC: паспорт/ID-карта ─────────────────────────────────────────────────────

class PassportUploadSerializer(serializers.Serializer):
    document_type = serializers.ChoiceField(
        choices=PassportDocument.TYPE_CHOICES, default=PassportDocument.TYPE_ID_CARD
    )
    front_image = serializers.ImageField()
    back_image = serializers.ImageField(required=False, allow_null=True)


class PassportConfirmSerializer(serializers.Serializer):
    """Клиент подтверждает/правит данные, распознанные OCR, перед финальной проверкой."""
    series = serializers.CharField(max_length=10)
    number = serializers.CharField(max_length=20)
    pinfl = serializers.CharField(max_length=14)
    full_name = serializers.CharField(max_length=200)
    birth_date = serializers.DateField()
    issue_date = serializers.DateField(required=False, allow_null=True)
    expiry_date = serializers.DateField(required=False, allow_null=True)

    def validate_series(self, value):
        value = value.strip().upper()
        if not re_series.fullmatch(value):
            raise serializers.ValidationError('Серия должна состоять из 2 латинских букв, напр. "AD".')
        return value

    def validate_number(self, value):
        value = value.strip()
        if not value.isdigit() or len(value) != 7:
            raise serializers.ValidationError('Номер документа должен состоять из 7 цифр.')
        return value

    def validate_pinfl(self, value):
        value = value.strip()
        if not value.isdigit() or len(value) != 14:
            raise serializers.ValidationError('ПИНФЛ должен состоять из 14 цифр.')
        return value


class PassportStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = PassportDocument
        fields = [
            'document_type', 'series', 'number', 'pinfl', 'full_name',
            'birth_date', 'issue_date', 'expiry_date',
            'status', 'reject_reason', 'submitted_at', 'verified_at',
        ]
        read_only_fields = fields


# ─── KYC: сверка лица (face match + liveness) ──────────────────────────────────

class FaceVerifySerializer(serializers.Serializer):
    frame_1 = serializers.ImageField()
    frame_2 = serializers.ImageField(required=False, allow_null=True)
    frame_3 = serializers.ImageField(required=False, allow_null=True)


class FaceVerificationStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = FaceVerification
        fields = [
            'status', 'face_match_score', 'face_match_passed',
            'liveness_score', 'liveness_passed', 'fail_reason',
            'submitted_at', 'verified_at',
        ]
        read_only_fields = fields


class PhoneChangeSendSerializer(serializers.Serializer):
    new_phone = serializers.CharField(max_length=20)

    def validate_new_phone(self, value):
        phone = normalize_uz_phone(value)
        if User.objects.filter(phone=phone).exists():
            raise serializers.ValidationError('Этот номер уже занят.')
        return phone


class PhoneChangeVerifySerializer(serializers.Serializer):
    new_phone = serializers.CharField(max_length=20)
    code = serializers.CharField(max_length=6, min_length=6)

    def validate_new_phone(self, value):
        return normalize_uz_phone(value)
