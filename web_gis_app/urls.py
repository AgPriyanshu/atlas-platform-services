from django.urls import include, path
from rest_framework.routers import DefaultRouter

from web_gis_app.views.document_views import DocumentViewSet
from web_gis_app.views.feature_views import FeatureViewSet
from web_gis_app.views.layer_views import LayerViewSet
from web_gis_app.views.processing_views import ProcessingJobViewSet
from web_gis_app.views.tiles_views import DatasetTileView
from web_gis_app.views.vector_tile_view import VectorTileView
from web_gis_app.views.workflow_views import (
    WorkflowRunDetailView,
    WorkflowRunListCreateView,
    WorkflowViewSet,
)

from .views.dataset_views import DatasetNodeViewSet

router = DefaultRouter()

router.register(r"datasets", DatasetNodeViewSet, basename="datasets")
router.register(r"layers", LayerViewSet, basename="layers")
router.register(r"features", FeatureViewSet, basename="features")
router.register(r"processing", ProcessingJobViewSet, basename="processing")
router.register(r"documents", DocumentViewSet, basename="documents")
router.register(r"workflows", WorkflowViewSet, basename="workflows")

urlpatterns = [
    path("", include(router.urls)),
    path(
        "datasets/<uuid:pk>/tiles/<int:z>/<int:x>/<int:y>.png",
        DatasetTileView.as_view(),
        name="dataset-tile",
    ),
    path(
        "datasets/<uuid:pk>/vector-tiles/<int:z>/<int:x>/<int:y>.mvt",
        VectorTileView.as_view(),
        name="dataset-vector-tile",
    ),
    path(
        "workflows/<uuid:workflow_id>/runs/",
        WorkflowRunListCreateView.as_view(),
        name="workflow-runs",
    ),
    path(
        "workflows/<uuid:workflow_id>/runs/<uuid:pk>/",
        WorkflowRunDetailView.as_view(),
        name="workflow-run-detail",
    ),
]
