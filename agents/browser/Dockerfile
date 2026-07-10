FROM node:18-slim

# Install Chromium system dependencies + Playwright browsers
RUN npx playwright install chromium --with-deps

WORKDIR /app

COPY agents/browser/package.json .
RUN npm install --production

COPY agents/browser/server.js agents/browser/browser.js agents/browser/scraper.js ./

CMD ["node", "server.js"]
