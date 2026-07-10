const dns = require('dns').promises;
const net = require('net');

const DEFAULT_TIMEOUT_MS = 30000;
const DEFAULT_MAX_CONTENT_BYTES = 2_000_000;
const DEFAULT_MAX_OUTPUT_CHARS = 200_000;
const MAX_REDIRECTS = 5;

const BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'Upgrade-Insecure-Requests': '1',
};

const CHALLENGE_PATTERNS = [
    /cf-browser-verification/i,
    /cf-chl-/i,
    /cloudflare ray id/i,
    /attention required!.*cloudflare/is,
    /just a moment\.\.\./i,
    /verify (?:you are|that you are) human/i,
    /captcha/i,
    /datadome/i,
    /perimeterx/i,
    /px-captcha/i,
    /akamai.*(?:challenge|bot manager)/is,
    /access denied.*(?:bot|automated|request)/is,
];

function decodeHtmlEntities(value) {
    if (!value) return '';
    const named = {
        amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", '#39': "'",
        nbsp: ' ', ndash: '–', mdash: '—', hellip: '…', laquo: '«', raquo: '»',
    };
    return value.replace(/&(#x[0-9a-f]+|#\d+|[a-z][a-z0-9]+);/gi, (match, entity) => {
        const lower = entity.toLowerCase();
        if (lower.startsWith('#x')) {
            const codepoint = parseInt(lower.slice(2), 16);
            return Number.isFinite(codepoint) ? String.fromCodePoint(codepoint) : match;
        }
        if (lower.startsWith('#')) {
            const codepoint = parseInt(lower.slice(1), 10);
            return Number.isFinite(codepoint) ? String.fromCodePoint(codepoint) : match;
        }
        return Object.prototype.hasOwnProperty.call(named, lower) ? named[lower] : match;
    });
}

