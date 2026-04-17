from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from .models import Profile, KYCDocument

User = get_user_model()


# ─── Auth ─────────────────────────────────────────────────────────────────────

class SendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()


class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(max_length=6, min_length=6)


class TokenPairSerializer(serializers.Serializer):
    """Response schema for JWT token pair."""
    access = serializers.CharField()
    refresh = serializers.CharField()
    is_new_user = serializers.BooleanField()


# ─── Profile ──────────────────────────────────────────────────────────────────

class ProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    phone = serializers.CharField(source='user.phone', required=False)

    class Meta:
        model = Profile
        fields = [
            'email', 'phone', 'full_name', 'avatar',
            'rating', 'rating_count', 'verification_status',
        ]
        read_only_fields = ['rating', 'rating_count', 'verification_status']

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
