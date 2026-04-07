"""Notification system for in-app and email notifications."""

from src.core.notifications.service import NotificationService, notification_service
from src.core.notifications.models import Notification, NotificationChannel

__all__ = ["Notification", "NotificationChannel", "NotificationService", "notification_service"]
