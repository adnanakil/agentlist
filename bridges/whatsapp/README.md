# HAL WhatsApp bridge

Links HAL's WhatsApp account (as a Baileys companion device) to the
hal-orchestrator `/api/message` contract. Runs on the Hal Mac next to the
iMessage bridge; launchd (`com.hal.whatsapp`, KeepAlive) owns the restart
loop — the bridge exits on any disconnect.

## Deploy (from this repo)

```bash
rsync -a bridges/whatsapp/bridge.js bridges/whatsapp/package.json hal.local:.hal/whatsapp/
ssh hal.local 'cd .hal/whatsapp && ~/.nvm/versions/node/v20*/bin/npm install --omit=dev'
# Render the plist: substitute __BRIDGE_SECRET__ (same HAL_BRIDGE_SECRET as
# the iMessage bridge) and __NODE_BIN__ (absolute node 20 path), then:
ssh hal.local 'launchctl unload ~/Library/LaunchAgents/com.hal.whatsapp.plist 2>/dev/null;
               launchctl load ~/Library/LaunchAgents/com.hal.whatsapp.plist'
tail -f  # /tmp/hal_whatsapp.log on the Hal Mac
```

## One-time pairing

WhatsApp must already be registered on HAL's phone (the phone is the primary
device; this bridge is a linked device — up to 4 can coexist).

- Pairing code (works over ssh): start the bridge once with
  `WHATSAPP_PAIRING_NUMBER=1201XXXXXXX` (digits only). It logs an 8-char code
  (also written to `~/.hal/whatsapp-pairing-code.txt`); enter it on the phone
  under WhatsApp > Linked devices > Link with phone number.
- QR: start without the env var and scan the QR from the log.

Creds persist in `~/.hal/whatsapp-auth/` — pairing is once. If the log says
`logged out`, delete that dir and re-pair.

## Env

| Var | Default | |
|-----|---------|-|
| `HAL_BRIDGE_SECRET` | — | required, same secret as the iMessage bridge |
| `HAL_ORCHESTRATOR_URL` | prod Railway URL | |
| `WHATSAPP_AUTH_DIR` | `~/.hal/whatsapp-auth` | |
| `WHATSAPP_PAIRING_NUMBER` | — | digits-only number, only for first pairing |
| `WHATSAPP_OUTBOX_POLL_MS` | `4000` | |
| `WHATSAPP_LOG_LEVEL` | `warn` | Baileys internal logger |

## Notes / limits

- DM silos are `+E.164` — the same person on iMessage and WhatsApp shares one
  silo; proactive sends follow the **last** channel they wrote from
  (`hal_silo_channels`). Group silos are the raw WhatsApp group jid
  (`…@g.us`), disjoint from iMessage group ids.
- `side_messages` are delivered on THIS channel — a side message to someone
  who is not on WhatsApp fails (logged, not retried).
- No Find My integration on this channel (`current_location` never sent).
- Unofficial-client caveat: Baileys violates WhatsApp ToS; a ban strands the
  number. Keep HAL's WhatsApp usage disclosure-friendly and low-volume.
