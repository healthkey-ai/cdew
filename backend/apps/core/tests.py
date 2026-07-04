from rest_framework.test import APITestCase


class HealthTests(APITestCase):
    def test_health_ok_unauthenticated(self):
        resp = self.client.get("/api/v1/health/")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "service": "validation"}
