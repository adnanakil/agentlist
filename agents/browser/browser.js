/**
 * Browser Agent — Playwright-based web content extraction
 *
 * Stateless: each invocation launches headless Chromium, performs actions,
 * returns result, closes browser. Refactored from HAL's browser-agent.js.
 */

const { chromium } = require('playwright');

// ─── HTML Entity Decoding ────────────────────────────────────────────────── //

function decodeHTMLEntities(text) {
    return text
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
        .replace(/&#(\d+);/g, (_, dec) => String.fromCharCode(parseInt(dec)));
}

// ─── YouTube Helpers ─────────────────────────────────────────────────────── //

function extractVideoId(url) {
    const match = url.match(/[?&]v=([^&]+)/) || url.match(/youtu\.be\/([^?&]+)/);
    return match ? match[1] : null;
}

function parseJson3Transcript(json) {
    if (!json.events) return '';
    return json.events
        .filter(e => e.segs)
        .map(e => {
            const time = Math.floor((e.tStartMs || 0) / 1000);
            const mins = Math.floor(time / 60);
            const secs = time % 60;
            const timestamp = `[${mins}:${secs.toString().padStart(2, '0')}]`;
            const text = e.segs.map(s => s.utf8).join('').trim();
            return text ? `${timestamp} ${text}` : '';
        })
        .filter(Boolean)
        .join('\n');
}

function parseXmlTranscript(xml) {
    const textMatches = xml.match(/<text[^>]*>([\s\S]*?)<\/text>/g);
    if (!textMatches) return '';
    return textMatches.map(m => {
        const startMatch = m.match(/start="([\d.]+)"/);
        const time = startMatch ? Math.floor(parseFloat(startMatch[1])) : 0;
        const mins = Math.floor(time / 60);
        const secs = time % 60;
        const timestamp = `[${mins}:${secs.toString().padStart(2, '0')}]`;
        const content = m.replace(/<[^>]+>/g, '').trim();
        const decoded = decodeHTMLEntities(content);
        return decoded ? `${timestamp} ${decoded}` : '';
    }).filter(Boolean).join('\n');
}

function parseWebVTT(vtt) {
    const lines = vtt.split('\n');
    const cues = [];
    let i = 0;
    while (i < lines.length) {
        if (lines[i].includes('-->')) {
            const timeMatch = lines[i].match(/(\d{2}):(\d{2}):(\d{2})/);
            if (timeMatch) {
                const mins = parseInt(timeMatch[1]) * 60 + parseInt(timeMatch[2]);
                const secs = parseInt(timeMatch[3]);
                const timestamp = `[${mins}:${secs.toString().padStart(2, '0')}]`;
                const textLines = [];
                i++;
                while (i < lines.length && lines[i].trim() !== '') {
                    textLines.push(lines[i].trim());
                    i++;
                }
                const text = textLines.join(' ');
                if (text) cues.push(`${timestamp} ${text}`);
            }
        }
        i++;
    }
    return cues.join('\n');
}

function parseCaptionBody(body) {
    if (!body || body.length < 200) return '';
    try {
        const json = JSON.parse(body);
        return parseJson3Transcript(json);
    } catch (e) {
        return parseXmlTranscript(body);
    }
}

// ─── Browser Launch ──────────────────────────────────────────────────────── //

async function launchBrowser() {
    const browser = await chromium.launch({
        headless: true,
        args: [
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-extensions',
        ],
    });

    const context = await browser.newContext({
        viewport: { width: 1280, height: 900 },
        userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        locale: 'en-US',
        timezoneId: 'America/New_York',
    });

    // Set YouTube consent cookie to skip GDPR consent screen
    await context.addCookies([
        {
            name: 'SOCS',
            value: 'CAESEwgDEgk2MjcxMjEyMTQaAmVuIAEaBgiA_LyaBg',
            domain: '.youtube.com',
            path: '/',
        },
        {
            name: 'CONSENT',
            value: 'PENDING+987',
            domain: '.google.com',
            path: '/',
        },
    ]);

    // Stealth patches
    await context.addInitScript(() => {
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {} };
        if (navigator.permissions) {
            const origPermQuery = navigator.permissions.query;
            navigator.permissions.query = (params) =>
                params.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : origPermQuery.call(navigator.permissions, params);
        }
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });
    });

    const page = await context.newPage();
    return { browser, context, page };
}

// ─── YouTube Extraction ──────────────────────────────────────────────────── //

