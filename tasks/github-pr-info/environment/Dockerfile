FROM node:22-bookworm

ARG GH_VERSION=2.78.0
RUN ARCH=$(dpkg --print-architecture) \
 && curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${ARCH}.deb" -o /tmp/gh.deb \
 && apt-get update && apt-get install -y --no-install-recommends /tmp/gh.deb \
 && rm /tmp/gh.deb && rm -rf /var/lib/apt/lists/*

WORKDIR /app