function htmlToMarkdown(html, maxChars = DEFAULT_MAX_OUTPUT_CHARS) {
    if (!html) return '';
    let text = html
        .replace(/<!--[\s\S]*?-->/g, '')
        .replace(/<(script|style|noscript|template|svg)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, '')
        .replace(/<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>([\s\S]*?)<\/a\s*>/gi,
            (_match, href, label) => `${label.replace(/<[^>]+>/g, ' ').trim()} (${href})`)
        .replace(/<h([1-6])\b[^>]*>/gi, (_match, level) => `\n${'#'.repeat(Number(level))} `)
        .replace(/<\/h[1-6]\s*>/gi, '\n')
        .replace(/<li\b[^>]*>/gi, '\n- ')
        .replace(/<(br|hr)\b[^>]*\/?>/gi, '\n')
        .replace(/<\/(p|div|section|article|main|header|footer|nav|aside|ul|ol|li|table|tr|blockquote)\s*>/gi, '\n')
        .replace(/<(p|div|section|article|main|header|footer|nav|aside|ul|ol|table|tr|blockquote)\b[^>]*>/gi, '\n')
        .replace(/<[^>]+>/g, ' ');

    text = decodeHtmlEntities(text)
        .replace(/\r/g, '')
        .replace(/[\t ]+/g, ' ')
        .replace(/ *\n */g, '\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim();

    return text.length > maxChars ? `${text.slice(0, maxChars)}\n...(truncated)` : text;
}

function extractTitle(html) {
    const match = String(html || '').match(/<title\b[^>]*>([\s\S]*?)<\/title\s*>/i);
    return match ? decodeHtmlEntities(match[1].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()) : '';
}

function extractLinks(html, baseUrl, limit = 500) {
    const links = [];
    const seen = new Set();
    const pattern = /<a\b[^>]*href\s*=\s*(?:["']([^"']+)["']|([^\s>]+))[^>]*>/gi;
    let match;
    while ((match = pattern.exec(String(html || ''))) && links.length < limit) {
        const href = decodeHtmlEntities(match[1] || match[2] || '').trim();
        if (!href || /^(?:javascript:|mailto:|tel:|#)/i.test(href)) continue;
        try {
            const absolute = new URL(href, baseUrl).toString();
            if (!seen.has(absolute)) {
                seen.add(absolute);
                links.push(absolute);
            }
        } catch (_error) {}
    }
    return links;
}

function isChallenge(content, status = 200) {
    if ([401, 403, 407, 429, 503].includes(status)) return true;
    const sample = String(content || '').slice(0, 100_000);
    return CHALLENGE_PATTERNS.some(pattern => pattern.test(sample));
}

function isJunkContent(content, contentType = 'text/html') {
    const value = String(content || '').trim();
    if (!value) return true;
    if (!contentType.toLowerCase().includes('html')) return value.length < 40;

    const text = htmlToMarkdown(value, 10_000);
    if (text.length >= 400) return false;

    // A tiny visible body plus a large JS bundle is usually an SPA shell that
    // needs rendering, not a genuinely short document.
    return /<script\b/i.test(value) || /__next|webpack|react|hydrate|application\/ld\+json/i.test(value);
}

function isPrivateIp(address) {
    if (!address) return true;
    const normalized = address.toLowerCase().split('%')[0];
    if (normalized === '::1' || normalized === '::' || normalized === '0:0:0:0:0:0:0:1') return true;
    if (normalized.startsWith('::ffff:')) return isPrivateIp(normalized.slice(7));

    if (net.isIPv4(normalized)) {
        const [a, b] = normalized.split('.').map(Number);
        return a === 0 || a === 10 || a === 127 ||
            (a === 100 && b >= 64 && b <= 127) ||
            (a === 169 && b === 254) ||
            (a === 172 && b >= 16 && b <= 31) ||
            (a === 192 && b === 168) ||
            (a === 198 && (b === 18 || b === 19)) ||
            a >= 224;
    }

    if (net.isIPv6(normalized)) {
        return normalized.startsWith('fc') || normalized.startsWith('fd') ||
            normalized.startsWith('fe8') || normalized.startsWith('fe9') ||
            normalized.startsWith('fea') || normalized.startsWith('feb');
    }
    return true;
}

async function assertPublicUrl(rawUrl, lookup = dns.lookup) {
    let parsed;
    try {
        parsed = new URL(rawUrl);
    } catch (_error) {
        throw new Error('url must be a valid absolute HTTP(S) URL');
    }
    if (!['http:', 'https:'].includes(parsed.protocol)) {
        throw new Error('url must use http or https');
    }
    if (parsed.username || parsed.password) throw new Error('url credentials are not allowed');
    if (parsed.hostname === 'localhost' || parsed.hostname.endsWith('.localhost') || parsed.hostname.endsWith('.internal')) {
        throw new Error('url resolves to a private or internal host');
    }

    const literalFamily = net.isIP(parsed.hostname);
    const addresses = literalFamily
        ? [{ address: parsed.hostname, family: literalFamily }]
        : await lookup(parsed.hostname, { all: true, verbatim: true });
    if (!addresses.length || addresses.some(record => isPrivateIp(record.address))) {
        throw new Error('url resolves to a private or internal address');
    }
    return parsed;
}

async function readResponseBody(response, maxBytes) {
    const advertised = Number(response.headers.get('content-length') || 0);
    if (advertised > maxBytes) throw new Error(`response exceeds ${maxBytes} bytes`);

    if (!response.body || typeof response.body.getReader !== 'function') {
        const text = await response.text();
        if (Buffer.byteLength(text) > maxBytes) throw new Error(`response exceeds ${maxBytes} bytes`);
        return text;
    }

    const reader = response.body.getReader();
    const chunks = [];
    let size = 0;
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > maxBytes) {
            await reader.cancel().catch(() => {});
            throw new Error(`response exceeds ${maxBytes} bytes`);
        }
        chunks.push(Buffer.from(value));
    }
    return Buffer.concat(chunks).toString('utf8');
}

async function fetchWithSafeRedirects(url, options) {
    const {
        fetchImpl, headers, timeoutMs, maxBytes, lookup = dns.lookup,
    } = options;
    let current = url;

    for (let hop = 0; hop <= MAX_REDIRECTS; hop++) {
        await assertPublicUrl(current, lookup);
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const response = await fetchImpl(current, {
                headers,
                redirect: 'manual',
                signal: controller.signal,
            });
            if ([301, 302, 303, 307, 308].includes(response.status)) {
                const location = response.headers.get('location');
                if (!location) throw new Error(`redirect ${response.status} had no location`);
                current = new URL(location, current).toString();
                continue;
            }

            const body = await readResponseBody(response, maxBytes);
            return { response, body, finalUrl: current };
        } finally {
            clearTimeout(timer);
        }
    }
    throw new Error(`too many redirects (>${MAX_REDIRECTS})`);
}

