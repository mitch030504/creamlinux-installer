# Pinned ARM64 SDK; build context is this directory, never the source checkout.
FROM ubuntu@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3
ENV DEBIAN_FRONTEND=noninteractive TZ=UTC LANG=C.UTF-8
COPY ubuntu.sources /etc/apt/sources.list.d/ubuntu.sources
# The minimal base has no CA bundle. Authenticate this one bootstrap through
# Ubuntu archive signatures; TLS verification stays enabled after CA installation.
RUN apt-get -o Acquire::https::Verify-Peer=false update \
 && apt-get -o Acquire::https::Verify-Peer=false install -y --no-install-recommends ca-certificates=20260601~24.04.1 \
 && apt-get install -y --no-install-recommends python3=3.12.3-0ubuntu2.1
COPY packages.tsv sdk-lock.json provision.py /opt/frame-sdk/
RUN python3 /opt/frame-sdk/provision.py
COPY Dockerfile ubuntu.sources .dockerignore /opt/frame-sdk/
ARG SDK_SOURCE_SHA256
LABEL org.creamlinux.sdk.source=$SDK_SOURCE_SHA256
ENV PATH="/opt/node/bin:/opt/rust/bin:${PATH}"
USER ubuntu
WORKDIR /work
CMD ["sleep", "infinity"]
