from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from .models import Profile, KYCDocument, MyIDVerificationAttempt

User = get_user_model()


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
    phone = serializers.CharField(source='user.phone', read_only=True)
    email = serializers.EmailField(source='user.email', required=False)

    class Meta:
        model = Profile
        fields = [
            'phone', 'email', 'full_name', 'avatar',
            'rating', 'rating_count', 'verification_status', 'wallet_balance',
            'is_verified_myid', 'myid_verified_at',
        ]
        read_only_fields = [
            'rating',
            'rating_count',
            'verification_status',
            'wallet_balance',
            'is_verified_myid',
            'myid_verified_at',
        ]

    def update(self, instance, validated_data):
        user_data = validated_data.pop('user', {})
        if 'email' in user_data:
            instance.user.email = user_data['email']
            instance.user.save(update_fields=['email'])
        return super().update(instance, validated_data)


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


class VerificationStatusSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(source='user.phone', read_only=True)

    class Meta:
        model = Profile
        fields = [
            'phone',
            'verification_status',
            'is_verified_myid',
            'myid_verified_at',
        ]
        read_only_fields = fields


class MyIDStartResponseSerializer(serializers.Serializer):
    authorize_url = serializers.URLField()
    state = serializers.CharField()


class MyIDAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = MyIDVerificationAttempt
        fields = ['state', 'status', 'error', 'created_at', 'finished_at']
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
