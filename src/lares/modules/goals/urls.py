from django.urls import path

from . import views

app_name = "goals"

urlpatterns = [
    path("metas/", views.goal_list, name="list"),
    path("metas/nueva/", views.goal_new, name="new"),
    path("metas/<uuid:pk>/", views.goal_detail, name="detail"),
    path("metas/<uuid:pk>/editar/", views.goal_edit, name="edit"),
    path("metas/<uuid:pk>/apartar/", views.contribute, name="contribute"),
    path("metas/<uuid:pk>/cerrar/", views.close, name="close"),
]