async function extractYouTube(page, url) {
    let interceptedCaptions = null;

    // Set up network intercept BEFORE navigation
    page.on('response', async (response) => {
        try {
            const respUrl = response.url();
            if (respUrl.includes('/api/timedtext') && response.status() === 200) {
                const body = await response.text();
                if (body && body.length > 200) {
                    if (!interceptedCaptions || body.length > interceptedCaptions.body.length) {
                        interceptedCaptions = { url: respUrl, body, length: body.length };
                    }
                }
            }
        } catch (e) {}
    });

    await page.goto(url, { waitUntil: 'load', timeout: 30000 });

    // Handle YouTube/Google consent screen (GDPR regions, fresh profiles)
    try {
        const consentBtn = page.locator(
            'button[aria-label="Accept all"], ' +
            'button:has-text("Accept all"), ' +
            'button:has-text("I agree"), ' +
            'form[action*="consent"] button[type="submit"]'
        );
        if (await consentBtn.first().isVisible({ timeout: 3000 })) {
            await consentBtn.first().click();
            await page.waitForTimeout(2000);
            // May need to re-navigate after consent
            if (!page.url().includes('youtube.com/watch')) {
                await page.goto(url, { waitUntil: 'load', timeout: 30000 });
            }
        }
    } catch (e) {}

    // Wait for YouTube SPA to render
    try {
        await page.waitForSelector('ytd-watch-metadata, #above-the-fold', { timeout: 10000 });
    } catch (e) {}

    // Handle YouTube ads
    for (let adAttempt = 0; adAttempt < 10; adAttempt++) {
        const hasAd = await page.evaluate(() => {
            const adOverlay = document.querySelector('.ytp-ad-player-overlay, .ytp-ad-overlay-container, .ad-showing, .ytp-ad-skip-button-container');
            const adText = document.querySelector('.ytp-ad-text, .ytp-ad-preview-text');
            return !!(adOverlay || adText);
        });
        if (!hasAd) break;
        try {
            const skipBtn = page.locator('.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern, button.ytp-skip-ad-button');
            if (await skipBtn.first().isVisible({ timeout: 500 })) {
                await skipBtn.first().click();
                await page.waitForTimeout(1000);
                continue;
            }
        } catch (e) {}
        await page.waitForTimeout(2000);
    }

    // Wait after ad for captions to start loading
    await page.waitForTimeout(2000);

    // Get video metadata
    const ytMeta = await page.evaluate(() => {
        const info = { title: '', channel: '', description: '' };
        const titleEl = document.querySelector('h1.ytd-watch-metadata yt-formatted-string, h1.title yt-formatted-string');
        if (titleEl) info.title = titleEl.textContent?.trim() || '';
        if (!info.title) info.title = document.title?.replace(' - YouTube', '').trim() || '';
        const channelEl = document.querySelector('#channel-name a, ytd-channel-name a');
        if (channelEl) info.channel = channelEl.textContent.trim();
        try { document.querySelector('tp-yt-paper-button#expand, #expand')?.click(); } catch (e) {}
        const descEl = document.querySelector('#description-inline-expander, ytd-text-inline-expander, #description .content, meta[name="description"]');
        if (descEl) info.description = (descEl.content || descEl.innerText?.trim() || descEl.textContent?.trim() || '').substring(0, 3000);
        return info;
    });

    let transcript = '';
    let transcriptMethod = '';

    // Strategy 1: Network-intercepted captions
    if (interceptedCaptions && interceptedCaptions.body) {
        transcript = parseCaptionBody(interceptedCaptions.body);
        if (transcript) transcriptMethod = 'network_intercept';
    }

    // Strategy 2: Fetch caption URL from player response
    if (!transcript) {
        const captionData = await page.evaluate(async () => {
            try {
                let tracks = null;
                if (window.ytInitialPlayerResponse?.captions?.playerCaptionsTracklistRenderer?.captionTracks) {
                    tracks = window.ytInitialPlayerResponse.captions.playerCaptionsTracklistRenderer.captionTracks;
                }
                if (!tracks) {
                    const player = document.querySelector('#movie_player');
                    if (player && player.getPlayerResponse) {
                        const resp = player.getPlayerResponse();
                        tracks = resp?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
                    }
                }
                if (!tracks || !tracks.length) return null;
                const track = tracks.find(t => t.languageCode === 'en' && t.kind !== 'asr') ||
                    tracks.find(t => t.languageCode === 'en') ||
                    tracks.find(t => t.kind === 'asr') ||
                    tracks[0];
                if (!track || !track.baseUrl) return null;
                let fetchUrl = track.baseUrl;
                if (!fetchUrl.includes('fmt=')) fetchUrl += '&fmt=json3';
                const resp = await fetch(fetchUrl);
                if (!resp.ok) return null;
                const text = await resp.text();
                return text && text.length > 200 ? text : null;
            } catch (e) {
                return null;
            }
        }).catch(() => null);

        if (captionData) {
            transcript = parseCaptionBody(captionData);
            if (transcript) transcriptMethod = 'player_response_fetch';
        }
    }

    // Strategy 3: Trigger captions and wait for network response
    if (!transcript) {
        await page.evaluate(() => {
            const player = document.querySelector('#movie_player');
            if (player) {
                if (player.loadModule) try { player.loadModule('captions'); } catch (e) {}
                if (player.setOption) {
                    try { player.setOption('captions', 'track', { languageCode: 'en' }); } catch (e) {}
                }
            }
        });
        try {
            const ccBtn = await page.$('.ytp-subtitles-button');
            if (ccBtn) {
                const pressed = await ccBtn.getAttribute('aria-pressed');
                if (pressed === 'false') await ccBtn.click();
            }
        } catch (e) {}
        await page.waitForTimeout(5000);

        if (interceptedCaptions && interceptedCaptions.body) {
            transcript = parseCaptionBody(interceptedCaptions.body);
            if (transcript) transcriptMethod = 'network_intercept_triggered';
        }
    }

    // Strategy 4: "Show transcript" UI panel + DOM scrape
    if (!transcript) {
        try {
            const moreBtn = page.locator('button[aria-label="More actions"]');
            if (await moreBtn.first().isVisible({ timeout: 2000 })) {
                await moreBtn.first().click();
                await page.waitForTimeout(1000);
                const transcriptBtn = page.locator('ytd-menu-service-item-renderer:has-text("transcript"), tp-yt-paper-item:has-text("transcript")');
                if (await transcriptBtn.first().isVisible({ timeout: 2000 })) {
                    await transcriptBtn.first().click();
                    await page.waitForTimeout(2000);

                    if (interceptedCaptions && interceptedCaptions.body && !transcript) {
                        transcript = parseCaptionBody(interceptedCaptions.body);
                        if (transcript) transcriptMethod = 'network_after_ui';
                    }

                    if (!transcript) {
                        const domTranscript = await page.evaluate(() => {
                            const segments = document.querySelectorAll(
                                'ytd-transcript-segment-renderer, ' +
                                '[target-id="engagement-panel-searchable-transcript"] ytd-transcript-segment-renderer'
                            );
                            if (segments.length === 0) return '';
                            return Array.from(segments).map(seg => {
                                const time = seg.querySelector('.segment-timestamp, [class*="timestamp"]')?.textContent?.trim() || '';
                                const text = seg.querySelector('.segment-text, [class*="segment-text"], yt-formatted-string.segment-text')?.textContent?.trim() || '';
                                return text ? `[${time}] ${text}` : '';
                            }).filter(Boolean).join('\n');
                        });
                        if (domTranscript) {
                            transcript = domTranscript;
                            transcriptMethod = 'dom_panel';
                        }
                    }
                } else {
                    await page.keyboard.press('Escape');
                }
            }
        } catch (e) {}
    }

    const output = {
        url,
        title: ytMeta.title || await page.title(),
        channel: ytMeta.channel,
        type: 'youtube_video',
    };
    if (ytMeta.description) output.description = ytMeta.description;
    if (transcript) {
        output.transcript = transcript.length > 50000
            ? transcript.substring(0, 50000) + '\n...(truncated)'
            : transcript;
        output.transcript_source = transcriptMethod;
    } else {
        output.transcript_error = 'No captions/transcript available for this video.';
    }
    return output;
}

