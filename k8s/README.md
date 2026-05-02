# Atlas Platform — Kubernetes Deployment

Self-contained Kubernetes setup for the Atlas Platform, targeting a single-node minikube cluster. Resource allocation is computed automatically from the host machine's specs at deploy time.

---

## Quick Start

```bash
# With a GHCR personal access token (required to pull private images):
GHCR_PAT=<your_token> python3 setup.py
```

`setup.py` handles everything: installs Helm and minikube if missing, detects machine resources, computes allocations, starts minikube, and deploys all charts in order.

---

## How Resource Allocation Works

`compute_resources.py` detects CPU cores and RAM, reserves headroom for the OS, then distributes the remainder across services by weight:

| Service    | CPU weight | RAM weight |
|------------|:----------:|:----------:|
| PostgreSQL | 31 %       | 38 %       |
| Backend    | 28 %       | 20 %       |
| Worker     | 16 %       | 16 %       |
| SeaweedFS  | 12 %       | 10 %       |
| Redis      | 8 %        | 12 %       |
| Frontend   | 5 %        | 4 %        |

Results are written to `values-computed.yaml` and `minikube-args.env`, both of which are auto-generated — do not edit them manually.

---

## Components

### Application

| Chart | Release name | Namespace | Endpoint |
|-------|-------------|-----------|----------|
| `apps/backend` | `backend` | `default` | `api.worldofapps.bar` |
| `apps/frontend` | `frontend` | `default` | `worldofapps.bar` |

- **Backend** — Django 5 + Uvicorn on port 8000. Includes an HPA (1–4 replicas, CPU target 50 %).
- **Worker** — Celery worker sharing the same image, separate Deployment, 2 concurrent tasks.

### Platform Infrastructure

| Chart | Release name | Namespace | Internal address |
|-------|-------------|-----------|-----------------|
| `platform/databases/postgres` | `platform-db` | `default` | `postgres:5432` |
| `platform/cache` | `platform-cache` | `default` | `redis:6379` |
| `platform/storage/object` | `object-storage` | `default` | `seaweedfs-s3:8333` |

- **PostgreSQL 17 + PostGIS** — StatefulSet, tuned `postgresql.conf` values derived from its RAM limit (shared\_buffers, work\_mem, etc.).
- **Redis 7.4** — StatefulSet, RDB + AOF persistence, `allkeys-lru` eviction.
- **SeaweedFS** — All-in-one master + volume + S3 API + filer. Exposed publicly at `s3.worldofapps.bar`.

### Networking

| Chart | Release name | Namespace |
|-------|-------------|-----------|
| `platform/crds/gateway-api` | *(kubectl apply)* | cluster-wide |
| `platform/controllers/nginx-gateway` | `nginx-gateway` | `gateway-ns` |
| `platform/gateway` | `platform-gateway` | `gateway-ns` |
| `platform/cloudflare` | `cloudflared` | `gateway-ns` |

Traffic enters via a Cloudflare Tunnel → NGINX Gateway Fabric → HTTPRoutes:

```
worldofapps.bar       →  frontend-app-service:80
api.worldofapps.bar   →  backend-app-service:80
s3.worldofapps.bar    →  seaweedfs-s3:8333
```

### Supporting

| Chart | Release name | Namespace |
|-------|-------------|-----------|
| `platform/registry` | `platform-registry` | `default` |
| `platform/namespaces` | `platform-namespaces` | cluster-wide |
| `apps/shared` | `apps-shared` | `default` |

---

## Directory Structure

```
k8s/
├── apps/
│   ├── backend/          # Django backend + Celery worker
│   ├── frontend/         # React frontend
│   └── shared/           # ServiceAccount
├── platform/
│   ├── cache/            # Redis
│   ├── cloudflare/       # Cloudflare Tunnel
│   ├── controllers/      # NGINX Gateway Fabric values
│   ├── crds/             # Gateway API CRDs
│   ├── databases/
│   │   └── postgres/     # PostgreSQL + PostGIS
│   ├── gateway/          # Gateway + HTTPRoutes
│   ├── namespaces/       # Namespace + RBAC grants
│   ├── registry/         # GHCR image pull secret
│   └── storage/
│       └── object/       # SeaweedFS (S3-compatible)
├── k6/                   # Load test scripts
├── compute_resources.py  # Resource calculator (run via setup.py)
├── setup.py              # One-shot full deployment script
├── values-computed.yaml  # Auto-generated — do not edit
└── minikube-args.env     # Auto-generated — do not edit
```

---

## Useful Commands

```bash
# Check all pods
kubectl get pods -A

# Tail backend logs
kubectl logs -l app=backend-app --tail=100 -f

# Open a Django shell
kubectl exec -it deploy/backend-app -- python manage.py shell

# Recalculate resources without redeploying
python3 compute_resources.py

# Run load tests (requires k6)
cd k6 && k6 run load.ts
```
