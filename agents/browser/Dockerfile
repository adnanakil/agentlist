FROM node:18-slim

# tini as PID 1 reaps the orphaned Chromium processes each launch/close leaves
# behind — without an init they accumulate as zombies until the container hits
# its PID limit and every spawn fails with EAGAIN.
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

# Install Chromium system dependencies + Playwright browsers
RUN npx playwright install chromium --with-deps

WORKDIR /app

COPY agents/browser/package.json .
RUN npm install --production

COPY agents/browser/server.js agents/browser/browser.js agents/browser/scraper.js ./

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["node", "server.js"]
