# Hydrosat Geospatial Data Pipeline

A production-ready geospatial data pipeline demonstrating Apache Airflow on Kubernetes with field-level satellite imagery processing.

## 🎯 Features

- **Field-Level Processing**: Agricultural fields with polygon geometries and planting dates
- **Dynamic Task Mapping**: Airflow DAGs with `expand()` for parallel per-field processing
- **Planting-Date Awareness**: Fields processed only after their planting date
- **Day-over-Day Dependencies**: Processing DAG waits for satellite data ingestion
- **Kubernetes-Native**: Tasks run as Kubernetes pods (KubernetesExecutor)
- **S3-Compatible Storage**: MinIO for local development, swappable for cloud S3
- **Synthetic Data Generation**: No external API keys required
- **Infrastructure as Code**: Terraform for reproducible deployments

## 📁 Project Structure

```
hydrosat-technical-test/
├── infra/                      # Terraform IaC
│   ├── main.tf                 # Providers & namespaces
│   ├── minio.tf                # MinIO deployment
│   ├── airflow.tf              # Airflow deployment
│   ├── variables.tf            # Configuration variables
│   ├── outputs.tf              # Service URLs & info
│   └── values/                 # Helm chart values (YAML)
│       ├── minio-values.yaml   # MinIO configuration
│       └── airflow-values.yaml # Airflow configuration
├── src/hydrosat/               # Python package
│   ├── config.py               # Configuration management (AOI, fields)
│   ├── generators/             # Synthetic data generation
│   │   ├── satellite_data.py   # AOI raster generation
│   │   └── field_data.py       # Field polygon & planting date generation
│   ├── clients/                # External service clients
│   │   └── storage.py          # S3/MinIO client
│   └── services/               # Business logic
│       ├── ingestion.py        # AOI satellite data ingestion
│       └── processing.py       # Field-level processing & NDVI
├── dags/                       # Airflow DAGs
│   ├── satellite_ingestion_dag.py  # DAG 1: AOI satellite data ingestion
│   └── field_processing_dag.py     # DAG 2: Dynamic field processing
├── tests/                      # Unit tests (57 tests)
├── scripts/                    # Helper scripts
│   ├── start_minikube.sh       # Start Kubernetes cluster
│   ├── deploy.sh               # Deploy infrastructure
│   └── access_services.sh      # Get service URLs
└── pyproject.toml
```

