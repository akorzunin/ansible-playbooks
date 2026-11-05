# Same maintained core as the workstation proxy, including Naïve and QUIC.
FROM ghcr.io/sagernet/sing-box@sha256:0788ffbddab2c68a99a2dd4780bbc50902f159af6f589df3ee74a8389d278279
WORKDIR /app
COPY bin/vpn-monitor /usr/local/bin/vpn-monitor
COPY web/dist/ web/dist/
ENTRYPOINT ["/usr/local/bin/vpn-monitor"]
CMD ["--config", "config.yaml"]
