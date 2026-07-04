from rest_framework.routers import DefaultRouter

from .review import ExtractionReviewViewSet

router = DefaultRouter()
router.register(r"", ExtractionReviewViewSet, basename="extraction")

urlpatterns = router.urls
