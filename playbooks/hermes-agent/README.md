# Hermes Agent

Add these **Ansible Vault-encrypted** values to `external_vars.yml`:

```yaml
HERMES_OMNIROUTE_API_KEY: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  ...
HERMES_FIRECRAWL_API_KEY: !vault |
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
ansible-vault encrypt_string --vault-password-file .ansible_pass 'value' --name HERMES_OMNIROUTE_API_KEY
ansible-vault encrypt_string --vault-password-file .ansible_pass 'value' --name HERMES_FIRECRAWL_API_KEY
```

## Use through OmniRoute

OmniRoute is configured to send outbound traffic through the host v2rayA HTTP
proxy at `host.docker.internal:20171`.

Deploy/redeploy OmniRoute so the proxy settings are applied:

   ```sh
   ansible-playbook --vault-password-file=.ansible_pass \
     playbooks/omniroute/deploy.yaml -i hosts -l remote_workstation
   ```

Deploy to a chosen host:

```sh
ansible-playbook --vault-password-file=.ansible_pass \
  playbooks/hermes-agent/deploy.yaml -i hosts -l host_name
```

The OmniRoute and Firecrawl keys are written only to
`/srv/deploy/hermes-agent/data/.env` on the target, mode `0600`; existing
Telegram configuration is retained. STT runs in the `hermes-stt` GPU container
using faster-whisper/CTranslate2 and the multilingual `large-v3` model. The
model is cached in the `whisper-models` Docker volume. Re-running the playbook
updates `data/config.yaml` and recreates both services.
