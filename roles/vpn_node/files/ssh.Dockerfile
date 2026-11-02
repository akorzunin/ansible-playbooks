FROM debian:13-slim

RUN apt-get update && apt-get install -y --no-install-recommends openssh-server ca-certificates \
    && rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_* \
    && mkdir -p /run/sshd
ARG VPN_UID
ARG VPN_GID
RUN groupadd -g "$VPN_GID" vpnprobe \
    && useradd -u "$VPN_UID" -g vpnprobe -M -d /tmp -s /usr/sbin/nologin -p '*' vpnprobe
USER vpnprobe
ENTRYPOINT ["/usr/sbin/sshd", "-D", "-e", "-f", "/etc/vpn/sshd_config"]
