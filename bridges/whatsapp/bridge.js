#!/usr/bin/env node
/**
 * HAL WhatsApp bridge.
 *
 * Links to HAL's WhatsApp account as a companion device (Baileys) and speaks
 * the same orchestrator contract as the iMessage Mac bridge:
 *   - inbound chat message  -> POST /api/message (channel: "whatsapp")
 *   - reply / side_messages / result_images -> sent back into WhatsApp
 *   - GET /api/outbox?channel=whatsapp poll -> proactive deliveries
 *
 * Pairing: on first run with no saved creds, set WHATSAPP_PAIRING_NUMBER to
 * HAL's number (digits only, e.g. 12015551234) and this bridge logs an
 * 8-char code to enter under WhatsApp > Linked devices > Link with phone
 * number. Without the env var it logs a QR to scan instead. Creds persist in
 * WHATSAPP_AUTH_DIR; pairing is once.
 *
 * Exit-on-disconnect by design: launchd (com.hal.whatsapp.plist, KeepAlive)
 * owns the restart loop, mirroring the iMessage bridge.
 */

"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const pino = require("pino");
const qrcodeTerminal = require("qrcode-terminal");
const {
  default: makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
  downloadMediaMessage,
  DisconnectReason,
  Browsers,
} = require("@whiskeysockets/baileys");

const ORCHESTRATOR_URL =
  process.env.HAL_ORCHESTRATOR_URL ||
  "https://hal-orchestrator-production.up.railway.app";
const BRIDGE_SECRET = process.env.HAL_BRIDGE_SECRET || "";
const AUTH_DIR =
  process.env.WHATSAPP_AUTH_DIR || path.join(os.homedir(), ".hal", "whatsapp-auth");
const PAIRING_NUMBER = (process.env.WHATSAPP_PAIRING_NUMBER || "").replace(/\D/g, "");
const PAIRING_CODE_FILE = path.join(os.homedir(), ".hal", "whatsapp-pairing-code.txt");
const OUTBOX_POLL_MS = Number(process.env.WHATSAPP_OUTBOX_POLL_MS || 4000);
const MESSAGE_TIMEOUT_MS = 180_000;
const IMAGE_MIME_RX = /^image\/(jpeg|jpg|png|gif|webp|heic|heif)$/;

const logger = pino({ level: process.env.WHATSAPP_LOG_LEVEL || "warn" });

function log(line) {
  console.log(`[${new Date().toISOString()}] ${line}`);
}

if (!BRIDGE_SECRET) {
  log("FATAL: HAL_BRIDGE_SECRET not set");
  process.exit(1);
}

// ---------------------------------------------------------------- jid utils

function jidToPhone(jid, alt) {
  // 12015551234@s.whatsapp.net (optionally :device suffix) -> +12015551234.
  // @lid jids carry no phone number; callers pass the *Pn alt when present.
  const candidate =
    jid && jid.endsWith("@s.whatsapp.net") ? jid : alt && alt.includes("@") ? alt : null;
  if (!candidate || !candidate.endsWith("@s.whatsapp.net")) return null;
  const digits = candidate.split("@")[0].split(":")[0].replace(/\D/g, "");
  return digits ? `+${digits}` : null;
}

function destinationToJid(to) {
  // Outbox destinations: a WhatsApp group jid passes through; a +E.164 silo
  // becomes a user jid.
  if (to.includes("@")) return to;
  const digits = to.replace(/\D/g, "");
  return digits ? `${digits}@s.whatsapp.net` : null;
}

function unwrapMessage(content) {
  let node = content;
  for (const wrapper of [
    "ephemeralMessage",
    "viewOnceMessage",
    "viewOnceMessageV2",
    "documentWithCaptionMessage",
  ]) {
    if (node && node[wrapper] && node[wrapper].message) node = node[wrapper].message;
  }
  return node;
}

// ------------------------------------------------------------- orchestrator

