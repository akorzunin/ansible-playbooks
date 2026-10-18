FROM scratch
COPY ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY caddy /usr/local/bin/caddy-naive
ENTRYPOINT ["/usr/local/bin/caddy-naive"]
CMD ["run", "--config", "/etc/naiveproxy/Caddyfile", "--adapter", "caddyfile"]