function createScraper({ fetchImpl = global.fetch, render, lookup = dns.lookup } = {}) {
    if (typeof fetchImpl !== 'function') throw new Error('fetch implementation is required');
    if (typeof render !== 'function') throw new Error('render implementation is required');

    return async function scrape(input) {
        const url = input.url;
        const renderJs = input.render_js !== false && input.renderJs !== false;
        const format = input.format === 'html' ? 'html' : 'markdown';
        const timeoutMs = Math.min(Math.max(Number(input.timeout_ms) || DEFAULT_TIMEOUT_MS, 1000), 90000);
        const maxBytes = Math.min(Math.max(Number(input.max_content_bytes) || DEFAULT_MAX_CONTENT_BYTES, 1000), 10_000_000);
        const headers = { ...BROWSER_HEADERS, ...(input.headers || {}) };
        const startedAt = Date.now();
        let plainFailure = null;

        try {
            const { response, body, finalUrl } = await fetchWithSafeRedirects(url, {
                fetchImpl, headers, timeoutMs, maxBytes, lookup,
            });
            const contentType = response.headers.get('content-type') || 'text/html';
            const challenged = isChallenge(body, response.status);
            const junk = isJunkContent(body, contentType);

            if (response.ok && !challenged && !junk) {
                const content = format === 'html' || !contentType.includes('html')
                    ? body.slice(0, DEFAULT_MAX_OUTPUT_CHARS)
                    : htmlToMarkdown(body);
                return {
                    content,
                    title: contentType.includes('html') ? extractTitle(body) : '',
                    links: contentType.includes('html') ? extractLinks(body, finalUrl) : [],
                    url: finalUrl,
                    status_code: response.status,
                    content_type: contentType,
                    strategy: 'http',
                    duration_ms: Date.now() - startedAt,
                };
            }
            plainFailure = `HTTP ${response.status}${challenged ? ' challenge page' : junk ? ' junk/JS shell' : ''}`;
        } catch (error) {
            plainFailure = error.name === 'AbortError' ? `HTTP timeout after ${timeoutMs}ms` : error.message;
        }

        if (!renderJs) throw new Error(plainFailure || 'plain HTTP fetch failed');

        await assertPublicUrl(url, lookup);
        const rendered = await render({
            url,
            action: 'scrape',
            format,
            timeout_ms: timeoutMs,
            max_output_chars: DEFAULT_MAX_OUTPUT_CHARS,
        });
        if (!rendered || rendered.error || !rendered.content) {
            throw new Error(rendered?.error || `${plainFailure}; browser render returned no content`);
        }
        if (isChallenge(rendered.content, rendered.status_code || 200)) {
            throw new Error(`${plainFailure}; browser render was blocked by a challenge page`);
        }

        return {
            ...rendered,
            strategy: 'browser',
            fallback_reason: plainFailure,
            duration_ms: Date.now() - startedAt,
        };
    };
}

module.exports = {
    BROWSER_HEADERS,
    assertPublicUrl,
    createScraper,
    decodeHtmlEntities,
    extractTitle,
    extractLinks,
    htmlToMarkdown,
    isChallenge,
    isJunkContent,
    isPrivateIp,
};
