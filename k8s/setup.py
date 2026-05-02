#!/usr/bin/env python3
"""
setup.py
Full Kubernetes deployment script.
Detects machine resources, installs helm/minikube if needed,
starts minikube with computed resources, then deploys all Helm charts.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Import the resource computation module from the same directory
sys.path.insert(0, str(Path(__file__).parent))
import compute_resources

SCRIPT_DIR = Path(__file__).parent.resolve()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command, streaming output, raising on failure."""
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, cwd=SCRIPT_DIR, **kwargs)


def check_output(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def is_installed(tool: str) -> bool:
    return shutil.which(tool) is not None


def step(msg: str) -> None:
    print(f"\n{'─'*60}")
    print(f"📦 {msg}")
    print('─'*60)


# ---------------------------------------------------------------------------
# Tool installation
# ---------------------------------------------------------------------------

def ensure_helm() -> None:
    step("Checking Helm")
    if is_installed("helm"):
        print(f"✅ Helm ready: {check_output(['helm', 'version', '--short'])}")
        return

    print("⚙️  Helm not found — installing...")
    if platform.system() == "Darwin" and is_installed("brew"):
        run(["brew", "install", "helm"])
    else:
        # Official get-helm-3 installer (macOS/Linux)
        get_helm = subprocess.check_output(
            ["curl", "-fsSL", "https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3"],
        )
        subprocess.run(["bash"], input=get_helm, check=True)

    print(f"✅ Helm installed: {check_output(['helm', 'version', '--short'])}")


def ensure_minikube() -> None:
    step("Checking Minikube")
    if is_installed("minikube"):
        print(f"✅ Minikube ready: {check_output(['minikube', 'version', '--short'])}")
        return

    print("⚙️  Minikube not found — installing...")
    system = platform.system()
    arch = platform.machine()

    if system == "Darwin" and is_installed("brew"):
        run(["brew", "install", "minikube"])
    elif system == "Darwin":
        url = f"https://storage.googleapis.com/minikube/releases/latest/minikube-darwin-{arch}"
        run(["curl", "-Lo", "/tmp/minikube", url])
        run(["install", "/tmp/minikube", "/usr/local/bin/minikube"])
    else:
        run(["curl", "-Lo", "/tmp/minikube",
             "https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64"])
        run(["install", "/tmp/minikube", "/usr/local/bin/minikube"])

    print(f"✅ Minikube installed: {check_output(['minikube', 'version', '--short'])}")


# ---------------------------------------------------------------------------
# Minikube lifecycle
# ---------------------------------------------------------------------------

def minikube_is_running() -> bool:
    try:
        status = check_output(["minikube", "status", "--format={{.Host}}"])
        return status.strip() == "Running"
    except subprocess.CalledProcessError:
        return False


def minikube_current_config() -> tuple[int, int]:
    """Returns (current_cpus, current_memory_mb) from the running minikube node."""
    try:
        cpu_str = check_output([
            "kubectl", "get", "node", "minikube",
            "-o", "jsonpath={.status.capacity.cpu}",
        ])
        # memory reported as e.g. "8118080Ki"
        mem_str = check_output([
            "kubectl", "get", "node", "minikube",
            "-o", "jsonpath={.status.capacity.memory}",
        ])
        cpus = int(cpu_str.strip())
        # convert Ki → MiB
        if mem_str.endswith("Ki"):
            mem_mb = int(mem_str[:-2]) // 1024
        else:
            mem_mb = int(mem_str) // 1024 // 1024
        return cpus, mem_mb
    except (subprocess.CalledProcessError, ValueError):
        return 0, 0


def ensure_minikube_running(cpus: int, memory_mb: int) -> None:
    step(f"Starting Minikube ({cpus} CPUs, {memory_mb}MB RAM)")

    if minikube_is_running():
        current_cpus, current_mem = minikube_current_config()
        if current_cpus == cpus and current_mem == memory_mb:
            print("✅ Minikube already running with correct resources")
            return

        print(f"⚠️  Resource mismatch (running: {current_cpus}C/{current_mem}MB, "
              f"target: {cpus}C/{memory_mb}MB) — restarting...")
        run(["minikube", "stop"])
        run(["minikube", "delete"])

    run([
        "minikube", "start",
        "--cpus",   str(cpus),
        "--memory", f"{memory_mb}mb",
        "--driver", "docker",
    ])
    print("✅ Minikube running")


# ---------------------------------------------------------------------------
# Helm chart deployments
# ---------------------------------------------------------------------------

def helm(release: str, chart: str, *extra_args: str, values: Path | None = None) -> None:
    cmd = ["helm", "upgrade", "--install", release, chart]
    if values:
        cmd += ["--values", str(values)]
    cmd += list(extra_args)
    run(cmd)


def deploy_all(computed: Path) -> None:
    # 1. Gateway API CRDs
    step("Installing Gateway API CRDs")
    run(["kubectl", "apply", "-f", "platform/crds/gateway-api/standard-install.yaml"])
    # kustomize piped to kubectl
    kustomize_out = check_output([
        "kubectl", "kustomize",
        "https://github.com/nginx/nginx-gateway-fabric/config/crd/gateway-api/standard?ref=v2.2.2"
    ])
    subprocess.run(["kubectl", "apply", "-f", "-"], input=kustomize_out, text=True,
                   check=True, cwd=SCRIPT_DIR)
    print("✅ Gateway API CRDs installed")

    # 2. Gateway namespace
    step("Creating Gateway namespace")
    ns_yaml = check_output(["kubectl", "create", "namespace", "gateway-ns",
                             "--dry-run=client", "-o", "yaml"])
    subprocess.run(["kubectl", "apply", "-f", "-"], input=ns_yaml, text=True,
                   check=True, cwd=SCRIPT_DIR)
    print("✅ Gateway namespace created")

    # 3. NGINX Gateway Fabric
    step("Installing NGINX Gateway Fabric")
    helm("nginx-gateway",
         "oci://ghcr.io/nginx/charts/nginx-gateway-fabric",
         "--version", "2.2.1",
         "--namespace", "gateway-ns",
         "-f", "platform/controllers/nginx-gateway/values.yaml")
    print("✅ NGINX Gateway Fabric installed")

    # 4. Platform namespaces
    step("Installing Platform Namespaces")
    helm("platform-namespaces", "platform/namespaces")
    print("✅ Platform Namespaces installed")

    # 5. Platform gateway
    step("Installing Platform Gateway")
    helm("platform-gateway", "platform/gateway", "--namespace", "gateway-ns")
    print("✅ Platform Gateway installed")

    # 6. Databases (postgres)
    step("Installing Databases")
    helm("platform-db", "platform/databases/postgres", values=computed)
    print("✅ Databases installed")

    # 7. Cache (redis)
    step("Installing Redis Cache")
    helm("platform-cache", "platform/cache", values=computed)
    print("✅ Redis Cache installed")

    # 8. Object storage (SeaweedFS)
    step("Installing SeaweedFS Object Storage")
    helm("object-storage", "platform/storage/object", "--namespace", "default", values=computed)
    print("✅ SeaweedFS Object Storage installed")

    # Registry — docker credentials must be supplied via GHCR_PAT env var
    ghcr_pat = os.environ.get("GHCR_PAT", "")
    if not ghcr_pat:
        print("⚠️  GHCR_PAT env var not set — skipping platform-registry deploy.")
        print("   Re-run with: GHCR_PAT=<your_token> python3 setup.py")
    else:
        ghcr_email = os.environ.get("GHCR_EMAIL", "")
        helm("platform-registry", "platform/registry",
             "--namespace", "default",
             "--set", f"docker.password={ghcr_pat}",
             "--set", f"docker.email={ghcr_email}")

    # 9. Shared app components
    step("Installing Shared Application Components")
    helm("apps-shared", "apps/shared", "--namespace", "default")

    # 10. Backend
    step("Installing Backend Application")
    helm("backend", "apps/backend", "--namespace", "default", values=computed)
    print("✅ Backend Application installed")

    # 11. Frontend
    step("Installing Frontend Application")
    helm("frontend", "apps/frontend", "--namespace", "default", values=computed)
    print("✅ Frontend Application installed")

    # 12. Cloudflare tunnel
    step("Installing Cloudflare Tunnel")
    helm("cloudflared", "platform/cloudflare",
         "--namespace", "gateway-ns", "--create-namespace")
    print("✅ Cloudflare Tunnel installed")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("🚀 Starting full Kubernetes deployment...")

    # Step 0: compute resources
    step("Detecting machine resources")
    result = compute_resources.run(SCRIPT_DIR)
    computed      = result["values_path"]
    minikube_cpus = result["minikube_cpus"]
    minikube_mem  = result["minikube_memory_mb"]
    print(f"✅ Resources computed → minikube: {minikube_cpus} CPUs, {minikube_mem}MB RAM")

    # Step 1-2: ensure tools
    ensure_helm()
    ensure_minikube()

    # Step 3: start minikube
    ensure_minikube_running(minikube_cpus, minikube_mem)

    # Step 4+: deploy all charts
    deploy_all(computed)

    # Summary
    print("\n" + "=" * 50)
    print("🎉 Full deployment completed successfully!")
    print("=" * 50)
    print(f"\n  ✅ Minikube  ({minikube_cpus} CPUs, {minikube_mem}MB RAM)")
    print("  ✅ Gateway API CRDs + NGINX Gateway Fabric")
    print("  ✅ PostgreSQL · Redis · SeaweedFS")
    print("  ✅ Backend · Frontend · Cloudflare Tunnel")
    print("\nTo check status:")
    print("  kubectl get pods -A")
    print("  kubectl get gateway -n gateway-ns")


if __name__ == "__main__":
    main()
