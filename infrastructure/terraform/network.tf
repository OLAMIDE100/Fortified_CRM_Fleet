################################################################################### NETWORK CONFIGURATION ###########################################################################################################################################
####################################################################################################################################################################################################################################################

resource "google_compute_network" "fortified-crm-fleet" {
  auto_create_subnetworks         = false
  delete_default_routes_on_create = false
  name                            = var.solution
  project                         = var.gcp_project_name
  routing_mode                    = "REGIONAL"
}


resource "google_compute_subnetwork" "fortified-crm-fleet" {
  ip_cidr_range              = "10.0.0.0/20"
  name                       = var.solution
  network                    = google_compute_network.fortified-crm-fleet.id
  private_ip_google_access   = true
  private_ipv6_google_access = "DISABLE_GOOGLE_ACCESS"
  project                    = var.gcp_project_name
  purpose                    = "PRIVATE"
  region                     = var.region
  depends_on                 = [google_compute_network.fortified-crm-fleet]

}




################################################################################### NETWORK ROUTER CONFIGURATION ##################################################################################################################
###################################################################################################################################################################################################################################

resource "google_compute_address" "fortified-crm-fleet" {
  address_type = "EXTERNAL"
  ip_version   = "IPV4"
  name         = "${var.solution}-router-address"
  project      = var.gcp_project_name
  region       = var.region
  labels = {
    solution = "general"
  }
}


resource "google_compute_router" "fortified-crm-fleet" {

  encrypted_interconnect_router = false
  name                          = var.solution
  network                       = google_compute_network.fortified-crm-fleet.name
  project                       = var.gcp_project_name
  region                        = var.region
  depends_on                    = [google_compute_network.fortified-crm-fleet]

}


resource "google_compute_router_nat" "fortified-crm-fleet" {
  icmp_idle_timeout_sec              = 30
  max_ports_per_vm                   = 0
  min_ports_per_vm                   = 0
  name                               = var.solution
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.fortified-crm-fleet.id]
  project                            = var.gcp_project_name
  region                             = var.region
  router                             = google_compute_router.fortified-crm-fleet.name
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
  tcp_established_idle_timeout_sec   = 1200
  tcp_time_wait_timeout_sec          = 120
  tcp_transitory_idle_timeout_sec    = 30
  udp_idle_timeout_sec               = 30

}

################################################################################### NETWORK VPC PEERING CONFIGURATION ####################################################################################################
##########################################################################################################################################################################################################################

resource "google_compute_global_address" "fortified-crm-fleet" {

  name          = "${var.solution}-vpc-peering-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.fortified-crm-fleet.id
  labels = {
    solution = "fortified-crm-fleet"
  }
}

resource "google_service_networking_connection" "fortified-crm-fleet" {

  network                 = google_compute_network.fortified-crm-fleet.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.fortified-crm-fleet.name]
  depends_on              = [google_compute_global_address.fortified-crm-fleet, google_compute_network.fortified-crm-fleet]
}


################################################################################################### DOMAIN CONFIGURATION ########################################################################################################
#####################################################################################################################################################################################################################

resource "google_compute_global_address" "fortified-crm-fleet-domain" {
  address_type = "EXTERNAL"
  ip_version   = "IPV4"
  name         = "fortified-crm-fleet"
  project      = var.gcp_project_name
  labels       = {
    solution = "fortified-crm-fleet"
  }
}


resource "google_dns_record_set" "fortified-crm-fleet-domain" {
  name    = "fortified-crm-fleet.wolfcore.app."
  type    = "A"
  ttl     = 300
  project = var.gcp_project_name

  managed_zone = "wolfcore"

  rrdatas = [google_compute_global_address.fortified-crm-fleet-domain.address]

  depends_on = [google_compute_global_address.fortified-crm-fleet-domain]
}