#!/usr/bin/env python3
"""
compute_resources.py
Detects machine CPU cores and total RAM, computes proportional Kubernetes
resource requests/limits for each service, and writes:
  - values-computed.yaml  (passed to every helm upgrade)
  - minikube-args.env     (sourced by setup.py for minikube start)
"""
from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from dataclasses import dataclass

SCRIPT_DIR = Path(__file__).parent.resolve()


# ---------------------------------------------------------------------------
# Machine detection
# ---------------------------------------------------------------------------

def _detect_mac() -> tuple[int, int]:
    """Returns (cpu_cores, total_ram_mib) on macOS."""
    cpu = int(subprocess.check_output(["sysctl", "-n", "hw.logicalcpu"]).strip())
    ram_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
    return cpu, ram_bytes // 1024 // 1024


def _detect_linux() -> tuple[int, int]:
    """Returns (cpu_cores, total_ram_mib) on Linux."""
    cpu = int(subprocess.check_output(["nproc"]).strip())
    meminfo = Path("/proc/meminfo").read_text()
    for line in meminfo.splitlines():
        if line.startswith("MemTotal:"):
            ram_kb = int(line.split()[1])
            return cpu, ram_kb // 1024
    raise RuntimeError("Could not read MemTotal from /proc/meminfo")


def detect_machine() -> tuple[int, int]:
    """Returns (cpu_cores, total_ram_mib)."""
    system = platform.system()
    if system == "Darwin":
        return _detect_mac()
    elif system == "Linux":
        return _detect_linux()
    else:
        raise RuntimeError(f"Unsupported OS: {system}")


