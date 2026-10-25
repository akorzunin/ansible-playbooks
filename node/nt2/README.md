# nt2 disposable connectivity test

Target DNS: `akorz-nt2.duckdns.org`.
Tested 2026-10-22, administered through nt1 using its existing root SSH key.
This is a temporary experiment, **not** the production bootstrap. No SSH policy,
Docker, monitoring, or system-routing changes were made. UFW was already inactive.

## Running services

| Endpoint | Purpose | Service |
| --- | --- | --- |
| TCP 80 | HTTP redirect / ACME validation | `nt2-poc-naive` |
| TCP 443 | HTTPS test page and authenticated NaiveProxy | `nt2-poc-naive` |
| TCP 8443 | VLESS/REALITY, Vision, SNI `google.com` | `nt2-poc-vless` |
| UDP 443 | Hysteria2 with authenticated access and normal TLS verification | `nt2-poc-hysteria2` |

The HTTPS certificate is a real Let's Encrypt certificate for the **apex hostname**,
not a wildcard certificate. Caddy obtained it using HTTP-01 validation.

All three services run as the unprivileged `nt2poc` user, with binaries/configs in
`/opt/nt2-poc` and certificates/state in `/var/lib/nt2-poc`. Combined service memory
was approximately 25 MiB at the final check. No public management panel was installed.

Versions: Caddy forwardproxy `v2.11.2-naive`, Xray `25.10.15` (copied read-only from
nt1's existing image), sing-box `1.14.3` for the Hysteria2 server. The initially
tried Xray `26.10.21` did not interoperate with the installed sing-box client's
REALITY verification; the working PoC uses the same Xray version as nt1. This is
not a recommendation to use that older version for a new production deployment.
Xray's freedom outbound is configured to use IPv4.

## Observed results

| Test | Direct from controller | From/via nt1 |
| --- | --- | --- |
| HTTPS website | Timeout | HTTP 200, valid TLS |
| Naive, TCP 443 | Timeout | Successful proxied requests |
| VLESS/REALITY, TCP 8443 | Timeout | Successful proxied requests |
| VLESS/REALITY, temporarily on TCP 443 | Timeout | 4/4 successful proxied requests |
| Hysteria2, UDP 443 | Timeout | 4/4 successful proxied requests |

Successful proxy checks fetched `api.ipify.org` and Google's `generate_204`;
returned egress IP matched **nt2**, not nt1. Naive/VLESS reference tests
used isolated local sing-box clients through SSH port-forwards on nt1. Hysteria2
was tested with an isolated client running directly on nt1; SSH does not forward
UDP. Temporary client artifacts on nt1 were removed afterward.

The final direct test used a 15-second connection timeout and failed for both
URLs on all three protocols. The workstation's direct HTTPS test also timed out.
VLESS was restored to TCP 8443 after its TCP 443 comparison, and Naive/HTTPS was
restored to TCP 443. All three services were active at the final check.

These results are consistent with routing/filtering affecting the tested local
network paths. They do not establish which provider is responsible, or whether
other networks can access the server. Ping alone is not evidence that these
application protocols work. Try mobile data or another ISP before committing to
this server for direct VPN/site access.

## Private client files

On the controller, mode `0600`:

- `~/.local/share/nt2-naive.json`
- `~/.local/share/nt2-vless.json`
- `~/.local/share/nt2-hysteria2.json`
- `~/.local/share/nt2-links.txt` — import URIs; **contains credentials**.

JSON files contain sing-box outbound fragments, matching the existing nt1 profile
format. They do not change the active VPN configuration. Naive requires a client
build supporting Naive outbound. Do not publish these files or paste them into logs.
Private deployment artifacts, standalone loopback-only probe configurations, and
results are retained in the gitignored `.ansible/nt2-poc/` directory.

No nt2 entry was added to production inventories or public profile subscriptions.
Credentials are separate from nt1 and will need replacing after reinstalling.
Hysteria2 currently reads Caddy's certificate files at startup; this disposable
setup does not wire certificate-renewal reloads into that service.

## Stop the experiment

From a root shell on nt2:

```sh
systemctl disable --now nt2-poc-naive nt2-poc-vless nt2-poc-hysteria2
```

This closes the PoC listeners without deleting state. The planned OS reinstall
can remove the experiment entirely; no production nt1 service was reconfigured.
