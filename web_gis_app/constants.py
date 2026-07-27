from django.db.models import TextChoices


class DatasetNodeType(TextChoices):
    FOLDER = "folder"
    DATASET = "dataset"


class DatasetType(TextChoices):
    VECTOR = "vector"
    RASTER = "raster"
    TEXT = "text"


class FileFormat(TextChoices):
    # Vector formats
    SHAPEFILE = "shapefile"
    KML = "kml"
    GEOPACKAGE = "gpkg"

    # Raster formats
    GEOTIFF = "geotiff"
    COG = "cog"
    PNG = "png"
    JPEG = "jpeg"

    # Document formats
    PDF = "pdf"
    TXT = "txt"


class TileSetStatus(TextChoices):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class DatasetStatus(TextChoices):
    PENDING = "pending"
    UPLOADED = "uploaded"
    FAILED = "failed"


class ProcessingJobStatus(TextChoices):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessingTool(TextChoices):
    # Raster tools.
    HILLSHADE = "hillshade"
    SLOPE = "slope"
    CONTOUR = "contour"
    CLIP_RASTER = "clip_raster"
    RASTER_CALCULATOR = "raster_calculator"

    # Vector tools.
    BUFFER = "buffer"
    CLIP_VECTOR = "clip_vector"
    DISSOLVE = "dissolve"
    CENTROID = "centroid"
    SIMPLIFY = "simplify"
    CONVEX_HULL = "convex_hull"


class ProcessingToolCategory(TextChoices):
    RASTER = "raster"
    VECTOR = "vector"


class WorkflowRunStatus(TextChoices):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowNodeStatus(TextChoices):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowNodeType(TextChoices):
    SOURCE = "source"
    OPERATION = "operation"
