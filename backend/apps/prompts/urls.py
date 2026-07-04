from rest_framework.routers import DefaultRouter

from .views import PromptDefinitionViewSet, PromptTestSampleViewSet, PromptVersionViewSet

router = DefaultRouter()
router.register(r"definitions", PromptDefinitionViewSet, basename="prompt-definition")
router.register(r"versions", PromptVersionViewSet, basename="prompt-version")
router.register(r"test-set", PromptTestSampleViewSet, basename="prompt-test-sample")

urlpatterns = router.urls
