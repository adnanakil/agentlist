const express = require('express');
const { handleAction } = require('./browser');
const { assertPublicUrl, createScraper } = require('./scraper');

const app = express();
app.use(express.json({ limit: '10mb' }));

app.get('/health', (_req, res) => {
    res.json({ status: 'ok', scraper: 'http-with-browser-fallback' });
});

const scrape = createScraper({ render: handleAction });

function parseBoolean(value, defaultValue = true) {
    if (value === undefined || value === null || value === '') return defaultValue;
    return !['0', 'false', 'no', 'off'].includes(String(value).toLowerCase());
}

// spawn EAGAIN means the container can no longer fork (PID exhaustion from
// leaked Chromium processes). Nothing will succeed again until a restart, so
// answer the in-flight request and exit — Railway brings up a fresh container.
function exitIfCannotFork(error) {
    if (/EAGAIN/.test(error?.message || '')) {
        console.error('Browser spawn hit EAGAIN — exiting so Railway restarts the container');
        setTimeout(() => process.exit(1), 250);
    }
}

function authorized(req) {
    const expected = process.env.SCRAPER_API_KEY;
    if (!expected) return true;
    const bearer = (req.get('authorization') || '').replace(/^Bearer\s+/i, '');
    return bearer === expected || req.get('x-api-key') === expected || req.query.key === expected;
}

async function scrapeHandler(req, res) {
    if (!authorized(req)) return res.status(401).json({ error: 'Unauthorized' });
    const source = req.method === 'GET' ? req.query : (req.body.input || req.body || {});
    if (!source.url) return res.status(400).json({ error: 'Missing required field: url' });

    try {
        const result = await scrape({
            ...source,
            render_js: parseBoolean(source.render_js ?? source.renderJs, true),
            format: source.format === 'html' ? 'html' : 'markdown',
        });
        res.json({
            result,
            context: {
                cost: { credits: 0 },
                scrape_method: result.strategy,
                duration_ms: result.duration_ms,
            },
        });
    } catch (error) {
        const status = /private|internal|valid absolute|credentials|http or https/i.test(error.message) ? 400 : 502;
        res.status(status).json({ error: error.message });
        exitIfCannotFork(error);
    }
}

// GET is intentionally Scrapfly-shaped for a low-friction migration. New
// callers should prefer POST so credentials and long URLs stay out of logs.
app.get('/scrape', scrapeHandler);
app.post('/scrape', scrapeHandler);

app.post('/', async (req, res) => {
    if (!authorized(req)) return res.status(401).json({ error: 'Unauthorized' });
    const input = req.body.input || req.body;
    if (!input || !input.url) {
        return res.status(400).json({ error: 'Missing required field: url' });
    }

    try {
        await assertPublicUrl(input.url);
    } catch (error) {
        return res.status(400).json({ error: error.message });
    }

    // Per-request timeout (90s default)
    const timeout = setTimeout(() => {
        if (!res.headersSent) {
            res.status(504).json({ error: 'Browser action timed out after 90s' });
        }
    }, 90000);

    try {
        const output = await handleAction(input);
        clearTimeout(timeout);
        if (!res.headersSent) {
            res.json({ output });
        }
    } catch (err) {
        clearTimeout(timeout);
        console.error('Browser error:', err.message);
        if (!res.headersSent) {
            res.status(500).json({ error: err.message });
        }
        exitIfCannotFork(err);
    }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Browser service listening on port ${PORT}`);
});
