"""Offline checks for monitoring's inventory/provisioning contract."""

import copy
import json
from pathlib import Path
import unittest

import jinja2
import yaml
from ansible.plugins.filter.core import to_bool


STACK = Path(__file__).resolve().parents[1]
ROOT = STACK.parents[1]


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        inventory = yaml.safe_load((ROOT / "monitoring.inventory.yml").read_text())
        children = inventory["all"]["children"]
        self.groups = {
            name: list(group.get("hosts", {})) for name, group in children.items()
        }
        defaults = children["monitored_nodes"]["vars"]
        self.hostvars = {
            name: {
                **defaults,
                "ansible_host": f"{name}.example.test",
                **(settings or {}),
            }
            for name, settings in children["monitored_nodes"]["hosts"].items()
        }
        self.environment = jinja2.Environment(
            undefined=jinja2.StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.environment.filters["to_json"] = json.dumps
        self.environment.filters["bool"] = to_bool

    def prometheus(self):
        template = self.environment.from_string(
            (STACK / "prometheus.yml.j2").read_text()
        )
        rendered = template.render(groups=self.groups, hostvars=self.hostvars)
        return yaml.safe_load(rendered)

    def targets(self, job):
        jobs = {
            entry["job_name"]: entry for entry in self.prometheus()["scrape_configs"]
        }
        return {
            entry["labels"]["node"]: entry
            for entry in jobs[job]["static_configs"]
        }

    def test_active_nodes_ports_and_alert_opt_in(self):
        targets = self.targets("nodeexporter")
        self.assertEqual(set(targets), {"workstation", "pi", "nk1", "nt1"})
        self.assertEqual(targets["workstation"]["targets"], ["nodeexporter:9100"])
        self.assertEqual(targets["nk1"]["targets"], ["nk1.example.test:9100"])
        self.assertEqual(targets["nt1"]["targets"], ["nt1.example.test:901"])
        self.assertEqual(self.targets("cadvisor")["nk1"]["targets"], ["nk1.example.test:3003"])
        self.assertEqual(self.targets("cadvisor")["nt1"]["targets"], ["nt1.example.test:900"])
        opted_in = {
            node for node, target in targets.items()
            if target["labels"]["availability_alert"] == "true"
        }
        self.assertEqual(opted_in, {"nk1", "nt1"})
        for target in targets.values():
            self.assertIsInstance(target["labels"]["availability_alert"], str)

    def test_retired_nodes_are_excluded_even_if_added_to_monitored_group(self):
        for host in self.groups["retired_nodes"]:
            self.groups["monitored_nodes"].append(host)
            self.hostvars[host] = copy.deepcopy(self.hostvars["nk1"])
        self.assertEqual(set(self.targets("nodeexporter")), {"workstation", "pi", "nk1", "nt1"})
        self.assertEqual(set(self.targets("cadvisor")), {"workstation", "pi", "nk1", "nt1"})

    def test_disabled_nodes_are_not_scraped(self):
        for disabled in (False, "false"):
            with self.subTest(disabled=disabled):
                self.hostvars["nk1"]["monitoring_enabled"] = disabled
                self.assertNotIn("nk1", self.targets("nodeexporter"))
                self.assertNotIn("nk1", self.targets("cadvisor"))

    def test_string_false_does_not_enable_availability_alerts(self):
        self.hostvars["nk1"]["monitoring_availability_alert"] = "false"
        self.assertEqual(
            self.targets("nodeexporter")["nk1"]["labels"]["availability_alert"], "false"
        )

    def test_new_node_and_address_override_need_no_new_jobs(self):
        self.groups["monitored_nodes"].append("newnode")
        self.hostvars["newnode"] = {
            "ansible_host": "ssh.example.test",
            "monitoring_address": "10.10.10.10",
            "monitoring_node": "stable-name",
            "monitoring_client_node_exporter_port": 9991,
            "monitoring_client_cadvisor_port": 9990,
        }
        self.assertEqual(
            self.targets("nodeexporter")["stable-name"]["targets"],
            ["10.10.10.10:9991"],
        )
        self.assertEqual(len(self.prometheus()["scrape_configs"]), 4)

    def test_no_empty_gpu_job_when_gpu_node_is_disabled(self):
        self.hostvars["local_workstation"]["monitoring_enabled"] = False
        jobs = [job["job_name"] for job in self.prometheus()["scrape_configs"]]
        self.assertNotIn("nvidia-gpu-exporter", jobs)

    def test_dashboards_use_stable_datasource_and_node_selector(self):
        dashboards = list((STACK / "grafana/dashboards").glob("*.json"))
        self.assertEqual(len(dashboards), 2)
        uids = set()
        for path in dashboards:
            dashboard = json.loads(path.read_text())
            uids.add(dashboard["uid"])
            self.assertFalse(dashboard["editable"])
            self.assertNotIn("__NODE_NAME__", path.read_text())
            self.assertEqual(dashboard["templating"]["list"][0]["name"], "node")
            for panel in dashboard["panels"]:
                self.assertEqual(panel["datasource"]["uid"], "monitoring-prometheus")
                for query in panel["targets"]:
                    self.assertIn('node=~"$node"', query["expr"])
                    self.assertNotIn("nodeexporter-", query["expr"])
                    self.assertNotIn("cadvisor-", query["expr"])
        self.assertEqual(uids, {"monitoring-nodes", "monitoring-containers"})

    def test_alert_is_multidimensional_and_independent_of_dashboard_variables(self):
        rules = yaml.safe_load(
            (STACK / "grafana/provisioning/alerting/rules.yml").read_text()
        )
        rule = rules["groups"][0]["rules"][0]
        query, condition = rule["data"]
        self.assertEqual(rule["for"], "2m")
        self.assertEqual(rule["noDataState"], "NoData")
        self.assertEqual(rule["execErrState"], "Error")
        self.assertEqual(query["datasourceUid"], "monitoring-prometheus")
        self.assertEqual(query["model"]["expr"], 'up{job="nodeexporter", availability_alert="true"}')
        self.assertTrue(query["model"]["instant"])
        self.assertEqual(condition["model"]["type"], "threshold")
        self.assertEqual(condition["model"]["conditions"][0]["evaluator"], {"type": "lt", "params": [1]})

    def test_telegram_template_preserves_numeric_ids_and_literal_dollars(self):
        template = self.environment.from_string(
            (STACK / "grafana/provisioning/alerting/contact-points.yml.j2").read_text()
        )
        rendered = yaml.safe_load(template.render(
            monitoring_telegram_bot_token="123:dummy$literal",
            monitoring_telegram_chat_id=-100123456,
        ))
        contact = rendered["contactPoints"][0]
        receiver = contact["receivers"][0]
        self.assertEqual(receiver["type"], "telegram")
        self.assertEqual(receiver["settings"]["bottoken"], "123:dummy$$literal")
        self.assertEqual(receiver["settings"]["chatid"], "-100123456")
        policies = yaml.safe_load(
            (STACK / "grafana/provisioning/alerting/policies.yml").read_text()
        )
        self.assertEqual(policies["policies"][0]["receiver"], contact["name"])
        self.assertIn("node", policies["policies"][0]["group_by"])

    def test_provisioning_paths_and_datasource_uids_match(self):
        compose = yaml.safe_load((STACK / "compose.yml").read_text())
        volumes = compose["services"]["grafana"]["volumes"]
        self.assertIn("./grafana/provisioning:/etc/grafana/provisioning:ro", volumes)
        self.assertIn("./grafana/dashboards:/etc/grafana/dashboards:ro", volumes)
        providers = yaml.safe_load(
            (STACK / "grafana/provisioning/dashboards/monitoring.yml").read_text()
        )
        self.assertEqual(providers["providers"][0]["options"]["path"], "/etc/grafana/dashboards")
        self.assertFalse(providers["providers"][0]["disableDeletion"])
        sources = yaml.safe_load(
            (STACK / "grafana/provisioning/datasources/monitoring.yml").read_text()
        )
        self.assertEqual(
            {source["uid"] for source in sources["datasources"]},
            {"monitoring-prometheus", "monitoring-loki"},
        )

    def test_client_deploy_excludes_server_and_retired_nodes(self):
        client = yaml.safe_load((STACK / "deploy-clients.yml").read_text())[0]
        self.assertEqual(client["hosts"], "monitored_nodes:!monitoring_servers:!retired_nodes")
        role = yaml.safe_load((ROOT / "roles/monitoring_client/tasks/main.yaml").read_text())
        self.assertIn("monitoring_client_node_exporter_port", role[0]["environment"]["NODEEXPORTER_PORT"])
        self.assertIn("monitoring_client_cadvisor_port", role[0]["environment"]["CADVISOR_PORT"])

    def test_configuration_reload_does_not_force_recreation(self):
        play = yaml.safe_load((STACK / "deploy.yml").read_text())[0]
        compose_tasks = [
            task for task in play["tasks"]
            if "community.docker.docker_compose_v2" in task
        ]
        self.assertEqual(compose_tasks[0]["community.docker.docker_compose_v2"]["recreate"], "auto")
        reload = compose_tasks[1]
        self.assertEqual(reload["community.docker.docker_compose_v2"]["state"], "restarted")
        self.assertIn("loki", reload["community.docker.docker_compose_v2"]["services"])
        self.assertIn("when", reload)

    def test_public_ssh_override_only_changes_the_workstation(self):
        override = yaml.safe_load((ROOT / "monitoring.remote.inventory.yml").read_text())
        self.assertEqual(set(override["all"]["hosts"]), {"local_workstation"})
        for value in override["all"]["hosts"]["local_workstation"].values():
            self.assertIn("hostvars['remote_workstation']", value)

    def test_cleanup_is_opt_in_and_follows_backup(self):
        play = yaml.safe_load((STACK / "deploy.yml").read_text())[0]
        self.assertFalse(play["vars"]["monitoring_replace_ui"])
        includes = [task for task in play["tasks"] if "ansible.builtin.include_tasks" in task]
        self.assertEqual([task["ansible.builtin.include_tasks"] for task in includes], ["backup.yml", "replace-ui.yml"])
        self.assertIn("monitoring_replace_ui | bool", includes[1]["when"])
        self.assertIn("not ansible_check_mode", includes[1]["when"])
        cleanup = yaml.safe_load((STACK / "replace-ui.yml").read_text())
        self.assertIn("monitoring_archive_result.rc == 0", cleanup[0]["ansible.builtin.assert"]["that"])


if __name__ == "__main__":
    unittest.main()
