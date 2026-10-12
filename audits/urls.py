from django.urls import path

from . import views

app_name = "audits"
urlpatterns = [
    path("", views.home, name="home"),
    path("history/", views.history, name="history"),
    path("report/<int:pk>/", views.report, name="report"),
    path("report/<int:pk>/download/", views.download, name="download"),
    path("free-check/", views.free_check, name="free_check"),
    path("free-check/<uuid:token>/", views.free_result, name="free_result"),
]
