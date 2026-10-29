# Cherry VLESS configuration review — 2026-10-29

## Conclusion

**The reported direct-path failure did not reproduce during this review.** All
11 alternative configurations worked from this workstation. These results show
compatibility, not resistance to DPI or a preferred configuration for blocked
users. Keep production settings unchanged until a comparison on a failing path
shows a repeatable improvement.

One actionable finding: **do not rely on the sing-box 1.14.4 TLS fragmentation
flags to change REALITY's ClientHello**; see the fragmentation investigation below.

## Scope and isolation

- Existing server: dyn1, Cherry Amsterdam.
- Production configuration: VLESS/REALITY, raw TCP/8443,
  `xtls-rprx-vision`, target/SNI `www.google.com`, Chrome uTLS fingerprint.
- Client: sing-box 1.14.4, direct Ethernet through `enp12s0`. Wi-Fi was down.
  Proxy environment variables were explicitly bypassed; no active client or TUN
  configuration was changed. Results do not cover a different Wi-Fi/mobile path.
- Server trials: the existing digest-pinned sing-box 1.14.4 image, a temporary
  unprivileged container on TCP/18443, and disposable credentials. All variants
  reused that port so SNI/transport comparisons did not also change the port.
- Each trial's SNI and server-side REALITY handshake target matched. This was not
  a client-only SNI substitution.
- Each configuration was checked locally and in the pinned server image before
  use. Existing VPN containers were not restarted or reconfigured by this review;
  no profiles were published and no client defaults were changed by it.
- Temporary container, server files, SSH forwards and local clients were removed.
  Final inspection found no trial listener or directory; original container IDs
  and uptimes were preserved.

## Transport, SNI and fingerprint matrix

Each direct result is two rounds against two HTTPS destinations: ipify (HTTP 200
and the expected Cherry egress IPv4) and gstatic (HTTP 204). Each SSH reference
is one round against both destinations, using the identical VLESS settings over
strictly host-key-pinned administrator SSH forwarding. A reference success checks
configuration/server functionality; it is not an independent working VPN path.

| Configuration | Direct | SSH reference |
| --- | --- | --- |
| Production TCP/8443, start | 4/4 | 2/2 |
| Trial TCP + Vision, `www.google.com`, Chrome | 4/4 | 2/2 |
| Trial TCP + Vision, `www.microsoft.com`, Chrome | 4/4 | 2/2 |
| Trial TCP + Vision, `www.apple.com`, Chrome | 4/4 | 2/2 |
| Trial TCP + Vision, `www.cloudflare.com`, Chrome | 4/4 | 2/2 |
| Trial TCP, no Vision, Google, Chrome | 4/4 | 2/2 |
| Trial TCP + Vision, Google, Firefox | 4/4 | 2/2 |
| Trial TCP + Vision, Google, Safari | 4/4 | 2/2 |
| Trial gRPC + REALITY | 4/4 | 2/2 |
| Trial HTTP/2 + REALITY | 4/4 | 2/2 |
| Trial WebSocket + REALITY | 4/4 | 2/2 |
| Trial HTTPUpgrade + REALITY | 4/4 | 2/2 |
| Production TCP/8443, end | 4/4 | Not repeated |

HTTP-based trials used Google/Chrome and **no Vision**. gRPC/HTTP used ALPN `h2`;
WebSocket/HTTPUpgrade used `http/1.1`. Paths were `/review`, and gRPC service name
was `review`. They connected directly to Cherry, **not through a CDN**. A working
WebSocket/REALITY trial does not establish ordinary certificate-TLS/CDN support.
QUIC transport and XHTTP were not tested.

Naïve controls passed 2/2 with its configured hostname and 2/2 with the server IP
while retaining its certificate SNI. An earlier attempt hit a DNS SERVFAIL for
DuckDNS; it also encountered an SSH command timeout and was cleaned up before
repeating the full matrix. Neither event establishes DPI blocking.

## Additional production-baseline checks

These used the existing TCP/8443 VLESS configuration, not every trial transport:

- Repeated HTTPS requests: **30/30** across 15 rounds and two destinations.
- Downloads: **3/3**, each exactly 524,288 bytes from Cloudflare's speed endpoint;
  six accompanying ipify/gstatic checks also passed.
- Uploads: **3/3**, each 262,144 bytes of generated zero data, HTTP 200.
- UDP relay over VLESS TCP: **10/10** STUN binding responses, five each from
  Cloudflare and Google, with matching transaction IDs and Cherry's egress IPv4.

These are small functional transfers, not a bandwidth benchmark, long-duration
stability test, or real Discord/voice evaluation. HTTP transports can also reuse
an outer connection, so successful request counts are not independent outer
TLS-handshake counts.

## Fragmentation investigation

Setting `tls.record_fragment: true` or `tls.fragment: true` was accepted and each
passed 6/6 HTTPS checks. **Those successes alone do not demonstrate fragmentation.**

A separate loopback TCP relay inspected the reassembled client-side TLS records
for one successful HTTPS request per setting:

| Setting | TLS records containing the complete ClientHello |
| --- | --- |
| Baseline | One, payload 593 bytes |
| `record_fragment: true` | One, payload 593 bytes |
| `fragment: true` | One, payload 561 bytes |

Thus `record_fragment` did not split the ClientHello into TLS records. Record
inspection does not itself measure TCP packet segmentation. However, the
[1.14.4 REALITY implementation](https://github.com/SagerNet/sing-box/blob/v1.14.4/common/tls/reality_client.go)
constructs `utls.UClient` directly, bypassing the wrapping in
[`UTLSClientConfig.Client`](https://github.com/SagerNet/sing-box/blob/v1.14.4/common/tls/utls_client.go)
that applies both fragmentation flags. This explains why enabling those flags
is not a reliable REALITY workaround in this version.

The [TLS documentation](https://sing-box.sagernet.org/configuration/shared/tls/)
also cautions against treating fragmentation or copied browser fingerprints as
strong censorship resistance. A successful Firefox/Safari test here is not
proof that either evades a particular DPI implementation.

## Next test when the failure is present

1. Capture the failing network/interface, client/core version, timestamps and
   precise failure stage: DNS, TCP connect, REALITY authentication, or transfer.
   Check clock synchronization and credentials before attributing it to filtering.
2. Interleave the original baseline with candidate SNI/transport settings on the
   **same port and network**, and run the identical settings through pinned SSH.
   Direct failure plus reference success narrows the problem to the direct path,
   but still does not identify DPI versus another middlebox or path fault.
3. Compare normal certificate TLS with REALITY if needed. Test TCP/443 only in
   a separately approved experiment: Naïve currently owns it. This review did not
   interrupt Naïve or test VLESS on 443.
4. Run longer transfers and the affected users' actual workloads for at least
   30–60 minutes, then repeat across affected ISPs. Promote only a configuration
   that improves the failing path without breaking required client/UDP support.

## Private evidence

Diagnostic scripts and detailed results remain under `infra/cherry-vpn/private/`
(ignored by Git; do not publish credentials or raw private logs):

- `vless-review.py`, `vless-review-variants.json`, `vless-review-results.json`
- `vless-options-review.py`, `vless-review-udp-upload.json`
- `check-reality-fragmentation.py`, `vless-review-fragment-inspection.json`
- `review-*-direct.log`, `review-*-ssh-reference.log`, `review-*-server.log`
- `vless-review-before.txt`, `vless-review-after.txt`,
  `vless-review-final-cleanup.txt`
- `vless-review-first-attempt/`: results/log from the interrupted initial run.
