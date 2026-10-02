"""
到场预约URL配置
"""
from django.urls import path
from .views import (
    AppointmentListView, AppointmentDetailView, AppointmentTodayView,
    AppointmentRescheduleView, AppointmentCancelView, AppointmentCheckInView
)

urlpatterns = [
    path('appointments/', AppointmentListView.as_view(), name='appointment-list'),
    path('appointments/today/', AppointmentTodayView.as_view(), name='appointment-today'),
    path('appointments/<int:pk>/', AppointmentDetailView.as_view(), name='appointment-detail'),
    path('appointments/<int:pk>/reschedule/', AppointmentRescheduleView.as_view(), name='appointment-reschedule'),
    path('appointments/<int:pk>/cancel/', AppointmentCancelView.as_view(), name='appointment-cancel'),
    path('appointments/<int:pk>/check-in/', AppointmentCheckInView.as_view(), name='appointment-check-in'),
]
