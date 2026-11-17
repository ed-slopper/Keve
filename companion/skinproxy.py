"""Keve wears your skin: a small proxy in front of Keve's server.

In offline mode a server sends no skin for anyone, and players only draw skins that
Mojang hosts, so a new skin can't be made up for Keve. What can be done: the server
trusts a Velocity proxy's forwarding (Horizon's docs/velocity-forwarding.md) and so
takes the skin data the proxy forwards. This proxy forwards *your* skin (Mojang's
signed textures from your profile) for Keve, and your own for you. Everyone joins
through it; the server only listens on 127.0.0.1.

Forwarding, as Horizon reads it: the server sends login plugin request 0x04 on
`velocity:player_info`; the proxy answers with login plugin response 0x02 whose data is
HMAC-SHA256(secret, payload) + payload, payload = version 1, address, UUID, name,
properties. After that, bytes are passed through untouched, except that the proxy also
reads (never changes) what your game sends, to see when you press shift: two quick taps
near Keve mean "hand me what you got". Those go to sneaks.txt in Keve's folder.
"""
import asyncio
import hashlib
import hmac
import json
import os
import time
import zlib
from pathlib import Path
import urllib.request
import uuid as uuidlib


def varint(n):
    out = bytearray()
    n &= 0xFFFFFFFF
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def string(s):
    b = s.encode("utf-8")
    return varint(len(b)) + b


def read_varint(buf, i):
    n, shift = 0, 0
    while True:
        b = buf[i]
        i += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, i
        shift += 7


def read_string(buf, i):
    n, i = read_varint(buf, i)
    return buf[i:i + n].decode("utf-8"), i + n


async def read_packet(reader):
    """One uncompressed packet: (raw bytes with the length prefix, body)."""
    n, shift, prefix = 0, 0, bytearray()
    while True:
        b = (await reader.readexactly(1))[0]
        prefix.append(b)
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            break
        shift += 7
    body = await reader.readexactly(n)
    return bytes(prefix) + body, body


def packet(body):
    return varint(len(body)) + body


def offline_uuid(name):
    """Java's UUID.nameUUIDFromBytes("OfflinePlayer:" + name): the UUID an offline server gives."""
    h = bytearray(hashlib.md5(("OfflinePlayer:" + name).encode("utf-8")).digest())
    h[6] = (h[6] & 0x0F) | 0x30
    h[8] = (h[8] & 0x3F) | 0x80
    return bytes(h)


def fetch_textures(profile_uuid, cache_path):
    """Your skin's signed `textures` property from Mojang's profile service (cached a day)."""
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if time.time() - cached["at"] < 86400 and cached["uuid"] == profile_uuid:
            return cached["property"]
    except (OSError, ValueError, KeyError):
        pass
    url = (f"https://sessionserver.mojang.com/session/minecraft/profile/"
           f"{profile_uuid.replace('-', '')}?unsigned=false")
    req = urllib.request.Request(url, headers={"User-Agent": "keve"})
    with urllib.request.urlopen(req, timeout=15) as r:
        prof = json.loads(r.read())
    prop = next((p for p in prof.get("properties", []) if p["name"] == "textures"), None)
    if prop:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"at": time.time(), "uuid": profile_uuid, "property": prop}),
                              encoding="utf-8")
    return prop


