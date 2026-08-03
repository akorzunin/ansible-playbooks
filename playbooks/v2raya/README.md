# v2raya via SSH

This deploys a loopback-only SSH SOCKS5 tunnel on port `20173`, imports it as
`ssh-nt1`, and selects it as v2rayA's active `proxy` outbound. Existing VLESS
profiles remain saved but are no longer active. v2rayA's HTTP proxy stays on
port `20171`.

Add these values to `external_vars.yml`; encrypt both passwords with Ansible
Vault. `V2RAYA_SSH_HOST` defaults to the `ansible_host` of inventory host
`nt1`, so it is only needed to override that destination.

```yaml
V2RAYA_ADMIN_USERNAME: v2raya_admin
V2RAYA_ADMIN_PASSWORD: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  ...
V2RAYA_SSH_USERNAME: ssh_user
V2RAYA_SSH_PASSWORD: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  ...
V2RAYA_SSH_KNOWN_HOSTS: |
  |1|... ssh-ed25519 AAAA...
# V2RAYA_SSH_HOST: ssh.example.net
# V2RAYA_SSH_PORT: 22
```

Get and independently verify the SSH server's key before saving it:

```sh
ssh-keyscan -H -p 22 ssh.example.net
```

Deploy to the machine running v2rayA:

```sh
ansible-playbook --vault-password-file=.ansible_pass \
  playbooks/v2raya/deploy.yaml -i hosts -l host_name
```

The playbook waits for the tunnel, switches v2rayA to its SOCKS profile, and
checks the resulting HTTP proxy. The SSH password is stored only on the target
in `/srv/deploy/v2raya/ssh-password`, mode `0600`.