async function api(pathname, options = {}) {
  const response = await fetch(`${ORCHESTRATOR_URL}${pathname}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${BRIDGE_SECRET}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    signal: AbortSignal.timeout(options.timeoutMs || 30_000),
  });
  if (!response.ok) {
    throw new Error(`${pathname} -> HTTP ${response.status}: ${await response.text()}`);
  }
  return response.json();
}

// ----------------------------------------------------------------- sending

async function sendText(sock, jid, text) {
  if (!text) return;
  await sock.sendMessage(jid, { text });
}

async function sendImages(sock, jid, images) {
  for (const image of images || []) {
    try {
      await sock.sendMessage(jid, { image: Buffer.from(image.data, "base64") });
    } catch (error) {
      log(`image send failed to ${jid}: ${error.message}`);
    }
  }
}

// ----------------------------------------------------------------- inbound

const groupNameCache = new Map(); // jid -> {name, at}

async function groupName(sock, jid) {
  const cached = groupNameCache.get(jid);
  if (cached && Date.now() - cached.at < 3_600_000) return cached.name;
  try {
    const metadata = await sock.groupMetadata(jid);
    groupNameCache.set(jid, { name: metadata.subject, at: Date.now() });
    return metadata.subject;
  } catch {
    return cached ? cached.name : null;
  }
}

const seenIds = new Set(); // local echo of orchestrator idempotency, bounded

function alreadySeen(id) {
  if (seenIds.has(id)) return true;
  seenIds.add(id);
  if (seenIds.size > 2000) {
    for (const value of seenIds) {
      seenIds.delete(value);
      if (seenIds.size <= 1000) break;
    }
  }
  return false;
}

async function extractImages(sock, msg, content) {
  const image = content.imageMessage;
  if (!image || !IMAGE_MIME_RX.test(image.mimetype || "")) return [];
  try {
    const buffer = await downloadMediaMessage(msg, "buffer", {}, {
      logger,
      reuploadRequest: sock.updateMediaMessage,
    });
    return [{ mime_type: image.mimetype, data: buffer.toString("base64") }];
  } catch (error) {
    log(`media download failed: ${error.message}`);
    return [];
  }
}

async function handleInbound(sock, msg) {
  const key = msg.key || {};
  const remoteJid = key.remoteJid || "";
  if (!msg.message || key.fromMe) return;
  if (
    remoteJid === "status@broadcast" ||
    remoteJid.endsWith("@broadcast") ||
    remoteJid.endsWith("@newsletter")
  )
    return;
  if (alreadySeen(`${remoteJid}|${key.id}`)) return;

  const content = unwrapMessage(msg.message);
  if (content.protocolMessage || content.reactionMessage || content.pollUpdateMessage)
    return;

  const text =
    content.conversation ||
    (content.extendedTextMessage && content.extendedTextMessage.text) ||
    (content.imageMessage && content.imageMessage.caption) ||
    "";
  const images = await extractImages(sock, msg, content);
  if (!text && images.length === 0) return;

  const isGroup = remoteJid.endsWith("@g.us");
  const senderPhone = isGroup
    ? jidToPhone(key.participant || "", key.participantPn || msg.participantPn)
    : jidToPhone(remoteJid, key.senderPn || key.remoteJidAlt);
  if (!senderPhone && !isGroup) {
    log(`skip: cannot resolve sender phone for ${remoteJid}`);
    return;
  }

  const payload = {
    message_id: `wa:${key.id}`,
    channel: "whatsapp",
    phone: senderPhone || remoteJid,
    text,
    sender_name: msg.pushName || null,
    is_group: isGroup,
    group_name: isGroup ? await groupName(sock, remoteJid) : null,
    chat_id: isGroup ? remoteJid : null,
    images,
  };

  log(
    `inbound ${isGroup ? "group " + remoteJid : senderPhone}: ` +
      `${text.slice(0, 80)}${images.length ? ` [+${images.length} img]` : ""}`
  );

  let result;
  try {
    result = await api("/api/message", {
      method: "POST",
      body: JSON.stringify(payload),
      timeoutMs: MESSAGE_TIMEOUT_MS,
    });
  } catch (error) {
    log(`orchestrator error: ${error.message}`);
    return;
  }

  if (result.reply) await sendText(sock, remoteJid, result.reply);
  await sendImages(sock, remoteJid, result.result_images);
  for (const side of result.side_messages || []) {
    const jid = destinationToJid(side.to || "");
    if (jid) {
      await sendText(sock, jid, side.text).catch((error) =>
        log(`side message to ${side.to} failed: ${error.message}`)
      );
    }
  }
}

// ------------------------------------------------------------------ outbox

let outboxTimer = null;

function startOutboxLoop(sock) {
  stopOutboxLoop();
  outboxTimer = setInterval(async () => {
    try {
      const { messages } = await api(
        `/api/outbox?ack=false&limit=50&channel=whatsapp`
      );
      if (!messages || messages.length === 0) return;
      const delivered = [];
      for (const item of messages) {
        const jid = destinationToJid(item.to || "");
        if (!jid) {
          log(`outbox ${item.id}: undeliverable destination ${item.to}`);
          continue;
        }
        try {
          await sendText(sock, jid, item.text);
          await sendImages(sock, jid, item.images);
          delivered.push(item.id);
        } catch (error) {
          log(`outbox send to ${item.to} failed: ${error.message}`);
        }
      }
      if (delivered.length) {
        await api("/api/outbox/ack", {
          method: "POST",
          body: JSON.stringify({ message_ids: delivered, delivered: true }),
        });
        log(`delivered ${delivered.length} outbox message(s)`);
      }
    } catch (error) {
      log(`outbox poll failed: ${error.message}`); // best-effort, next tick retries
    }
  }, OUTBOX_POLL_MS);
}

function stopOutboxLoop() {
  if (outboxTimer) clearInterval(outboxTimer);
  outboxTimer = null;
}

// ------------------------------------------------------------------- main

async function main() {
  fs.mkdirSync(AUTH_DIR, { recursive: true });
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  const sock = makeWASocket({
    version,
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, logger),
    },
    logger,
    browser: Browsers.macOS("Desktop"),
    markOnlineOnConnect: false, // keep push notifications on the primary phone
    syncFullHistory: false,
  });

  let pairingRequested = false;

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr && !state.creds.registered) {
      if (PAIRING_NUMBER && !pairingRequested) {
        pairingRequested = true;
        try {
          const code = await sock.requestPairingCode(PAIRING_NUMBER);
          fs.writeFileSync(PAIRING_CODE_FILE, `${code}\n`, { mode: 0o600 });
          log(`PAIRING CODE: ${code}  (WhatsApp > Linked devices > Link with phone number)`);
        } catch (error) {
          log(`pairing code request failed: ${error.message}`);
        }
      } else if (!PAIRING_NUMBER) {
        log("scan this QR from WhatsApp > Linked devices:");
        qrcodeTerminal.generate(qr, { small: true }, (rendered) => console.log(rendered));
      }
    }

    if (connection === "open") {
      log(`connected as ${sock.user && sock.user.id}`);
      startOutboxLoop(sock);
    }

    if (connection === "close") {
      stopOutboxLoop();
      const statusCode =
        lastDisconnect && lastDisconnect.error && lastDisconnect.error.output
          ? lastDisconnect.error.output.statusCode
          : undefined;
      if (statusCode === DisconnectReason.loggedOut) {
        log("FATAL: logged out — delete auth dir and re-pair");
      } else {
        log(`connection closed (status ${statusCode}) — exiting for launchd restart`);
      }
      process.exit(1);
    }
  });

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;
    for (const msg of messages) {
      try {
        await handleInbound(sock, msg);
      } catch (error) {
        log(`inbound handling error: ${error.message}`);
      }
    }
  });
}

main().catch((error) => {
  log(`FATAL: ${error.stack || error.message}`);
  process.exit(1);
});
