const express = require('express');
const { handleAction } = require('./browser');

const app = express();
app.use(express.json({ limit: '10mb' }));

app.get('/health', (_req, res) => {
    res.json({ status: 'ok' });
});

app.post('/', async (req, res) => {
    const input = req.body.input || req.body;
    if (!input || !input.url) {
        return res.status(400).json({ error: 'Missing required field: url' });
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
    }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Browser service listening on port ${PORT}`);
});