// ─── TikTok Extraction ──────────────────────────────────────────────────── //

async function extractTikTok(page, url) {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(3000);

    // If we navigated to a shortlink, wait up to 10s for the redirect to
    // resolve to the canonical /video/<id> URL. On headless Linux, TikTok
    // sometimes serves a bot-check interstitial before redirecting; in that
    // case we bail with a clean error instead of trying to scrape junk.
    const landed = page.url();
    if (!TIKTOK_CANONICAL_RE.test(landed)) {
        try {
            await page.waitForURL(TIKTOK_CANONICAL_RE, { timeout: 10000 });
        } catch (e) {
            return {
                url: page.url(),
                type: 'tiktok_video',
                error: 'tiktok shortlink did not redirect to a canonical /video/ URL within 10s — likely a bot-check interstitial. Cannot extract video content.',
            };
        }
    }

    const ttData = await page.evaluate(() => {
        try {
            const script = document.querySelector('script#__UNIVERSAL_DATA_FOR_REHYDRATION__');
            if (!script) return { error: 'no rehydration data' };
            const data = JSON.parse(script.textContent);
            const detail = data['__DEFAULT_SCOPE__']?.['webapp.video-detail'];
            if (!detail) return { error: 'no video detail' };
            const item = detail.itemInfo?.itemStruct;
            if (!item) return { error: 'no item data' };
            return {
                title: item.desc || '',
                author: item.author?.nickname || item.author?.uniqueId || '',
                subtitleInfos: item.video?.subtitleInfos || [],
                captionInfos: item.video?.claInfo?.captionInfos || [],
                noCaptionReason: item.video?.claInfo?.noCaptionReason,
            };
        } catch (e) {
            return { error: e.message };
        }
    });

    if (ttData.error) {
        return { url, type: 'tiktok_video', error: ttData.error };
    }

    let transcript = '';
    let transcriptMethod = '';

    const subs = ttData.subtitleInfos;
    if (subs.length > 0) {
        const enTrack = subs.find(s => s.LanguageCodeName?.startsWith('eng'))
            || subs.find(s => s.Source === 'ASR')
            || subs[0];

        if (enTrack && enTrack.Url) {
            try {
                const vttText = await page.evaluate(async (captionUrl) => {
                    try {
                        const res = await fetch(captionUrl);
                        if (!res.ok) return '';
                        return await res.text();
                    } catch (e) { return ''; }
                }, enTrack.Url);

                if (vttText) {
                    transcript = parseWebVTT(vttText);
                    if (transcript) {
                        transcriptMethod = `${enTrack.LanguageCodeName} (${enTrack.Source || 'uploaded'})`;
                    }
                }
            } catch (e) {}
        }
    }

    const output = {
        url,
        title: ttData.title,
        author: ttData.author,
        type: 'tiktok_video',
    };
    if (transcript) {
        output.transcript = transcript.length > 50000
            ? transcript.substring(0, 50000) + '\n...(truncated)'
            : transcript;
        output.transcript_source = transcriptMethod;
    } else {
        output.transcript_error = 'No transcript/captions available for this video.';
    }
    return output;
}

