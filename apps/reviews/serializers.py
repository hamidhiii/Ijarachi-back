from rest_framework import serializers
from .models import Review
from apps.bookings.models import Booking

class ReviewSerializer(serializers.ModelSerializer):
    reviewer_phone = serializers.CharField(source='reviewer.phone', read_only=True)
    
    class Meta:
        model = Review
        fields = ['id', 'reviewer_phone', 'reviewee', 'booking', 'rating', 'comment', 'created_at']
        read_only_fields = ['id', 'reviewer_phone', 'reviewee', 'created_at']

    def validate(self, data):
        booking = data['booking']
        user = self.context['request'].user
        
        if booking.status != Booking.STATUS_COMPLETED:
            raise serializers.ValidationError('Отзыв можно оставить только после завершения сделки.')
            
        if user not in [booking.renter, booking.item.owner]:
            raise serializers.ValidationError('Вы не являетесь участником этой сделки.')
            
        # Ensure we set the correct reviewee
        reviewee = booking.renter if user == booking.item.owner else booking.item.owner
        data['reviewee'] = reviewee
        
        return data

    def create(self, validated_data):
        validated_data['reviewer'] = self.context['request'].user
        return super().create(validated_data)
