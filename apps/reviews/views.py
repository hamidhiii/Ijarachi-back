from rest_framework import generics, permissions
from .models import Review
from .serializers import ReviewSerializer

class ReviewCreateView(generics.CreateAPIView):
    """
    POST /api/v1/reviews/
    Оставить отзыв о сделке.
    """
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticated]

class UserReviewsListView(generics.ListAPIView):
    """
    GET /api/v1/reviews/users/{id}/
    Просмотреть все отзывы пользователя (как получателя).
    """
    serializer_class = ReviewSerializer
    permission_classes = []

    def get_queryset(self):
        return Review.objects.filter(reviewee_id=self.kwargs['user_id']).order_by('-created_at')
