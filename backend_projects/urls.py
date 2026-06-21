import os

from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from .settings import BASE_DIR, STATIC_ROOT, STATIC_URL
from .views import ping

urlpatterns = [
    path("", include("shared.urls")),
    path("admin/", admin.site.urls),
    path("auth/", include("auth_app.urls")),
    path("blogs/", include("blogs_app.urls")),
    path("dead-stock/", include("dead_stock_app.urls")),
    path("weather/", include("weather_app.urls")),
    path("tasks/", include("todo_app.urls")),
    path("expenses/", include("expense_tracker_app.urls")),
    path("notes/", include("note_markdown_app.urls")),
    path("url-shortner/urls/", include("url_shortner_app.urls")),
    # path("device-classifier/", include("device_classifier.urls")),
    path("web-gis/", include("web_gis_app.urls")),
    path("ecom/", include("ecommerce_app.urls")),
    path(
        "expense-app/api-doc/",
        TemplateView.as_view(
            template_name=os.path.join(
                BASE_DIR, "templates/expense-tracker-open-api.html"
            ),
        ),
        name="expense-api-doc",
    ),
    path(
        "note-app/api-doc/",
        TemplateView.as_view(
            template_name=os.path.join(
                BASE_DIR, "templates/note-markdown-open-api.html"
            ),
        ),
        name="note-api-doc",
    ),
    path("ai/", include("agent_manager.urls")),
    path("level-up/", include("level_up_app.urls")),
    path("workload/", include("workload_app.urls")),
    path("ping/", ping),
    # TODO: Add API Doc for each app
] + static(STATIC_URL, document_root=STATIC_ROOT)

# if settings.DEBUG:
#     from debug_toolbar.toolbar import debug_toolbar_urls

#     urlpatterns += debug_toolbar_urls()
#     urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
