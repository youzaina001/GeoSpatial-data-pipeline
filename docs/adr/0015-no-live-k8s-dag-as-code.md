# Remove live Kubernetes IaC; Airflow ships as a DAG that wraps the CLI

_Status: archived 2026-11-21 with the satellite example ([ADR 0021](0021-archive-the-satellite-example.md)). It describes code under `archive/v1-satellite/`, not the supported build._

infra/, Helm values, and Minikube scripts leave the live tree (deleted or archived as v0) so a clone cannot apply a broken stack. v1 keeps one DAG file that calls the Python pipeline and is unit-tested. Nobody must start a scheduler or a cluster to produce Field-days.
