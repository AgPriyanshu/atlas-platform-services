import io
import json
from typing import Annotated, Any

import httpx
from asgiref.sync import sync_to_async
from geopy.geocoders import Nominatim
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

SANDBOX_URL = "http://sandbox:8001"
_POLL_INTERVAL = 2
_MAX_POLL_SECONDS = 150

_RASTER_EXTENSIONS = {"tif", "tiff"}
_VECTOR_EXTENSIONS = {"geojson", "json", "gpkg"}


@tool
async def run_python(code: str) -> str:
    """Execute Python code in a secure, isolated container and return its output.

    Available libraries: GDAL, rasterio, shapely, geopandas, numpy, pandas, pyproj.
    The variable OUTPUT_DIR is pre-defined — write output files there:
      gdf.to_file(f'{OUTPUT_DIR}/result.geojson', driver='GeoJSON')
    Use print() to show computed values.
    Returns stdout, a job ID, and a list of output files for use with create_gis_layer.
    """
    import asyncio

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{SANDBOX_URL}/execute", json={"code": code})
        job_id = resp.json()["job_id"]

        data: dict = {}
        elapsed = 0

        while elapsed < _MAX_POLL_SECONDS:
            await asyncio.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL
            r = await client.get(f"{SANDBOX_URL}/result/{job_id}")
            data = r.json()

            if data.get("status") != "pending":
                break

    if data.get("status") == "pending":
        return "Error: execution timed out (exceeded agent budget)."

    if data.get("exit_code", 1) != 0:
        return f"Error:\n{data.get('stderr', '')}"

    stdout = data.get("stdout") or "(no output)"
    output_files = data.get("output_files") or []

    if not output_files:
        return f"[job:{job_id}]\n{stdout}"

    sizes_line = ", ".join(output_files)
    return f"[job:{job_id}]\n{stdout}\nOutput files: {sizes_line}"


