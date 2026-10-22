mock_provider "cherryservers" {
  mock_data "cherryservers_plan" {
    defaults = {
      pricing = [{ currency = "EUR", price = 0.015, unit = "Hourly" }]
      available_regions = [{
        slug = "LT-Siauliai", stock_qty = 1, spot_qty = 0, id = 1,
        name = "Lithuania", location = "Lithuania", region_iso_2 = "LT",
        bgp  = { asn = 16125, hosts = [] }
      }]
    }
  }
}

variables {
  project_id          = 123456
  region              = "LT-Siauliai"
  ssh_public_key_path = "tests/admin.pub"
}

run "small_hourly_node" {
  command = plan

  assert {
    condition = (
      cherryservers_server.vpn.cycle == "hourly" &&
      cherryservers_server.vpn.spot_instance == false &&
      cherryservers_server.vpn.allow_reinstall == false &&
      cherryservers_server.vpn.plan == "B1-1-1gb-20s-shared"
    )
    error_message = "The test must remain a smallest, non-spot hourly VM without implicit reinstalls."
  }
}

run "refuse_price_increase" {
  command = plan

  override_data {
    target = data.cherryservers_plan.vpn
    values = {
      pricing = [{ currency = "EUR", price = 0.016, unit = "Hourly" }]
      available_regions = [{
        slug = "LT-Siauliai", stock_qty = 1, spot_qty = 0, id = 1,
        name = "Lithuania", location = "Lithuania", region_iso_2 = "LT",
        bgp  = { asn = 16125, hosts = [] }
      }]
    }
  }

  expect_failures = [cherryservers_server.vpn]
}

run "refuse_unknown_currency" {
  command = plan

  override_data {
    target = data.cherryservers_plan.vpn
    values = {
      pricing = [{ currency = "USD", price = 0.015, unit = "Hourly" }]
      available_regions = [{
        slug = "LT-Siauliai", stock_qty = 1, spot_qty = 0, id = 1,
        name = "Lithuania", location = "Lithuania", region_iso_2 = "LT",
        bgp  = { asn = 16125, hosts = [] }
      }]
    }
  }

  expect_failures = [cherryservers_server.vpn]
}

run "refuse_missing_hourly_price" {
  command = plan

  override_data {
    target = data.cherryservers_plan.vpn
    values = {
      pricing = [{ currency = "EUR", price = 3.5, unit = "Monthly" }]
      available_regions = [{
        slug = "LT-Siauliai", stock_qty = 1, spot_qty = 0, id = 1,
        name = "Lithuania", location = "Lithuania", region_iso_2 = "LT",
        bgp  = { asn = 16125, hosts = [] }
      }]
    }
  }

  expect_failures = [cherryservers_server.vpn]
}

run "refuse_no_stock" {
  command = plan

  variables {
    region = "NL-Amsterdam"
  }

  expect_failures = [cherryservers_server.vpn]
}

run "refuse_larger_vm" {
  command = plan

  variables {
    plan = "B1-2-2gb-40s-shared"
  }

  expect_failures = [var.plan]
}
