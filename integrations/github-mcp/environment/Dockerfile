FROM node:22-bookworm

RUN npm install -g mcp-remote@0.1.38

COPY github-mcp-proxy.sh /usr/local/bin/github-mcp-proxy
RUN chmod +x /usr/local/bin/github-mcp-proxy

WORKDIR /app
