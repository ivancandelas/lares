from django.urls import path

from . import views

app_name = "tasks"

urlpatterns = [
    path("tareas/", views.task_list, name="list"),
    path("tareas/<uuid:pk>/completar/", views.complete, name="complete"),
]
