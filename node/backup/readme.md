# How to use backup playbooks

## Create backup

By default, backup will be created for all services.

```bash
ansible-playbook --vault-password-file=.ansible_pass -i hosts ./node/backup/create.playbook.yaml -l nt1 -e bs=service_name
```

## Restore backup

```bash
ansible-playbook --vault-password-file=.ansible_pass -i hosts ./node/backup/restore.playbook.yaml -l nt1 -e bs=service_name
```

## Get content of backup locally

### install rclone on local machine

```bash
ansible-playbook --vault-password-file=.ansible_pass ./playbooks/setup_rclone.playbook.yaml -i localhost, -c local
```

### extract backup

```bash
rclone archive extract backup-remote:/backups/nt1/all/backup_name . -P
```
