# Single base image used by every task. Installs every connector tool we
# evaluate (apify CLI, gh CLI, mcp-remote, @apify/mcpc) plus stdio proxies for
# the remote MCPs. Channel selection happens at runtime (which mcp_servers /
# instructions / setup scripts the agent gets) - the image is fixed, so its
# dirhash is stable and the sandbox template cache stays hot across runs.

FROM node:22-bookworm

# gh CLI
ARG GH_VERSION=2.78.0
RUN ARCH=$(dpkg --print-architecture) \
 && curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${ARCH}.deb" -o /tmp/gh.deb \
 && apt-get update && apt-get install -y --no-install-recommends /tmp/gh.deb \
 && rm /tmp/gh.deb && rm -rf /var/lib/apt/lists/*

# Node-based CLIs. `command -v` asserts each bin lands on PATH so a broken
# build fails loudly instead of the agent silently falling back to curl.
RUN npm install -g apify-cli@1.6.2 mcp-remote@0.1.38 @apify/mcpc@0.3.0 \
 && command -v apify && command -v mcp-remote && command -v mcpc

# Stdio shims for remote MCPs (harbor's MCPServerConfig has no `headers` field).
COPY apify-mcp-proxy.sh /usr/local/bin/apify-mcp-proxy
COPY github-mcp-proxy.sh /usr/local/bin/github-mcp-proxy
RUN chmod +x /usr/local/bin/apify-mcp-proxy /usr/local/bin/github-mcp-proxy

WORKDIR /app
