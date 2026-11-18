// Baileys most pro Netgear monitoring.
// Připojí se k WhatsApp (multi-device, bez prohlížeče/emulátoru) a vystaví
// lokální HTTP endpoint, na který se Python notifier doptává:
//
//   POST /send   {"to":"420123456789","text":"Ahoj"}   -> odešle WhatsApp zprávu
//   GET  /status                                        -> {"connected":true}
//
// První spuštění vypíše QR kód – naskenuj ho ve WhatsApp:
//   Nastavení → Propojená zařízení → Propojit zařízení.
// Přihlášení se uloží do ./auth_info, takže příště už QR netřeba.

import { createServer } from 'http'
import makeWASocket, {
  DisconnectReason,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
} from '@whiskeysockets/baileys'
import { Boom } from '@hapi/boom'
import pino from 'pino'
import qrcode from 'qrcode-terminal'

const HOST = '127.0.0.1'
const PORT = Number(process.env.WA_PORT || 8088)
const logger = pino({ level: 'silent' })

let sock = null
let connected = false

async function connect() {
  const { state, saveCreds } = await useMultiFileAuthState('./auth_info')
  // Aktuální verze WA Web protokolu – bez ní handshake padá na 405.
  const { version } = await fetchLatestBaileysVersion()
  sock = makeWASocket({ version, auth: state, logger })

  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update

    if (qr) {
      console.log('\n📱 Naskenuj QR ve WhatsApp (Propojená zařízení):\n')
      qrcode.generate(qr, { small: true })
    }
    if (connection === 'open') {
      connected = true
      console.log('✅ WhatsApp připojeno.')
    }
    if (connection === 'close') {
      connected = false
      const code = (lastDisconnect?.error instanceof Boom)
        ? lastDisconnect.error.output?.statusCode
        : undefined
      const loggedOut = code === DisconnectReason.loggedOut
      console.log(`❌ Spojení zavřeno (kód ${code}).`,
        loggedOut ? 'Odhlášeno – smaž auth_info a naskenuj QR znovu.' : 'Připojuji znovu…')
      if (!loggedOut) setTimeout(connect, 2000)
    }
  })
}

function toJid(to) {
  // Přijme "420123456789" i plný JID; nečíselné znaky odstraní.
  if (to.includes('@')) return to
  return to.replace(/[^0-9]/g, '') + '@s.whatsapp.net'
}

function readBody(req) {
  return new Promise((resolve) => {
    let data = ''
    req.on('data', (c) => (data += c))
    req.on('end', () => resolve(data))
  })
}

const server = createServer(async (req, res) => {
  const json = (code, obj) => {
    res.writeHead(code, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify(obj))
  }

  if (req.method === 'GET' && req.url === '/status') {
    return json(200, { connected })
  }

  if (req.method === 'POST' && req.url === '/send') {
    if (!connected) return json(503, { ok: false, error: 'WhatsApp není připojeno' })
    try {
      const { to, text } = JSON.parse((await readBody(req)) || '{}')
      if (!to || !text) return json(400, { ok: false, error: 'chybí "to" nebo "text"' })
      await sock.sendMessage(toJid(to), { text })
      return json(200, { ok: true })
    } catch (e) {
      return json(500, { ok: false, error: String(e) })
    }
  }

  json(404, { ok: false, error: 'neznámý endpoint' })
})

server.listen(PORT, HOST, () => {
  console.log(`Most naslouchá na http://${HOST}:${PORT} (POST /send, GET /status)`)
  connect()
})
