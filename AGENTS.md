# Agent Instructions

This document provides guidelines for AI agents working on this codebase.

## General Guidelines

- Every comment should end with a full stop.
- Do not add unnecessary comments.
- Use code block division with a blank line for best readability.
- Add a blank line before each `if` or `for` loop for readability.
- Do not create tests, examples, or run scripts without asking the user first.

## Technology Stack

- **Web framework**: Django 6 + Django REST Framework
- **ASGI server**: Uvicorn + Daphne (WebSockets via Django Channels)
- **Database**: PostgreSQL 17 with PostGIS (port 5431 in Docker)
- **Cache / pub-sub**: Redis (port 6379)
- **Task queue**: Celery workers
- **Object storage**: SeaweedFS (S3-compatible, ports 9333/8080/8333)
- **GIS tile serving**: rio-tiler (raster XYZ), PostGIS ST_AsMVT (vector MVT)
- **AI agents**: LangGraph + LangChain + LangChain-OpenAI
- **Sandboxed code execution**: Docker-in-Docker via `sandbox` service
- **Deployment**: Kubernetes (see `k8s/`)

## Project Structure

```
atlas-platform-services/
├── backend_projects/       # Django project root — settings, URL routing, ASGI config
├── shared/                 # Cross-app utilities (BaseModel, notifications, SSE, InfraManager)
├── agent_manager/          # AI chat agent — WebSocket consumer, LangGraph graph, tools
├── web_gis_app/            # GIS datasets, layers, tile serving, geoprocessing jobs
├── sandbox/                # Isolated Python/GIS code execution service (FastAPI + Docker)
├── auth_app/               # JWT authentication
├── workload_app/           # Employee workload and work-item tracking
├── todo_app/               # Todo lists
├── expense_tracker_app/    # Expense tracking
├── note_markdown_app/      # Markdown notes
├── url_shortner_app/       # URL shortening
├── blogs_app/              # Blog posts
├── weather_app/            # Weather data
├── ecommerce_app/          # E-commerce
└── level_up_app/           # Gamification / levelling
```

### Shared App

The `shared` app provides:
- `shared.models.base_models.BaseModel` — UUID PK, `user` FK, `created_at`, `updated_at`. All user-owned models inherit from this.
- `shared.models.base_models.BaseModelWithoutUser` — UUID PK, timestamps, no user. Used for join/child models.
- `shared.infrastructure.InfraManager` — singleton for object storage (S3/SeaweedFS). Use `InfraManager.object_storage.upload_object(file, key, metadata)` / `download_object(key)` / `delete_object(key)`.
- `shared.notifications.send_notification(content, app_name, user)` — publishes a JSON string to Redis; SSE endpoint delivers it to the browser. Always pass a JSON-encoded string as `content`.
- `shared.constants.AppName` — enum of app names for notification routing.
- `shared.views.base_viewsets.BaseModelViewSet` — auto-filters querysets by `user=request.user`. All feature ViewSets inherit from this.

## URL Routing

Defined in `backend_projects/urls.py`:

| Prefix | App |
|--------|-----|
| `/auth/` | auth_app |
| `/ai/` | agent_manager (REST) |
| `/ws/ai/<session_id>/` | agent_manager (WebSocket) |
| `/web-gis/` | web_gis_app |
| `/events/` | shared SSE endpoint |
| `/tasks/` | workload_app |
| `/blogs/` | blogs_app |
| `/weather/` | weather_app |
| `/expenses/` | expense_tracker_app |
| `/notes/` | note_markdown_app |
| `/urls/` | url_shortner_app |
| `/ecom/` | ecommerce_app |

## Agent Manager Architecture

The `agent_manager` app implements a multi-node LangGraph agent with self-reflection.

**Graph topology:**
```
START → ORCHESTRATOR → [WEB_GIS_EXPERT | UI_EXPERT | RESPONDER]
                              ↓ (experts → RESPONDER via fixed edges)
                         RESPONDER (draft)
                              ↓
                           CRITIC (evaluate quality, max 3 iterations)
                        ↙         ↘
                    APPROVE      REJECT → [WEB_GIS_EXPERT | UI_EXPERT | ORCHESTRATOR]
                      ↓
                     END
```

**Key files:**
- `agent_manager/agents/agent_factory.py` — builds LangGraph graph; node implementations
- `agent_manager/agents/schemas.py` — `GlobalMessageState`, `Node` enum, `CritiqueDecision`
- `agent_manager/agents/tools.py` — LangChain tools: `run_python`, `create_gis_layer`, `geocode`, `map_zoom_to`, `list_loaded_vector_layers`, `open_processing_tool`
- `agent_manager/agents/prompts.py` — system prompts for each node
- `agent_manager/consumers.py` — Django Channels WebSocket consumer; streams chunks to client
- `agent_manager/constants.py` — `GRAPH_TURN_TIMEOUT=180s`, `MAX_LOOP_ITERATIONS=3`

