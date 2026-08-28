

################################################################################################### SERVICE ACCOUNT AND IAM CONFIGURATION ########################################################################################################
#####################################################################################################################################################################################################################


resource "google_service_account" "fortified-crm-fleet" {
  account_id   = "fortified-crm-fleet"
  display_name = "Fortified CRM Fleet"
  description = "fortified-crm-fleet service account for workload identity"
}


resource "google_service_account_iam_member" "fortified-crm-fleet_workload_identity_user" {
  service_account_id =  "projects/${var.gcp_project_name}/serviceAccounts/${google_service_account.fortified-crm-fleet.email}"
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.gcp_project_name}.svc.id.goog[fortified-crm-fleet/fortified-crm-fleet]"
  depends_on         = [google_service_account.fortified-crm-fleet]
}

resource "google_project_iam_member" "fortified-crm-fleet_artifact_repository_reader" {
  project = var.gcp_project_name
  role = "roles/artifactregistry.reader"
  member = "serviceAccount:${google_service_account.fortified-crm-fleet.email}"
  depends_on = [google_service_account_iam_member.fortified-crm-fleet_workload_identity_user]
}

resource "google_project_iam_member" "fortified-crm-fleet_artifact_logs_writer" {
  project = var.gcp_project_name
  role = "roles/logging.logWriter"
  member = "serviceAccount:${google_service_account.fortified-crm-fleet.email}"
  depends_on = [google_project_iam_member.fortified-crm-fleet_artifact_repository_reader]
}

resource "google_project_iam_member" "fortified-crm-fleet_monitoring_metric_writer" {
  project = var.gcp_project_name
  role = "roles/monitoring.metricWriter"
  member = "serviceAccount:${google_service_account.fortified-crm-fleet.email}"
  depends_on = [google_project_iam_member.fortified-crm-fleet_artifact_logs_writer]
}

resource "google_project_iam_member" "fortified-crm-fleet_secret_manager_accessor" {
  project = var.gcp_project_name
  role = "roles/secretmanager.secretAccessor"
  member = "serviceAccount:${google_service_account.fortified-crm-fleet.email}"
  depends_on = [google_project_iam_member.fortified-crm-fleet_monitoring_metric_writer]
}

################################################################################################### SSL POLICY CONFIGURATION ########################################################################################################
#####################################################################################################################################################################################################################

resource "google_compute_ssl_policy" "fortified-crm-fleet-ssl-policy" {
  name = "restricted-ssl-policy"
  project = var.gcp_project_name
  min_tls_version = "TLS_1_2"
  profile = "RESTRICTED"
}