@tool
async def create_gis_layer(
    job_id: str,
    filename: str,
    layer_name: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """Download a GIS output file from a previous run_python call and add it to the map as a new layer.

    Use after run_python when the code wrote output files to OUTPUT_DIR.
    Supported formats: .geojson (vector, visible immediately), .tif/.tiff (raster, appears in ~30s).
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in _RASTER_EXTENSIONS | _VECTOR_EXTENSIONS:
        return f"Error: unsupported format '.{ext}'. Use .geojson or .tif."

    is_raster = ext in _RASTER_EXTENSIONS
    session_id = state.get("session_id", "")

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"{SANDBOX_URL}/files/{job_id}/{filename}")

        if response.status_code != 200:
            return f"Error: could not retrieve '{filename}' from sandbox (HTTP {response.status_code})."

        file_bytes = response.content

    geojson_data = None

    if not is_raster and ext in {"geojson", "json"}:
        try:
            geojson_data = json.loads(file_bytes)
        except json.JSONDecodeError:
            return "Error: output file is not valid GeoJSON."

    result_msg = await sync_to_async(_create_dataset_and_layer)(
        session_id=session_id,
        file_bytes=file_bytes,
        filename=filename,
        layer_name=layer_name,
        is_raster=is_raster,
        geojson_data=geojson_data,
    )

    async with httpx.AsyncClient(timeout=10) as client:
        await client.delete(f"{SANDBOX_URL}/result/{job_id}")

    return result_msg


def _create_dataset_and_layer(
    *,
    session_id: str,
    file_bytes: bytes,
    filename: str,
    layer_name: str,
    is_raster: bool,
    geojson_data: dict | None,
) -> str:
    from django.contrib.gis.geos import GEOSGeometry

    from agent_manager.models import ChatSession
    from shared.infrastructure import InfraManager
    from web_gis_app.constants import (
        DatasetNodeType,
        DatasetStatus,
        DatasetType,
        FileFormat,
    )
    from web_gis_app.models import Dataset, DatasetNode, Feature, Layer
    from web_gis_app.notifications import send_notification
    from web_gis_app.services import DatasetStorageService

    session = ChatSession.objects.select_related("user").get(id=session_id)
    user = session.user

    ext = filename.rsplit(".", 1)[-1].lower()
    _format_map = {
        "tif": FileFormat.GEOTIFF,
        "tiff": FileFormat.GEOTIFF,
        "geojson": FileFormat.GEOPACKAGE,
        "json": FileFormat.GEOPACKAGE,
        "gpkg": FileFormat.GEOPACKAGE,
    }
    file_format = _format_map.get(
        ext, FileFormat.GEOTIFF if is_raster else FileFormat.GEOPACKAGE
    )
    dataset_type = DatasetType.RASTER if is_raster else DatasetType.VECTOR

    dataset_node = DatasetNode.objects.create(
        name=layer_name,
        type=DatasetNodeType.DATASET,
        user=user,
    )

    dataset = Dataset.objects.create(
        dataset_node=dataset_node,
        type=dataset_type,
        format=file_format,
        file_name=filename,
        file_size=0,
        cloud_storage_path="",
        status=DatasetStatus.PENDING,
    )

    cloud_path = DatasetStorageService.build_dataset_storage_key(
        dataset_id=dataset.id,
        filename=filename,
    )

    InfraManager.object_storage.upload_object(
        file=io.BytesIO(file_bytes),
        key=cloud_path,
        metadata={
            "dataset_id": str(dataset.id),
            "original_filename": filename,
        },
    )

    dataset.file_size = len(file_bytes)
    dataset.cloud_storage_path = cloud_path
    dataset.status = DatasetStatus.UPLOADED
    dataset.save(update_fields=["file_size", "cloud_storage_path", "status"])

    if geojson_data and not is_raster:
        features = []

        for f in geojson_data.get("features", []):
            if not f.get("geometry"):
                continue

            features.append(
                Feature(
                    dataset=dataset,
                    geometry=GEOSGeometry(json.dumps(f["geometry"]), srid=4326),
                    properties=f.get("properties") or {},
                )
            )

        if features:
            Feature.objects.bulk_create(features, batch_size=500)

    layer = Layer.objects.create(
        name=layer_name,
        source=dataset,
        user=user,
    )

    send_notification(
        content=json.dumps(
            {
                "type": "agent_layer_created",
                "layerId": str(layer.id),
                "layerName": layer_name,
                "datasetId": str(dataset.id),
                "datasetType": dataset_type,
            }
        ),
        user=user,
    )

    if is_raster:
        return f"Layer '{layer_name}' created. Raster is processing — it will appear on the map in ~30 seconds."

    return f"Layer '{layer_name}' created and now visible on the map."


@tool
async def retrieve_from_documents(
    query: str,
    state: Annotated[dict, InjectedState],
    top_k: int = 5,
) -> str:
    """Search the user's uploaded PDF documents for relevant context.

    Use this when the user asks about content in their uploaded PDF documents.
    Returns the most relevant text excerpts with their source document and page number.
    """
    from agent_manager.models import ChatSession
    from shared.rag.retrieval import retrieve_chunks

    session_id = state.get("session_id", "")

    try:
        session = await ChatSession.objects.select_related("user").aget(id=session_id)
    except Exception:
        return "Error: could not resolve session to retrieve documents."

    chunks = await sync_to_async(retrieve_chunks)(query, session.user, top_k)

    if not chunks:
        return "No relevant content found in uploaded documents."

    return "\n\n---\n\n".join(
        f"[{c.document.title}, page {c.page_number}]\n{c.text}" for c in chunks
    )


_geocoder = Nominatim(user_agent="atlas-platform")


@tool
def geocode(query: str) -> dict:
    """Geocode a place name or address and return its coordinates."""
    location = _geocoder.geocode(query)  # type: ignore[assignment]

    if location is None:
        return {"error": f"Could not find coordinates for '{query}'."}

    return {
        "latitude": location.latitude,  # type: ignore[union-attr]
        "longitude": location.longitude,  # type: ignore[union-attr]
        "address": location.address,  # type: ignore[union-attr]
    }


@tool
def map_zoom_to(latitude: float, longitude: float) -> dict:
    """Zoom the map to the given coordinates. Use this after geocoding when the user wants to navigate or fly to a location."""
    return {"latitude": latitude, "longitude": longitude}


@tool
def list_loaded_vector_layers(
    state: Annotated[dict, InjectedState],
) -> list[dict]:
    """List vector layers currently loaded on the user's map.

    Use this to resolve a user's layer reference (e.g. "the buildings layer")
    to a concrete dataset id before invoking a processing tool.
    Returns a list of objects with id, name, type, and dataset_id.
    """
    layers = state.get("loaded_layers") or []

    return [layer for layer in layers if layer.get("type") == "vector"]


@tool
def list_processing_tools() -> list[dict]:
    """List the geoprocessing tools available in the Web GIS processing toolbox.

    Use this before opening a processing tool so you know the exact tool_name
    and the parameter names, types, and defaults you must supply.
    """
    from web_gis_app.tool_registry import list_tools

    return list_tools()


@tool
def open_processing_tool(
    tool_name: str,
    defaults: dict[str, Any],
    output_name: str | None = None,
) -> dict:
    """Open a geoprocessing tool modal on the frontend with inputs prefilled.

    Call this when the user wants to run a processing workflow (buffer, clip,
    dissolve, centroid, simplify, convex hull, hillshade, slope, contour, etc.).
    Do not call it until you have:
      1. Found the tool_name via list_processing_tools.
      2. Resolved any input layer references to dataset ids via list_loaded_vector_layers.
      3. Collected every required parameter from the user (or set a reasonable default).

    Args:
        tool_name: The exact tool name as returned by list_processing_tools (toolName field).
        defaults: A dict of prefilled form values. Must include "inputDatasetId" and any
            tool-specific parameters (e.g. {"inputDatasetId": "...", "distance": 50, "units": "meters"}).
        output_name: Optional name for the output dataset.
    """
    payload: dict[str, Any] = {"tool_name": tool_name, "defaults": defaults}

    if output_name:
        payload["output_name"] = output_name

    return payload
