# Hermes Agent

Add these **Ansible Vault-encrypted** values to `external_vars.yml`:

```yaml
HERMES_OPENROUTER_API_KEY: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  ...
HERMES_TELEGRAM_BOT_TOKEN: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  ...
HERMES_TELEGRAM_ALLOWED_USERS: "123456789"
```

Get the Telegram token from `@BotFather` and your numeric user ID from
`@userinfobot`. Never use `GATEWAY_ALLOW_ALL_USERS`.

Encrypt a value with:

```sh
ansible-vault encrypt_string --vault-password-file .ansible_pass 'value' --name HERMES_OPENROUTER_API_KEY
```

Deploy to a chosen host:

```sh
ansible-playbook --vault-password-file=.ansible_pass \
  playbooks/hermes-agent/deploy.yaml -i hosts -l host_name
```

The encrypted variables are written only to `/srv/deploy/hermes-agent/data/.env`
on the target, mode `0600`; Compose has no API keys. Re-running the playbook
updates `data/config.yaml` and recreates Hermes, including model changes.
