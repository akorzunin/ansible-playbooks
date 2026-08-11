# v2rayA as a VLESS proxy

This deploys v2rayA with a VLESS node from `V2RAYA_NODE_URL`, enables proxy
sharing on the `v2raya-proxy` Docker network, and starts that node. The API is
available on `127.0.0.1:2017`; the HTTP proxy is available on port `20171`.

Add these values to `external_vars.yml`; encrypt the passwords with Ansible
Vault:

```yaml
V2RAYA_ADMIN_USERNAME: v2raya_admin
V2RAYA_ADMIN_PASSWORD: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  ...
V2RAYA_NODE_URL: "vless://uuid@example.com:443?type=tcp&security=reality&pbk=public-key&sni=example.com&fp=chrome&sid=short-id#node"
```

Deploy to the machine running v2rayA:

```sh
ansible-playbook --vault-password-file=.ansible_pass \
  playbooks/v2raya/deploy.yaml -i hosts -l host_name
```

The playbook creates the `v2raya-proxy` Docker network, bootstraps the admin
account, imports or updates the VLESS node, and starts the proxy.
