output "hourly_quote" {
  description = "Catalogue compute quote only, excluding taxes, network overage and any other charges."
  value       = local.hourly_price
}

output "server_id" {
  value = cherryservers_server.vpn.id
}

output "ip_addresses" {
  description = "Inspect public address type before connecting; do not accidentally choose a private address."
  value       = cherryservers_server.vpn.ip_addresses
}