// ─── Generic Content Extraction ──────────────────────────────────────────── //

async function extractGeneric(page, url) {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(2000);

    const structuredData = await page.evaluate(() => {
        const scripts = document.querySelectorAll('script[type="application/ld+json"]');
        const data = [];
        scripts.forEach(s => {
            try { data.push(JSON.parse(s.textContent)); } catch (e) {}
        });
        return data;
    });

    const meta = await page.evaluate(() => {
        const tags = {};
        document.querySelectorAll('meta[property], meta[name]').forEach(m => {
            const key = m.getAttribute('property') || m.getAttribute('name');
            if (key && (key.startsWith('og:') || key.includes('price') || key.includes('status') || key.includes('description'))) {
                tags[key] = m.content;
            }
        });
        return tags;
    });

    const content = await page.evaluate(() => {
        const mainSelectors = ['main', 'article', '[role="main"]', '#content', '.content', '.listing-detail', '.hdp-content'];
        let root = null;
        for (const sel of mainSelectors) {
            root = document.querySelector(sel);
            if (root) break;
        }
        if (!root) root = document.body;

        const lines = [];
        const walk = (node) => {
            if (node.nodeType === 3) {
                const text = node.textContent.trim();
                if (text) lines.push(text);
                return;
            }
            if (node.nodeType !== 1) return;
            const tag = node.tagName.toLowerCase();
            if (['script', 'style', 'nav', 'footer', 'noscript', 'svg'].includes(tag)) return;
            const style = window.getComputedStyle(node);
            if (style.display === 'none' || style.visibility === 'hidden') return;

            if (['h1', 'h2', 'h3', 'h4'].includes(tag)) {
                lines.push('\n## ' + node.textContent.trim());
            } else if (tag === 'a' && node.href && !node.href.startsWith('javascript:')) {
                const linkText = node.textContent.trim();
                const href = node.href;
                if (linkText && href) {
                    lines.push('[' + linkText.substring(0, 120) + '](' + href + ')');
                }
            } else if (tag === 'li') {
                lines.push('- ' + node.textContent.trim());
            } else {
                for (const child of node.childNodes) walk(child);
            }
        };
        walk(root);

        const deduped = lines.filter((line, i) => i === 0 || line !== lines[i - 1]);
        return deduped.join('\n');
    });

    const truncated = content.length > 25000
        ? content.substring(0, 25000) + '\n...(truncated)'
        : content;

    const output = {
        url: page.url(),
        title: await page.title(),
        type: 'webpage',
    };
    if (structuredData.length > 0) output.structured_data = structuredData;
    if (Object.keys(meta).length > 0) output.metadata = meta;
    output.content = truncated;
    return output;
}

