from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from apps.catalog.models import Item

class FavoriteItem(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='favorites',
        verbose_name=_('User')
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='favorited_by',
        verbose_name=_('Item')
    )
    created_at = models.DateTimeField(_('Added at'), auto_now_add=True)

    class Meta:
        verbose_name = _('Favorite Item')
        verbose_name_plural = _('Favorite Items')
        unique_together = ('user', 'item')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.phone} - {self.item.title}'
