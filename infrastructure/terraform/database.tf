################################################################################################### DATABASE INSTANCE CONFIGURATION ########################################################################################################
#####################################################################################################################################################################################################################
resource "google_sql_database_instance" "fortified-crm-fleet" {
  database_version    = "POSTGRES_14"
  deletion_protection = false
  name                = var.solution
  project             = var.gcp_project_name
  region              = var.region
  depends_on          = [google_compute_subnetwork.fortified-crm-fleet, google_service_networking_connection.fortified-crm-fleet]
  root_password       = var.root_password

  settings {
    availability_type = "ZONAL"
    tier              = "db-custom-1-3840"
    backup_configuration {
      binary_log_enabled             = false
      enabled                        = true
      location                       = "eu"
      point_in_time_recovery_enabled = true
      start_time                     = "17:00"
      transaction_log_retention_days = 7

      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }
    }



    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = google_compute_network.fortified-crm-fleet.id
      enable_private_path_for_google_cloud_services = true
    }


  }

}


################################################################################################### DATABASE  CONFIGURATION ########################################################################################################
#####################################################################################################################################################################################################################
resource "google_sql_database" "fortified-crm-fleet" {
  name     = "fortified-crm-fleet"
  instance = google_sql_database_instance.fortified-crm-fleet.name
  project  = var.gcp_project_name
  depends_on = [google_sql_database_instance.fortified-crm-fleet]
}

resource "google_sql_user" "fortified-crm-fleet" {
  name     = "fortified-crm-fleet"
  instance = google_sql_database_instance.fortified-crm-fleet.name
  project  = var.gcp_project_name
  password = var.root_password
  depends_on = [google_sql_database.fortified-crm-fleet]
}