// ─── Action Router ───────────────────────────────────────────────────────── //

// Recognise TikTok shortlinks (tiktok.com/t/<code>/, vm.tiktok.com/<code>/) too —
// without this they fell through to the generic extractor and hung on TikTok's
// SPA / bot-check. The TikTok extractor itself now resolves the shortlink to
// the canonical /video/ URL before parsing rehydration data.
const TIKTOK_SHORTLINK_RE = /^https?:\/\/(?:[a-z0-9-]+\.)?tiktok\.com\/t\/[A-Za-z0-9]+/i;
const TIKTOK_VM_RE = /^https?:\/\/vm\.tiktok\.com\/[A-Za-z0-9]+/i;
const TIKTOK_CANONICAL_RE = /tiktok\.com\/.+\/video\/\d+/i;

function detectContentType(url) {
    if (url.includes('youtube.com/watch') || url.includes('youtu.be/')) return 'youtube';
    if (TIKTOK_CANONICAL_RE.test(url) || TIKTOK_SHORTLINK_RE.test(url) || TIKTOK_VM_RE.test(url)) return 'tiktok';
    return 'generic';
}

async function handleAction(input) {
    const { url, action = 'extract', selector, text, javascript } = input;
    const { browser, context, page } = await launchBrowser();

    try {
        switch (action) {
            case 'extract':
            case 'read': {
                const type = detectContentType(url);
                if (type === 'youtube') return await extractYouTube(page, url);
                if (type === 'tiktok') return await extractTikTok(page, url);
                return await extractGeneric(page, url);
            }

            case 'screenshot': {
                await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
                await page.waitForTimeout(2000);
                const buffer = await page.screenshot({ fullPage: false });
                return {
                    url: page.url(),
                    title: await page.title(),
                    type: 'screenshot',
                    screenshot_base64: buffer.toString('base64'),
                };
            }

            case 'click': {
                if (!selector) return { error: 'selector required for click action' };
                await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
                await page.waitForTimeout(1000);
                await page.click(selector, { timeout: 10000 });
                await page.waitForTimeout(1000);
                return {
                    url: page.url(),
                    title: await page.title(),
                    type: 'click_result',
                    clicked: selector,
                };
            }

            case 'type': {
                if (!selector || !text) return { error: 'selector and text required for type action' };
                await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
                await page.waitForTimeout(1000);
                await page.fill(selector, text);
                return {
                    url: page.url(),
                    title: await page.title(),
                    type: 'type_result',
                    typed: text,
                    into: selector,
                };
            }

            case 'evaluate': {
                if (!javascript) return { error: 'javascript required for evaluate action' };
                await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
                await page.waitForTimeout(1000);
                const evalResult = await page.evaluate(javascript);
                return {
                    url: page.url(),
                    title: await page.title(),
                    type: 'evaluate_result',
                    result: evalResult,
                };
            }

            case 'links': {
                await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
                await page.waitForTimeout(1000);
                const links = await page.evaluate(() => {
                    return Array.from(document.querySelectorAll('a[href]')).slice(0, 50).map(a => ({
                        text: (a.textContent || '').trim().substring(0, 80),
                        href: a.href,
                    })).filter(l => l.text && l.href && !l.href.startsWith('javascript:'));
                });
                return {
                    url: page.url(),
                    title: await page.title(),
                    type: 'links',
                    links,
                    count: links.length,
                };
            }

            default:
                return { error: `Unknown action: ${action}. Use: extract, screenshot, click, type, evaluate, read, links` };
        }
    } finally {
        await browser.close().catch(() => {});
    }
}

module.exports = { handleAction };
