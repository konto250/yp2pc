FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends tinyproxy openssh-client ca-certificates netcat-openbsd \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 proxyuser \
    && useradd --uid 1000 --gid 1000 --no-create-home proxyuser
COPY tinyproxy.conf allowed-domains /etc/yp2pc/
COPY tunnel.sh /usr/local/bin/yp2pc-tunnel
RUN chmod 755 /usr/local/bin/yp2pc-tunnel
USER 1000:1000
CMD ["tinyproxy", "-d", "-c", "/etc/yp2pc/tinyproxy.conf"]
