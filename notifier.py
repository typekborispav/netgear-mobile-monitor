"""Posílání upozornění přes Baileys most (whatsapp-bridge/server.js).

Most musí běžet: `cd whatsapp-bridge && npm start` (poprvé naskenuj QR).
Číslo příjemce nastav přes proměnnou prostředí WA_TO nebo konstantu níže.
"""

import os

import requests

BRIDGE_URL = os.environ.get("WA_BRIDGE_URL", "http://127.0.0.1:8088")
# Mezinárodní formát bez '+' a mezer, např. "420123456789". Bez nastaveného
# WA_TO se zprávy neodesílají (dřívější falešný default tiše mířil do prázdna).
WA_TO = os.environ.get("WA_TO", "")


def wa_connected():
    """Vrátí True, pokud je most připojený k WhatsApp."""
    try:
        return bool(requests.get(f"{BRIDGE_URL}/status", timeout=5).json().get("connected"))
    except Exception:
        return False


def notify(text, to=None):
    """Pošle WhatsApp zprávu přes most. Vrátí True při úspěchu.

    Při nedostupném mostu jen varuje a vrátí False (monitoring tím nespadne).
    """
    to = to or WA_TO
    if not to:
        print("⚠️  Není nastaven příjemce – nastavte env WA_TO (např. 420…). "
              "Zpráva neodeslána.")
        return False
    try:
        res = requests.post(f"{BRIDGE_URL}/send", json={"to": to, "text": text}, timeout=15)
        data = res.json()
        if data.get("ok"):
            return True
        print(f"⚠️  WhatsApp nedoručeno: {data.get('error', res.status_code)}")
    except Exception as e:
        print(f"⚠️  Most nedostupný ({e}). Běží `npm start` ve whatsapp-bridge?")
    return False


if __name__ == "__main__":
    # Rychlý test: python notifier.py "zprava"
    import sys
    msg = sys.argv[1] if len(sys.argv) > 1 else "Test z Netgear monitoru ✅"
    print("Most připojen:", wa_connected())
    print("Odesláno:", notify(msg))
