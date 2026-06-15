FROM node:22-bookworm

# `&& command -v mcpc` asserts the bin lands on PATH so a broken build fails loudly
# instead of the agent silently falling back to curl (see docs/todo.md template-collision).
RUN npm install -g @apify/mcpc@0.3.0 && command -v mcpc

WORKDIR /app
