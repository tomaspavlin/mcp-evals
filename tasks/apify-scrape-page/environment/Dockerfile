FROM node:22-bookworm

RUN npm install -g mcp-remote@0.1.38 apify-cli@1.6.2

COPY apify-mcp-proxy.sh /usr/local/bin/apify-mcp-proxy
RUN chmod +x /usr/local/bin/apify-mcp-proxy

WORKDIR /app
