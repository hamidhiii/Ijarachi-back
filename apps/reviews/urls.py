from django.urls import path
from .views import ReviewCreateView, UserReviewsListView

urlpatterns = [
    path('reviews/', ReviewCreateView.as_view(), name='review-create'),
    path('reviews/users/<int:user_id>/', UserReviewsListView.as_view(), name='user-reviews'),
]
