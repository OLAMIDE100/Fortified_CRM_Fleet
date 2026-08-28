################################################################################################################### GENERAL IMAGE REPOSITORY  CONFIGURATION #########################################################################################
#######################################################################################################################################################################################################################################


resource "google_artifact_registry_repository" "fortified-crm-fleet" {
  location      = var.region
  repository_id = "fortified-crm-fleet"
  description   = "Docker repository for fortified-crm-fleet images"
  format        = "DOCKER"
  labels = {
    solution = "fortified-crm-fleet"
  }
}



resource "null_resource" "build_and_push_fortified-crm-fleet_backend_docker_image" {
          triggers = {
            always_run = timestamp()
          }

          provisioner "local-exec" {
            command = <<EOT
              docker build --platform linux/amd64 -f ../../backend/Dockerfile -t ${google_artifact_registry_repository.fortified-crm-fleet.location}-docker.pkg.dev/${var.gcp_project_name}/${google_artifact_registry_repository.fortified-crm-fleet.repository_id}/fortified-crm-fleet-backend:${var.image_tag} ../../
              gcloud auth configure-docker ${google_artifact_registry_repository.fortified-crm-fleet.location}-docker.pkg.dev
              docker push ${google_artifact_registry_repository.fortified-crm-fleet.location}-docker.pkg.dev/${var.gcp_project_name}/${google_artifact_registry_repository.fortified-crm-fleet.repository_id}/fortified-crm-fleet-backend:${var.image_tag}
            EOT
          }
          depends_on         = [ google_artifact_registry_repository.fortified-crm-fleet ]
}


resource "null_resource" "build_and_push_fortified-crm-fleet_frontend_docker_image" {
          triggers = {
            always_run = timestamp()
            
          }

          provisioner "local-exec" {
            command = <<EOT
              docker build --platform linux/amd64 -t ${google_artifact_registry_repository.fortified-crm-fleet.location}-docker.pkg.dev/${var.gcp_project_name}/${google_artifact_registry_repository.fortified-crm-fleet.repository_id}/fortified-crm-fleet-frontend:${var.image_tag} ../../frontend
              gcloud auth configure-docker ${google_artifact_registry_repository.fortified-crm-fleet.location}-docker.pkg.dev
              docker push ${google_artifact_registry_repository.fortified-crm-fleet.location}-docker.pkg.dev/${var.gcp_project_name}/${google_artifact_registry_repository.fortified-crm-fleet.repository_id}/fortified-crm-fleet-frontend:${var.image_tag}
            EOT
          }
          depends_on         = [ google_artifact_registry_repository.fortified-crm-fleet ]
}

resource "null_resource" "build_and_push_fortified-crm-fleet_seed_docker_image" {
          triggers = {
            always_run = timestamp()
          }

          provisioner "local-exec" {
            command = <<EOT
              docker build --platform linux/amd64 -f ../../data_ingestion/Dockerfile -t ${google_artifact_registry_repository.fortified-crm-fleet.location}-docker.pkg.dev/${var.gcp_project_name}/${google_artifact_registry_repository.fortified-crm-fleet.repository_id}/fortified-crm-fleet-seed:${var.image_tag} ../..
              gcloud auth configure-docker ${google_artifact_registry_repository.fortified-crm-fleet.location}-docker.pkg.dev
              docker push ${google_artifact_registry_repository.fortified-crm-fleet.location}-docker.pkg.dev/${var.gcp_project_name}/${google_artifact_registry_repository.fortified-crm-fleet.repository_id}/fortified-crm-fleet-seed:${var.image_tag}
            EOT
          }
          depends_on         = [ google_artifact_registry_repository.fortified-crm-fleet ]
}