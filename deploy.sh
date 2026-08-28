#!/bin/bash
set -euo pipefail

echo "Starting complete deployment process..."

read -p "Enter the image tag: " image_tag

export TF_VAR_image_tag="${image_tag}"
export TF_VAR_gcp_project_name="${TF_VAR_gcp_project_name:-agentic-hackerton}"
export TF_VAR_region="${TF_VAR_region:-europe-west3}"

IMAGE_REGISTRY="${TF_VAR_region}-docker.pkg.dev/${TF_VAR_gcp_project_name}/fortified-crm-fleet"
NAMESPACE="fortified-crm-fleet"

# Step 1: Deploy infrastructure (AR + build/push images)
echo "=== Step 1: Deploying Infrastructure ==="
echo 'yes' | terraform -chdir=infrastructure/terraform init
echo 'yes' | terraform -chdir=infrastructure/terraform validate
terraform -chdir=infrastructure/terraform plan

read -p "ARE YOU OK WITH THE ABOVE PLAN AND WANT TO CONTINUE? (yes/no): " choice

case "$choice" in
  yes|YES|Yes)
    echo "Continuing with the script..."

    terraform -chdir=infrastructure/terraform apply -auto-approve

    echo "=== Getting cluster credentials ==="
    gcloud container clusters get-credentials fortified-crm-fleet \
      --region "${TF_VAR_region}" \
      --project "${TF_VAR_gcp_project_name}"

    echo "=== Step 2: Namespace setup ==="
    kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

    echo "=== Step 3: Render and apply manifests ==="
    RENDER_DIR="$(mktemp -d)"
    cp -r infrastructure/manifests/. "${RENDER_DIR}/"

    # Substitute registry + tag in workload images (manifests ship with v1.0.0 placeholders).
    find "${RENDER_DIR}" -name '*.yaml' -type f -print0 | while IFS= read -r -d '' file; do
      sed -i '' \
        "s|europe-west3-docker.pkg.dev/agentic-hackerton/fortified-crm-fleet/|${IMAGE_REGISTRY}/|g" \
        "${file}"
      sed -i '' "s|:v1.0.0|:${image_tag}|g" "${file}"
    done

    kubectl apply -f "${RENDER_DIR}/others/serviceaccount.yaml"
    kubectl apply -f "${RENDER_DIR}/configs/configmap.yaml"
    kubectl apply -f "${RENDER_DIR}/configs/secret.yaml"
    kubectl apply -f "${RENDER_DIR}/workload/backend/service.yaml"
    kubectl apply -f "${RENDER_DIR}/workload/backend/deployment.yaml"
    kubectl apply -f "${RENDER_DIR}/workload/frontend/service.yaml"
    kubectl apply -f "${RENDER_DIR}/workload/frontend/deployment.yaml"

    kubectl delete job fortified-crm-fleet-seed -n "${NAMESPACE}" --ignore-not-found
    kubectl apply -f "${RENDER_DIR}/workload/seed/job.yaml"

    kubectl apply -f "${RENDER_DIR}/network/frontend.yaml"
    kubectl apply -f "${RENDER_DIR}/network/managed-certificate.yaml"
    kubectl apply -f "${RENDER_DIR}/network/ingress.yaml"

    rm -rf "${RENDER_DIR}"

    echo "=== Step 4: Wait for core workloads ==="
    kubectl rollout status deployment/backend -n "${NAMESPACE}" --timeout=300s
    kubectl rollout status deployment/frontend -n "${NAMESPACE}" --timeout=300s
    kubectl wait --for=condition=complete job/fortified-crm-fleet-seed -n "${NAMESPACE}" --timeout=900s

    echo "=== Frontend external IP ==="
    kubectl get svc frontend -n "${NAMESPACE}"

    echo "Complete deployment finished!"
    ;;
  no|NO|No)
    echo "Exiting script."
    exit 1
    ;;
  *)
    echo "Invalid input. Please type yes or no."
    exit 1
    ;;
esac