def docker_available_memory_mib() -> int | None:
    """
    Ask the Docker daemon how much memory its VM actually has.
    Works with OrbStack, Docker Desktop, or any Docker-compatible runtime.
    Returns MiB, or None if Docker is not reachable.
    """
    try:
        out = subprocess.check_output(
            ["docker", "info", "--format", "{{.MemTotal}}"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
        return int(out) // 1024 // 1024
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Resource model
# ---------------------------------------------------------------------------

@dataclass
class Resources:
    cpu_req_m: int   # millicores
    cpu_lim_m: int
    ram_req_mib: int
    ram_lim_mib: int

    def to_yaml_block(self, indent: int = 0) -> str:
        pad = " " * indent
        return (
            f"{pad}requests:\n"
            f"{pad}  cpu: \"{self.cpu_req_m}m\"\n"
            f"{pad}  memory: \"{self.ram_req_mib}Mi\"\n"
            f"{pad}limits:\n"
            f"{pad}  cpu: \"{self.cpu_lim_m}m\"\n"
            f"{pad}  memory: \"{self.ram_lim_mib}Mi\""
        )


@dataclass
class PostgresConfig:
    shared_buffers_mb: int
    work_mem_mb: int
    maintenance_work_mem_mb: int
    effective_cache_size_mb: int
    max_connections: int = 100


# ---------------------------------------------------------------------------
# Allocation weights  (CPU %, RAM %) — must each sum to 100
# ---------------------------------------------------------------------------

WEIGHTS: dict[str, tuple[int, int]] = {
    "postgres":  (31, 38),
    "backend":   (28, 20),
    "worker":    (16, 16),
    "seaweedfs": (12, 10),
    "redis":     ( 8, 12),
    "frontend":  ( 5,  4),
}

assert sum(w[0] for w in WEIGHTS.values()) == 100, "CPU weights must sum to 100"
assert sum(w[1] for w in WEIGHTS.values()) == 100, "RAM weights must sum to 100"

# OS headroom to reserve
CPU_HEADROOM_PCT = 20
RAM_HEADROOM_PCT = 15

# Requests are set to this fraction of the computed limit
REQUEST_FRACTION = 0.5


def compute_usable_capacity(total_cpu: int, total_ram_mib: int) -> tuple[int, int]:
    total_cpu_m = total_cpu * 1000
    usable_cpu_m = total_cpu_m * (100 - CPU_HEADROOM_PCT) // 100
    usable_ram_mib = total_ram_mib * (100 - RAM_HEADROOM_PCT) // 100
    return usable_cpu_m, usable_ram_mib


def effective_cluster_capacity(total_cpu: int, total_ram_mib: int) -> tuple[int, int]:
    usable_cpu_m, usable_ram_mib = compute_usable_capacity(total_cpu, total_ram_mib)

    # Cap workload sizing to the memory actually available to the container runtime.
    # Without this, values-computed.yaml may describe pods larger than the minikube node.
    docker_mem = docker_available_memory_mib()
    if docker_mem is not None:
        docker_cap_mib = int(docker_mem * 0.90)
        if usable_ram_mib > docker_cap_mib:
            print(
                f"⚠️  Docker VM has {docker_mem} MiB — capping allocatable RAM "
                f"from {usable_ram_mib} MiB → {docker_cap_mib} MiB"
            )
            usable_ram_mib = docker_cap_mib

    return usable_cpu_m, usable_ram_mib


def compute_allocations(usable_cpu_m: int, usable_ram_mib: int) -> dict[str, Resources]:
    allocs: dict[str, Resources] = {}
    for service, (cpu_pct, ram_pct) in WEIGHTS.items():
        lim_cpu = usable_cpu_m * cpu_pct // 100
        lim_ram = usable_ram_mib * ram_pct // 100
        req_cpu = int(lim_cpu * REQUEST_FRACTION)
        req_ram = int(lim_ram * REQUEST_FRACTION)
        allocs[service] = Resources(req_cpu, lim_cpu, req_ram, lim_ram)

    return allocs


def compute_postgres_config(pg: Resources) -> PostgresConfig:
    ram = pg.ram_lim_mib
    return PostgresConfig(
        shared_buffers_mb          = max(1, ram * 25 // 100),
        work_mem_mb                = max(4, ram *  1 // 100),
        maintenance_work_mem_mb    = max(1, ram *  6 // 100),
        effective_cache_size_mb    = max(1, ram * 75 // 100),
    )


def storage_sizes_gib(total_ram_mib: int) -> dict[str, int]:
    ram_gib = total_ram_mib // 1024
    return {
        "postgres":  max(5,  ram_gib * 20 // 16),
        "redis":     max(2,  ram_gib * 10 // 16),
        "seaweedfs": max(10, ram_gib * 50 // 16),
    }


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def write_values_computed(
    allocs: dict[str, Resources],
    pg_config: PostgresConfig,
    storage: dict[str, int],
    total_cpu: int,
    total_ram_mib: int,
    usable_cpu_m: int,
    usable_ram_mib: int,
    out_path: Path,
) -> None:
    redis_maxmem_mb = allocs["redis"].ram_lim_mib * 80 // 100

    lines = [
        "# Auto-generated by compute_resources.py — DO NOT EDIT MANUALLY",
        f"# Machine: {total_cpu} cores, {total_ram_mib} MiB RAM ({platform.system()})",
        f"# Effective cluster capacity: {usable_cpu_m}m CPU, {usable_ram_mib} MiB RAM",
        "",
        "# ── backend app ──────────────────────────────────────────────────────────────",
        "resources:",
        allocs["backend"].to_yaml_block(indent=2),
        "",
        "workerResources:",
        allocs["worker"].to_yaml_block(indent=2),
        "",
        "# ── postgres ──────────────────────────────────────────────────────────────────",
        "postgresResources:",
        allocs["postgres"].to_yaml_block(indent=2),
        "",
        f'postgresPersistence:\n  size: "{storage["postgres"]}Gi"',
        "",
        "postgresConfig:",
        f'  sharedBuffers: "{pg_config.shared_buffers_mb}MB"',
        f'  workMem: "{pg_config.work_mem_mb}MB"',
        f'  maintenanceWorkMem: "{pg_config.maintenance_work_mem_mb}MB"',
        f'  effectiveCacheSize: "{pg_config.effective_cache_size_mb}MB"',
        f'  maxConnections: "{pg_config.max_connections}"',
        "",
        "# ── redis ─────────────────────────────────────────────────────────────────────",
        "redisResources:",
        allocs["redis"].to_yaml_block(indent=2),
        "",
        f'redisPersistence:\n  size: "{storage["redis"]}Gi"',
        "",
        f'redisMaxmemory: "{redis_maxmem_mb}mb"',
        "",
        "# ── seaweedfs ─────────────────────────────────────────────────────────────────",
        "seaweedfsResources:",
        allocs["seaweedfs"].to_yaml_block(indent=2),
        "",
        f'seaweefsPersistence:\n  size: "{storage["seaweedfs"]}Gi"',
        "",
        "# ── frontend ──────────────────────────────────────────────────────────────────",
        "frontendResources:",
        allocs["frontend"].to_yaml_block(indent=2),
    ]

    out_path.write_text("\n".join(lines) + "\n")
    print(f"\n📄 Written: {out_path}")


def write_minikube_env(
    usable_cpu_m: int,
    usable_ram_mib: int,
    out_path: Path,
) -> dict:
    minikube_cpus = usable_cpu_m // 1000
    minikube_mem_mb = usable_ram_mib
    content = (
        "# Auto-generated by compute_resources.py\n"
        f"MINIKUBE_CPUS={minikube_cpus}\n"
        f"MINIKUBE_MEMORY_MB={minikube_mem_mb}\n"
    )
    out_path.write_text(content)
    print(f"📄 Written: {out_path}")

    return {"MINIKUBE_CPUS": minikube_cpus, "MINIKUBE_MEMORY_MB": minikube_mem_mb}


def print_summary(allocs: dict[str, Resources]) -> None:
    print("\nResource summary:")
    for service, r in allocs.items():
        print(
            f"  {service:<12}  "
            f"CPU req/lim: {r.cpu_req_m:>6}m / {r.cpu_lim_m:>6}m   "
            f"RAM req/lim: {r.ram_req_mib:>6}Mi / {r.ram_lim_mib:>6}Mi"
        )


# ---------------------------------------------------------------------------
# Public API  (importable by setup.py)
# ---------------------------------------------------------------------------

def run(script_dir: Path = SCRIPT_DIR) -> dict:
    """
    Detect machine resources, compute allocations, and write output files.
    Returns a dict with 'minikube' keys for use by setup.py.
    """
    total_cpu, total_ram_mib = detect_machine()
    usable_cpu_m, usable_ram_mib = effective_cluster_capacity(total_cpu, total_ram_mib)
    print(f"🖥  Machine: {total_cpu} CPU cores, {total_ram_mib} MiB RAM ({platform.system()})")
    print(f"✅  Effective cluster capacity: {usable_cpu_m}m CPU, {usable_ram_mib} MiB RAM")

    allocs = compute_allocations(usable_cpu_m, usable_ram_mib)
    pg_config = compute_postgres_config(allocs["postgres"])
    storage   = storage_sizes_gib(total_ram_mib)

    values_path  = script_dir / "values-computed.yaml"
    env_path     = script_dir / "minikube-args.env"

    write_values_computed(
        allocs, pg_config, storage,
        total_cpu, total_ram_mib, usable_cpu_m, usable_ram_mib,
        values_path,
    )
    minikube_args = write_minikube_env(usable_cpu_m, usable_ram_mib, env_path)
    print_summary(allocs)

    return {
        "values_path": values_path,
        "minikube_cpus": minikube_args["MINIKUBE_CPUS"],
        "minikube_memory_mb": minikube_args["MINIKUBE_MEMORY_MB"],
    }


if __name__ == "__main__":
    run()
