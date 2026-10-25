FROM scratch
COPY server /usr/local/bin/server
COPY ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
ENTRYPOINT ["/usr/local/bin/server"]
