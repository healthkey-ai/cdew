from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import AdminUserViewSet, LoginView, MeView

router = DefaultRouter()
router.register(r"users", AdminUserViewSet, basename="admin-user")

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("me/", MeView.as_view(), name="me"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    *router.urls,
]
