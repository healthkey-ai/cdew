from django.urls import path

from .views import PatientDirectoryView, PatientSearchView

urlpatterns = [
    path("", PatientSearchView.as_view(), name="patient_search"),
    path("directory/", PatientDirectoryView.as_view(), name="patient_directory"),
]
