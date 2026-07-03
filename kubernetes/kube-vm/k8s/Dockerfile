FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    software-properties-common \
    gnupg \
    curl \
    && add-apt-repository ppa:open5gs/latest \
    && apt-get update \
    && apt-get install -y \
      open5gs-upf=2.7.6~jammy \
      iproute2 \
      iptables \
      iputils-ping \
      net-tools \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
