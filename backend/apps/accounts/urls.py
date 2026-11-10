from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    AdminUserViewSet,
    AuthConfigView,
    LoginView,
    MeView,
    PartnerLoginView,
    PartnerTokenView,
)

router = DefaultRouter()
router.register(r"users", AdminUserViewSet, basename="admin-user")

urlpatterns = [
    path("config/", AuthConfigView.as_view(), name="auth_config"),
    path("login/", LoginView.as_view(), name="login"),
    path("partner-login/", PartnerLoginView.as_view(), name="partner_login"),
    path("partner-token/", PartnerTokenView.as_view(), name="partner_token"),
    path("me/", MeView.as_view(), name="me"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    *router.urls,
]
