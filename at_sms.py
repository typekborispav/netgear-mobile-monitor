"""Odesílání SMS přes AT příkazy (bez rootu, pokud je AT port dostupný po síti).

Na firmwaru NTGX65 (M3 MH3150, M6 Pro) Netgear odebral HTTP endpoint pro
odesílání SMS. Samotný modem ale SMS pořád umí poslat přes AT příkazy
(AT+CMGF=1, AT+CMGS) — viz rootnuté řešení JeffWDH/MR6500-SMS-Server, které
mluví na /dev/smd8 lokálně.

Tyhle modemy navíc často vystavují AT-command rozhraní jako TELNET PORT
(typicky 5510) i po síti. Pokud je u tvého M3 otevřený, lze SMS poslat přímo
z PC přes socket — bez rootu a bez flashování.

POSTUP (síť):
  1) python at_sms.py probe        # zjistí, které porty jsou otevřené
  2) python at_sms.py at 5510       # interaktivní AT shell pro ruční ověření
  3) python at_sms.py send 5510 +420123456789 "Ahoj"

POSTUP (USB / sériový COM port — bez rootu, pokud modem AT port vystaví):
  1) Připoj M3 USB-C kabelem do PC.
  2) python at_sms.py comports                    # vypíše COM porty
  3) python at_sms.py atcom COM7                   # interaktivní AT shell po COM
  4) python at_sms.py sendcom COM7 +420123456789 "Ahoj"
"""

import socket
import sys
import time

# Windows konzole bývá cp1250 a padala by na emoji ve výpisech – vynutíme UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROUTER_IP = "192.168.1.1"

# Kandidátní porty pro AT rozhraní / shell na Netgear modemech.
# 5510 = AT command telnet (leonzdev/mr6500), 23 = root telnet (starší fw),
# ostatní jsou občas viděné na Sierra/Qualcomm modemech.
CANDIDATE_PORTS = [5510, 23, 7777, 6500, 2332, 5555]


def probe(host=ROUTER_IP, ports=CANDIDATE_PORTS, timeout=2.0):
    """Vypíše, které kandidátní TCP porty jsou otevřené."""
    print(f"Skenuji {host} …")
    open_ports = []
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            try:
                if s.connect_ex((host, port)) == 0:
                    print(f"  ✅ {port} otevřený")
                    open_ports.append(port)
                else:
                    print(f"  ·  {port} zavřený")
            except Exception as e:
                print(f"  ·  {port} chyba: {e}")
    if not open_ports:
        print("Žádný kandidátní port není otevřený — AT cesta po síti zřejmě nepůjde.")
    return open_ports


def _recv(sock, wait=0.6):
    """Posbírá to, co modem pošle zpět, a vrátí jako text."""
    sock.settimeout(wait)
    chunks = []
    try:
        while True:
            data = sock.recv(4096)
            if not data:
                break
            chunks.append(data)
    except socket.timeout:
        pass
    return b"".join(chunks).decode(errors="replace")


