from django.db import models
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.bookings.models import Booking
from apps.users.models import Profile

class Review(models.Model):
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews_left', verbose_name='Автор')
    reviewee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews_received', verbose_name='Получатель')
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='reviews', verbose_name='Сделка')
    rating = models.PositiveSmallIntegerField('Оценка', choices=[(i, str(i)) for i in range(1, 6)])
    comment = models.TextField('Комментарий', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Отзыв'
        verbose_name_plural = 'Отзывы'
        unique_together = ('reviewer', 'booking')  # Only one review per booking per user

    def __str__(self):
        return f'Отзыв от {self.reviewer.phone} для {self.reviewee.phone} ({self.rating}/5)'


@receiver(post_save, sender=Review)
def update_profile_rating(sender, instance, created, **kwargs):
    if created:
        profile, _ = Profile.objects.get_or_create(user=instance.reviewee)
        reviews = Review.objects.filter(reviewee=instance.reviewee)
        count = reviews.count()
        avg_rating = sum(r.rating for r in reviews) / count if count > 0 else 0.0
        profile.rating = round(avg_rating, 1)
        profile.rating_count = count
        profile.save(update_fields=['rating', 'rating_count'])
