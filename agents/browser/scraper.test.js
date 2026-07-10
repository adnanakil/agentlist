const test = require('node:test');
const assert = require('node:assert/strict');

const {
    assertPublicUrl,
    createScraper,
    extractLinks,
    htmlToMarkdown,
    isChallenge,
    isPrivateIp,
} = require('./scraper');

const publicLookup = async () => [{ address: '93.184.216.34', family: 4 }];

function htmlPage(body = 'Useful event details '.repeat(30)) {
    return `<!doctype html><html><head><title>Calendar &amp; Events</title></head><body><main><h1>Events</h1><p>${body}</p><a href="/tickets">Tickets</a></main></body></html>`;
}

test('htmlToMarkdown preserves useful structure and removes executable content', () => {
    const output = htmlToMarkdown('<h1>Hello &amp; goodbye</h1><script>bad()</script><ul><li>One</li></ul>');
    assert.match(output, /# Hello & goodbye/);
    assert.match(output, /- One/);
    assert.doesNotMatch(output, /bad/);
});

test('extractLinks resolves relative URLs and removes unsafe or duplicate links', () => {
    const links = extractLinks(
        '<a href="/events/1">One</a><a href="https://example.com/events/1">Again</a>' +
        '<a href="javascript:alert(1)">Bad</a>',
        'https://example.com/calendar',
    );
    assert.deepEqual(links, ['https://example.com/events/1']);
});

test('private and special-use IP ranges are blocked', async () => {
    assert.equal(isPrivateIp('127.0.0.1'), true);
    assert.equal(isPrivateIp('169.254.169.254'), true);
    assert.equal(isPrivateIp('10.2.3.4'), true);
    assert.equal(isPrivateIp('93.184.216.34'), false);
    await assert.rejects(
        assertPublicUrl('http://metadata.example/', async () => [{ address: '169.254.169.254', family: 4 }]),
        /private or internal/,
    );
});

test('a useful static page stays on the zero-browser HTTP tier', async () => {
    let renderCalls = 0;
    const scrape = createScraper({
        lookup: publicLookup,
        fetchImpl: async () => new Response(htmlPage(), {
            status: 200,
            headers: { 'content-type': 'text/html; charset=utf-8' },
        }),
        render: async () => {
            renderCalls += 1;
            return { content: 'should not render' };
        },
    });

    const result = await scrape({ url: 'https://example.com/events', render_js: true });
    assert.equal(result.strategy, 'http');
    assert.equal(result.title, 'Calendar & Events');
    assert.match(result.content, /Tickets/);
    assert.deepEqual(result.links, ['https://example.com/tickets']);
    assert.equal(renderCalls, 0);
});

test('a JS shell escalates to the Chromium tier', async () => {
    const scrape = createScraper({
        lookup: publicLookup,
        fetchImpl: async () => new Response('<html><body><div id="app"></div><script src="app.js"></script></body></html>', {
            status: 200,
            headers: { 'content-type': 'text/html' },
        }),
        render: async () => ({
            url: 'https://example.com/events',
            title: 'Rendered',
            content: 'Rendered event information '.repeat(30),
            status_code: 200,
            content_type: 'text/markdown',
        }),
    });

    const result = await scrape({ url: 'https://example.com/events', render_js: true });
    assert.equal(result.strategy, 'browser');
    assert.match(result.fallback_reason, /junk\/JS shell/);
    assert.match(result.content, /Rendered event/);
});

test('challenge responses escalate, but render_js=false fails closed', async () => {
    const fetchImpl = async () => new Response('<html><title>Just a moment...</title><body>cf-chl-bypass</body></html>', {
        status: 403,
        headers: { 'content-type': 'text/html' },
    });
    assert.equal(isChallenge('Just a moment... cf-chl-bypass', 403), true);

    const render = async () => ({
        content: 'Real calendar content '.repeat(30),
        status_code: 200,
        content_type: 'text/markdown',
    });
    const scrape = createScraper({ lookup: publicLookup, fetchImpl, render });
    const rendered = await scrape({ url: 'https://example.com', render_js: true });
    assert.equal(rendered.strategy, 'browser');
    assert.match(rendered.fallback_reason, /challenge page/);
    await assert.rejects(
        scrape({ url: 'https://example.com', render_js: false }),
        /challenge page/,
    );
});

test('redirects are revalidated before following them', async () => {
    let fetchCalls = 0;
    const scrape = createScraper({
        lookup: async host => host === 'safe.example'
            ? [{ address: '93.184.216.34', family: 4 }]
            : [{ address: '127.0.0.1', family: 4 }],
        fetchImpl: async () => {
            fetchCalls += 1;
            return new Response('', { status: 302, headers: { location: 'http://internal.example/secret' } });
        },
        render: async () => ({ content: 'never' }),
    });

    await assert.rejects(
        scrape({ url: 'https://safe.example', render_js: false }),
        /private or internal/,
    );
    assert.equal(fetchCalls, 1);
});