**WebSocket message format:**
```json
{ "id": "...", "session_id": "...", "message": "...", "user_id": "...", "role": "assistant", "isChunk": true, "ui_action": null }
```

## Web GIS Architecture

**Data flow: upload → tile serving**
1. File uploaded to S3 via `POST /web-gis/datasets/` (multipart or direct)
2. `Dataset.status = UPLOADED` triggers Django signal → Celery `generate_cog_task`
3. Task converts raster to Cloud Optimized GeoTIFF, creates `TileSet(status=READY)`
4. User creates `Layer` pointing to the Dataset
5. Frontend requests `GET /web-gis/datasets/<id>/tiles/<z>/<x>/<y>.png` (raster) or `.mvt` (vector)

**Key models** (in `web_gis_app/models/`):
- `DatasetNode` — tree node (folder or dataset reference); has `user`, `parent`, `type`
- `Dataset` — actual data file; has `type` (vector/raster), `format`, `cloud_storage_path`, `status`, `metadata`
- `TileSet` — processed COG for tile serving; has `storage_path`, `bounds`, `min_zoom`, `max_zoom`
- `Layer` — map layer definition; has `source` (FK → Dataset), `style` (MapLibre JSON), `user`
- `Feature` — individual GeoJSON feature in PostGIS; has `dataset`, `geometry` (SRID 4326), `properties`
- `ProcessingJob` — async geoprocessing task; has `tool_name`, `status`, `input_datasets`, `output_dataset`

**Creating a dataset programmatically (Python/ORM):**
```python
from web_gis_app.services import DatasetStorageService
from web_gis_app.constants import DatasetNodeType, DatasetStatus, DatasetType, FileFormat
from web_gis_app.models import Dataset, DatasetNode, Layer
from shared.infrastructure import InfraManager

node = DatasetNode.objects.create(name=name, type=DatasetNodeType.DATASET, user=user)
dataset = Dataset.objects.create(dataset_node=node, type=DatasetType.VECTOR, format=FileFormat.GEOPACKAGE,
                                  file_name=filename, file_size=0, cloud_storage_path="", status=DatasetStatus.PENDING)
key = DatasetStorageService.build_dataset_storage_key(dataset_id=dataset.id, filename=filename)
InfraManager.object_storage.upload_object(file=file_obj, key=key, metadata={...})
dataset.cloud_storage_path = key
dataset.file_size = size
dataset.status = DatasetStatus.UPLOADED  # triggers COG signal for rasters
dataset.save(update_fields=["cloud_storage_path", "file_size", "status"])
layer = Layer.objects.create(name=name, source=dataset, user=user)
```

**Notification after dataset/layer creation:**
```python
from web_gis_app.notifications import send_notification
import json
send_notification(content=json.dumps({"type": "agent_layer_created", "layerId": str(layer.id), ...}), user=user)
```

## Sandbox Service

The `sandbox` Docker Compose service provides isolated GIS code execution:
- FastAPI server at `http://sandbox:8001`
- Each execution spawns a throwaway container: `--network none --read-only --memory 256m`
- Output files written to `OUTPUT_DIR` env var (pre-injected into user code) persist in `sandbox_outputs` named volume
- Async job pattern: `POST /execute` → `{job_id}`; poll `GET /result/{job_id}`; download `GET /files/{job_id}/{filename}`; cleanup `DELETE /result/{job_id}`

The `run_python` LangChain tool wraps this. The `create_gis_layer` tool reads output files and ingests them into the web_gis_app pipeline.

## Real-Time Notifications (Signal → Redis → SSE)

1. Django signal or Celery task calls `send_notification(content, app_name, user)`
2. Notification published to Redis channel `notifications_{user.pk}`
3. Frontend SSE connection (`GET /events/`) streams events to browser
4. Frontend writes directly into React Query cache → triggers re-render

## Endpoint Development

When creating a new endpoint or updating an existing endpoint:

- Automatically update the relevant documentation.
- Automatically update or create corresponding tests.

## Running Django Commands

- Always use **Docker Compose** to run any Django-related commands.
- Examples:
  - Migrations: `docker compose exec web python manage.py migrate`
  - Make migrations: `docker compose exec web python manage.py makemigrations`
  - Shell: `docker compose exec web python manage.py shell`

## Python Package Management

- This project uses **uv** for all dependency management.
- Dependencies are declared in `pyproject.toml` and locked in `uv.lock`.
- **Do not edit `uv.lock` by hand** and do not use pip directly.
- To add a new package:
  1. Add it to the `dependencies` list in `pyproject.toml`.
  2. Run `uv lock` locally to update `uv.lock`.
  3. Rebuild the Docker image: `docker compose up --build`.
- To remove a package: remove it from `pyproject.toml`, then run `uv lock`.
- The `sandbox/` service has its own `pyproject.toml` and `uv.lock` — manage them independently.
