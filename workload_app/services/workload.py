from dataclasses import dataclass

UNDER_THRESHOLD = 0.7
OVER_THRESHOLD = 1.0


@dataclass
class LoadResult:
    active_count: int
    capacity: int
    ratio: float
    status: str


def compute_load(employee) -> LoadResult:
    """Compute load status for an employee based on active work-item count vs capacity."""
    active_count = employee.work_items.exclude(status="DONE").count()
    capacity = max(employee.capacity, 1)
    ratio = active_count / capacity

    if ratio < UNDER_THRESHOLD:
        load_status = "UNDER"
    elif ratio <= OVER_THRESHOLD:
        load_status = "HEALTHY"
    else:
        load_status = "OVER"

    return LoadResult(
        active_count=active_count,
        capacity=employee.capacity,
        ratio=round(ratio, 2),
        status=load_status,
    )
