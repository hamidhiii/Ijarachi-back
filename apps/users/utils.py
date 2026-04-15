import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

class NotificationService:
    """
    Utility service for sending push notifications via FCM.
    Requires FIREBASE_SERVER_KEY in settings.
    """
    
    @staticmethod
    def send_push_notification(user, title, body, data=None):
        if not user.profile.fcm_token:
            logger.info(f"User {user.phone} has no FCM token. Skipping notification.")
            return False

        # Note: This is a scaffold. You'd typically use firebase-admin package,
        # but a simple POST request to FCM V1 or Legacy API also works for basic needs.
        
        fcm_api_url = "https://fcm.googleapis.com/fcm/send"
        headers = {
            "Authorization": f"key={getattr(settings, 'FIREBASE_SERVER_KEY', '')}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "to": user.profile.fcm_token,
            "notification": {
                "title": title,
                "body": body,
                "sound": "default"
            },
            "data": data or {}
        }
        
        try:
            response = requests.post(fcm_api_url, json=payload, headers=headers, timeout=5)
            response.raise_for_status()
            logger.info(f"Push notification sent successfully to {user.phone}")
            return True
        except Exception as e:
            logger.error(f"Failed to send push notification to {user.phone}: {str(e)}")
            return False

def notify_booking_event(booking, event_type):
    """
    Higher-level utility to notify parties about booking events.
    """
    service = NotificationService()
    
    if event_type == 'new_booking':
        service.send_push_notification(
            booking.item.owner,
            "Новое бронирование",
            f"У вас новый запрос на {booking.item.title}",
            {"booking_id": str(booking.id)}
        )
    elif event_type == 'payment_received':
        service.send_push_notification(
            booking.item.owner,
            "Оплата получена",
            f"Бронирование {booking.item.title} оплачено. Пожалуйста, подтвердите готовность.",
            {"booking_id": str(booking.id)}
        )