class SkinProxy:
    def __init__(self, listen_port, server_port, secret, skins):
        """`skins`: player name (lower case) -> textures property {name, value, signature}."""
        self.listen_port = listen_port
        self.server_port = server_port
        self.secret = secret
        self.skins = skins

    def forwarding_answer(self, message_id, name, address):
        payload = bytearray(varint(1))
        payload += string(address)
        payload += offline_uuid(name)
        payload += string(name)
        prop = self.skins.get(name.lower())
        if prop:
            payload += varint(1) + string(prop["name"]) + string(prop["value"])
            sig = prop.get("signature")
            payload += (b"\x01" + string(sig)) if sig else b"\x00"
        else:
            payload += varint(0)
        mac = hmac.new(self.secret, bytes(payload), hashlib.sha256).digest()
        body = varint(0x02) + varint(message_id) + b"\x01" + mac + bytes(payload)
        return packet(body)

    async def handle(self, creader, cwriter):
        address = cwriter.get_extra_info("peername")[0]
        try:
            sreader, swriter = await asyncio.open_connection("127.0.0.1", self.server_port)
        except OSError:
            cwriter.close()
            return
        try:
            raw, body = await read_packet(creader)  # handshake
            swriter.write(raw)
            pid, i = read_varint(body, 0)
            _proto, i = read_varint(body, i)
            _host, i = read_string(body, i)
            i += 2
            next_state, i = read_varint(body, i)
            if pid == 0 and next_state in (2, 3):  # login (or transfer): forward the player
                raw, body = await read_packet(creader)  # login start: name, uuid
                swriter.write(raw)
                _, j = read_varint(body, 0)
                name, j = read_string(body, j)
                await swriter.drain()
                while True:  # until the server asks for the forwarding, pass its packets on
                    raw, body = await read_packet(sreader)
                    pid, j = read_varint(body, 0)
                    if pid == 0x04:
                        mid, j = read_varint(body, j)
                        channel, j = read_string(body, j)
                        if channel == "velocity:player_info":
                            swriter.write(self.forwarding_answer(mid, name, address))
                            await swriter.drain()
                            break
                    cwriter.write(raw)
                    await cwriter.drain()
            conn = {"compressed": False, "sneaking": False, "name": name if next_state in (2, 3) else None}
            await asyncio.gather(self.watch_client(creader, swriter, conn),
                                 self.watch_server(sreader, cwriter, conn))
        except (asyncio.IncompleteReadError, ConnectionError, OSError, IndexError):
            pass
        finally:
            for w in (cwriter, swriter):
                try:
                    w.close()
                except Exception:
                    pass

    # --- watching for shift taps (read only) -----------------------------------------
    PLAYER_INPUT = 43  # serverbound play: one byte of input flags (Horizon 26.3, protocol 777)
    SHIFT = 0x20
    SNEAKS = Path(os.environ.get("KEVE_HOME") or Path(os.environ.get("LOCALAPPDATA", ".")) / "Keve") / "sneaks.txt"

    async def watch_server(self, reader, writer, conn):
        """Server to you: read the last login packets to learn whether compression is on,
        then pass everything through as plain bytes."""
        try:
            while conn["name"]:
                raw, body = await read_packet(reader)
                pid, j = read_varint(body, 0)
                writer.write(raw)
                await writer.drain()
                if pid == 0x03:  # set compression: everything after is in the compressed format
                    conn["compressed"] = True
                    break
                if pid == 0x02:  # login finished without compression
                    break
        except (asyncio.IncompleteReadError, ConnectionError, OSError, IndexError):
            writer.close()
            return
        await self.pipe(reader, writer)

    async def watch_client(self, reader, writer, conn):
        """You to the server: forward each packet as it is, and note shift presses."""
        if not conn["name"]:
            await self.pipe(reader, writer)
            return
        try:
            while True:
                raw, body = await read_packet(reader)
                writer.write(raw)
                await writer.drain()
                try:
                    self.note_input(body, conn)
                except (IndexError, zlib.error):
                    pass  # not a packet we understand: it went through untouched anyway
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    def note_input(self, body, conn):
        i = 0
        if conn["compressed"]:
            size, i = read_varint(body, 0)
            data = body[i:] if size == 0 else zlib.decompress(body[i:])
        else:
            data = body
        pid, j = read_varint(data, 0)
        if pid != self.PLAYER_INPUT or len(data) != j + 1:
            return
        sneaking = bool(data[j] & self.SHIFT)
        if sneaking and not conn["sneaking"]:
            self.SNEAKS.parent.mkdir(parents=True, exist_ok=True)
            with open(self.SNEAKS, "a", encoding="utf-8") as f:
                f.write(f"{conn['name']} {time.time():.3f}" + chr(10))
        conn["sneaking"] = sneaking

    @staticmethod
    async def pipe(reader, writer):
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def serve(self):
        server = await asyncio.start_server(self.handle, "127.0.0.1", self.listen_port)
        async with server:
            await server.serve_forever()


def main():
    """python skinproxy.py LISTEN_PORT SERVER_PORT SECRET_FILE SKINS_FILE"""
    import sys
    from pathlib import Path
    listen, server = int(sys.argv[1]), int(sys.argv[2])
    secret = Path(sys.argv[3]).read_text(encoding="utf-8").strip().encode()
    try:
        skins = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        skins = {}
    print(f"Keve's skin proxy: players join 127.0.0.1:{listen}, the server is on {server}", flush=True)
    asyncio.run(SkinProxy(listen, server, secret, skins).serve())


if __name__ == "__main__":
    main()