## 🚀 Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- [Minikube](https://minikube.sigs.k8s.io/docs/start/)
- [Terraform](https://developer.hashicorp.com/terraform/install)
- [uv](https://github.com/astral-sh/uv) (Python package manager)

### 1. Start Minikube

```bash
./scripts/start_minikube.sh
```

Or manually:

```bash
minikube start --cpus=2 --memory=4096
```

### 2. Deploy Infrastructure

```bash
./scripts/deploy.sh
```

Or manually:

```bash
cd infra
terraform init
terraform apply
```

### 3. Access Services

```bash
# Get service URLs
./scripts/access_services.sh

# Or directly:
minikube service airflow-webserver -n airflow  # Airflow UI
minikube service minio-console -n minio         # MinIO Console
```

**Default Credentials:**

- Airflow: `admin` / `admin`
- MinIO: `minioadmin` / `minioadmin`

### 4. Run DAGs

1. Open Airflow UI
2. Enable `satellite_ingestion` DAG - ingests daily satellite data for AOI
3. Trigger a run (or wait for schedule)
4. Enable `field_processing` DAG - processes each field dynamically
5. Observe dynamic task generation (one task per eligible field)

## 🧪 Running Tests

```bash
# Install dev dependencies
uv sync --all-extras

# Run tests
uv run pytest tests/ -v

# With coverage
uv run pytest tests/ -v --cov=hydrosat
```

## 📊 DAG Overview

### DAG 1: Satellite Ingestion (`satellite_ingestion`)

Ingests daily satellite data for the Area of Interest (AOI):

```
check_satellite_availability() → generate_aoi_raster() → log_summary()
```

- Checks satellite data availability for execution date
- Generates synthetic multi-band raster (B02, B03, B04, B08)
- Stores raster in MinIO `raw-imagery` bucket

### DAG 2: Field Processing (`field_processing`)

Demonstrates **dynamic task mapping** with **planting-date-aware** processing:

```
wait_for_satellite_data() → discover_eligible_fields() → [process_field × N fields] → generate_report()
```

- **Sensor**: Waits for satellite data from DAG 1
- **Discovery**: Finds fields where `planting_date <= execution_date`
- **Dynamic Tasks**: Creates N parallel tasks (one per eligible field)
- **Processing**: Computes NDVI and band statistics for each field
- **Report**: Aggregates results to `processed-data` bucket

### Field Model

Each field has:

- `field_id`: Unique identifier
- `geometry`: Polygon coordinates
- `crop_type`: wheat, corn, soybean, sunflower
- `planting_date`: Date when crop was planted
- `area_hectares`: Field size

## ⚙️ Configuration

Environment variables (set in Terraform or manually):

| Variable           | Default          | Description                  |
| ------------------ | ---------------- | ---------------------------- |
| `MINIO_ENDPOINT`   | `localhost:9000` | MinIO API endpoint           |
| `MINIO_ACCESS_KEY` | `minioadmin`     | MinIO access key             |
| `MINIO_SECRET_KEY` | `minioadmin`     | MinIO secret key             |
| `RAW_BUCKET`       | `raw-imagery`    | Bucket for satellite rasters |
| `PROCESSED_BUCKET` | `processed-data` | Bucket for field reports     |
| `AOI_NAME`         | `europe-sample`  | Area of Interest name        |
| `NUM_FIELDS`       | `6`              | Number of fields to generate |

## 🏗️ Design Principles

| Principle  | Application                                |
| ---------- | ------------------------------------------ |
| **KISS**   | Simple functions, no complex abstractions  |
| **DRY**    | Shared clients/services across DAGs        |
| **YAGNI**  | Only what's needed for the challenge       |
| **SoC**    | Generators, clients, services are separate |
| **DI/IoC** | Config passed to functions, easy testing   |

## 📚 Resources & Documentation

### Core Technologies

| Technology     | Version | Documentation                                                                    |
| -------------- | ------- | -------------------------------------------------------------------------------- |
| Apache Airflow | 2.8.1   | [docs.apache.org/airflow](https://airflow.apache.org/docs/apache-airflow/2.8.1/) |
| Kubernetes     | 1.28+   | [kubernetes.io/docs](https://kubernetes.io/docs/home/)                           |
| Terraform      | ≥1.0.0  | [terraform.io/docs](https://developer.hashicorp.com/terraform/docs)              |
| MinIO          | Latest  | [min.io/docs](https://docs.min.io/enterprise/aistor-object-store/)                    |
| Minikube       | Latest  | [minikube.sigs.k8s.io](https://minikube.sigs.k8s.io/docs/)                       |

### Helm Charts

| Chart          | Version | Source                                                                                             |
| -------------- | ------- | -------------------------------------------------------------------------------------------------- |
| Apache Airflow | 1.13.1  | [airflow.apache.org/docs/helm-chart](https://airflow.apache.org/docs/helm-chart/stable/index.html) |
| MinIO          | 5.0.15  | [github.com/minio/minio/helm](https://github.com/minio/minio/tree/master/helm/minio)               |

### Python Dependencies

| Package        | Version | Purpose                |
| -------------- | ------- | ---------------------- |
| boto3          | ≥1.34.0 | S3/MinIO client        |
| numpy          | ≥1.26.0 | Raster data processing |
| apache-airflow | 2.8.1   | Workflow orchestration |

### Terraform Providers

| Provider             | Version | Registry                                                                                                                         |
| -------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------- |
| hashicorp/kubernetes | ~>2.25  | [registry.terraform.io/providers/hashicorp/kubernetes](https://registry.terraform.io/providers/hashicorp/kubernetes/latest/docs) |
| hashicorp/helm       | ~>2.12  | [registry.terraform.io/providers/hashicorp/helm](https://registry.terraform.io/providers/hashicorp/helm/latest/docs)             |

## 🤖 AI Tools Disclosure

This project was developed with assistance from:

- **Claude** (Anthropic) — Code review, refactoring, and documentation
- **Gemini** (Google) — Infrastructure simplification and best practices

AI was used for auto-completion, explanations, and iterative improvements.

## 🧹 Cleanup

```bash
# Destroy infrastructure
cd infra && terraform destroy

# Stop Minikube
minikube stop

# Delete Minikube cluster
minikube delete
```
