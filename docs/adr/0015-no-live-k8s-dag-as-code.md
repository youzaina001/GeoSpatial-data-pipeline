# Remove live Kubernetes IaC; Airflow ships as a DAG that wraps the CLI

infra/, Helm values, and Minikube scripts leave the live tree (deleted or archived as v0) so a clone cannot apply a broken stack. v1 keeps one DAG file that calls the Python pipeline and is unit-tested. Nobody must start a scheduler or a cluster to produce Field-days.