def at_shell(port, host=ROUTER_IP):
    """Jednoduchý interaktivní AT shell pro ruční ověření portu.

    Vyzkoušej třeba `AT` (musí vrátit OK) nebo `AT+CMGF=?`.
    Ukončení: prázdný řádek nebo Ctrl+C.
    """
    with socket.create_connection((host, port), timeout=5) as sock:
        banner = _recv(sock)
        if banner.strip():
            print(banner, end="")
        print(f"-- AT shell na {host}:{port} (Enter = konec) --")
        while True:
            try:
                cmd = input("AT> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not cmd:
                break
            sock.sendall((cmd + "\r\n").encode())
            print(_recv(sock), end="")


def send_sms_at(port, receiver, text, host=ROUTER_IP):
    """Odešle SMS přes AT příkazy na daný TCP port modemu.

    Vrací True, pokud modem na AT+CMGS odpověděl OK.
    """
    with socket.create_connection((host, port), timeout=5) as sock:
        _recv(sock)  # případný banner

        def cmd(line, wait=0.8):
            sock.sendall((line + "\r\n").encode())
            resp = _recv(sock, wait)
            print(f">>> {line}\n{resp.strip()}")
            return resp

        # Ověření, že port opravdu mluví AT.
        if "OK" not in cmd("AT"):
            print("❌ Port neodpovídá na 'AT' OK — nejspíš to není AT rozhraní.")
            return False

        cmd("AT+CMGF=1")  # textový režim
        # AT+CMGS vrátí prompt '>' a čeká na text zakončený Ctrl+Z (0x1A).
        cmd(f'AT+CMGS="{receiver}"', wait=1.0)
        sock.sendall((text + "\x1a").encode())
        time.sleep(0.3)
        final = _recv(sock, wait=8.0)  # odeslání může chvíli trvat
        print(final.strip())

        if "OK" in final or "+CMGS" in final:
            print(f"✅ SMS na {receiver} odeslána.")
            return True
        print("❌ Modem nepotvrdil odeslání (viz odpověď výše).")
        return False


# --- Sériová (USB / COM) varianta ----------------------------------------

def comports():
    """Vypíše dostupné COM porty. Hledej modem / diagnostic / Netgear / Qualcomm."""
    try:
        from serial.tools import list_ports
    except ImportError:
        print("Chybí pyserial. Nainstaluj: python -m pip install pyserial")
        return []
    ports = list(list_ports.comports())
    if not ports:
        print("Žádný COM port. Je M3 připojený USB-C kabelem do PC?")
        return []
    print("Dostupné COM porty:")
    for p in ports:
        print(f"  {p.device}  —  {p.description}  [{p.hwid}]")
    print("\nTip: AT port bývá popsaný jako 'modem', 'diagnostic', 'AT' nebo 'Qualcomm'.")
    return ports


def _open_serial(com, baud=115200):
    import serial
    return serial.Serial(com, baud, timeout=1, write_timeout=5)


def _recv_serial(ser, wait=0.8):
    time.sleep(wait)
    data = ser.read(ser.in_waiting or 1)
    return data.decode(errors="replace")


def at_shell_serial(com):
    """Interaktivní AT shell po sériovém portu. Zkus 'AT' → musí vrátit OK."""
    try:
        ser = _open_serial(com)
    except Exception as e:
        print(f"❌ Nelze otevřít {com}: {e}")
        return
    with ser:
        print(f"-- AT shell na {com} (Enter = konec) --")
        while True:
            try:
                cmd = input("AT> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not cmd:
                break
            ser.write((cmd + "\r\n").encode())
            print(_recv_serial(ser), end="")


def send_sms_serial(com, receiver, text):
    """Odešle SMS přes AT příkazy po sériovém (USB COM) portu modemu."""
    try:
        ser = _open_serial(com)
    except Exception as e:
        print(f"❌ Nelze otevřít {com}: {e}")
        return False
    with ser:
        def cmd(line, wait=0.8):
            ser.write((line + "\r\n").encode())
            resp = _recv_serial(ser, wait)
            print(f">>> {line}\n{resp.strip()}")
            return resp

        if "OK" not in cmd("AT"):
            print("❌ Port neodpovídá na 'AT' OK — nejspíš to není AT/modem rozhraní.")
            return False

        cmd("AT+CMGF=1")  # textový režim
        cmd(f'AT+CMGS="{receiver}"', wait=1.0)  # vrátí prompt '>'
        ser.write((text + "\x1a").encode())     # text + Ctrl+Z
        final = _recv_serial(ser, wait=8.0)
        print(final.strip())
        if "OK" in final or "+CMGS" in final:
            print(f"✅ SMS na {receiver} odeslána.")
            return True
        print("❌ Modem nepotvrdil odeslání (viz odpověď výše).")
        return False


def _usage():
    print(__doc__)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "probe":
        probe()
    elif args[0] == "at" and len(args) >= 2:
        at_shell(int(args[1]))
    elif args[0] == "send" and len(args) >= 4:
        send_sms_at(int(args[1]), args[2], " ".join(args[3:]))
    elif args[0] == "comports":
        comports()
    elif args[0] == "atcom" and len(args) >= 2:
        at_shell_serial(args[1])
    elif args[0] == "sendcom" and len(args) >= 4:
        send_sms_serial(args[1], args[2], " ".join(args[3:]))
    else:
        _usage()
