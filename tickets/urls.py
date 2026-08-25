from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(template_name='tickets/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('tickets/new/', views.create_ticket, name='create_ticket'),
    path('tickets/', views.my_tickets, name='my_tickets'),
    path('notifications/', views.notifications_view, name='notifications'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/export/', views.dashboard_export, name='dashboard_export'),
    path('manage-users/', views.manage_users, name='manage_users'),
    path('tickets/<int:ticket_id>/', views.ticket_detail, name='ticket_detail'),
]
