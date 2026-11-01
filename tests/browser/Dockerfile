FROM node:24-bookworm-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c
WORKDIR /opt/forge-browser
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/forge-browsers
RUN node node_modules/playwright/cli.js install --with-deps chromium \
    && chmod -R a-w /opt/forge-browser/node_modules /opt/forge-browsers \
    && rm -rf /var/lib/apt/lists/*
USER node
