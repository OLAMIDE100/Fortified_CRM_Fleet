################################################################################### GKE CLUSTER CONFIGURATION ################################################################################################################
############################################################################################################################################################################################################################

resource "google_container_cluster" "fortified-crm-fleet" {
  location   = var.region
  name       = var.solution
  network    = google_compute_network.fortified-crm-fleet.id
  project    = var.gcp_project_name
  subnetwork = google_compute_subnetwork.fortified-crm-fleet.id

  initial_node_count       = 1
  remove_default_node_pool = true
  networking_mode          = "VPC_NATIVE"
  ip_allocation_policy {}
  workload_identity_config {
    workload_pool = "${var.gcp_project_name}.svc.id.goog"
  }
  

  addons_config {
 
    dns_cache_config {
      enabled = true
    }
  }

  datapath_provider = "ADVANCED_DATAPATH"

  maintenance_policy {
    recurring_window {
      start_time = "2026-08-04T07:00:00Z"
      end_time   = "2026-08-04T20:00:00Z"
      recurrence = "FREQ=WEEKLY;BYDAY=TU"
    }
  }

  

  deletion_protection = false
  depends_on          = [google_compute_subnetwork.fortified-crm-fleet, google_service_networking_connection.fortified-crm-fleet]

}



resource "google_container_node_pool" "fortified-crm-fleet-node-pool" {
  cluster            = google_container_cluster.fortified-crm-fleet.name
  initial_node_count = 1
  location           = var.region
  max_pods_per_node  = 110
  name               = "fortified-crm-fleet-node-pool"
  project            = var.gcp_project_name
  node_locations = [
    "europe-west3-c", "europe-west3-b",
  ]

  autoscaling {
    location_policy      = "ANY"
    max_node_count       = 2
    min_node_count       = 0
    total_max_node_count = 0
    total_min_node_count = 0
  }
  management {
    auto_repair  = true
    auto_upgrade = true
  }
  node_config {
    disk_size_gb = 100
    disk_type    = "pd-ssd"
    image_type   = "COS_CONTAINERD"
    labels       = { "solution" : "fortified-crm-fleet" }
    machine_type = "e2-highcpu-4"
    metadata = {
      disable-legacy-endpoints = "true"
    }
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    resource_labels = {}
    service_account = "${google_service_account.fortified-crm-fleet.email}"
    tags            = []
    shielded_instance_config {
      enable_integrity_monitoring = true
      enable_secure_boot          = false
    }
  }
  network_config {
    enable_private_nodes = true
  }
  upgrade_settings {
    max_surge       = 1
    max_unavailable = 0
    strategy        = "SURGE"
  }
  lifecycle {
    ignore_changes = [
      node_config[0].linux_node_config,
      node_config[0].resource_labels

    ]
  }
  depends_on = [google_container_cluster.fortified-crm-fleet, google_service_account.fortified-crm-fleet]
}