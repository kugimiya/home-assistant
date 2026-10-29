#!/opt/bin/python3
"""Local uniproxy bridge: Yandex ASR/TTS, DeepSeek tools for the reply."""

import asyncio
import os
import ssl
import sys
import traceback

LISTEN = os.environ.get("BRIDGE_LISTEN", "127.0.0.1")
PORT = int(os.environ.get("BRIDGE_PORT", "8443"))
UPSTREAM_HOST = "uniproxy.alice.yandex.net"
UPSTREAM_PATH = "/uni.ws"
TOKEN_FILE = os.environ.get(
    "DEEPSEEK_TOKEN_FILE", "/data/quasar/deepseek-bridge/token"
)
MODE = os.environ.get("BRIDGE_MODE", "hybrid")
LOG_PATH = os.environ.get(
    "BRIDGE_LOG", "/data/quasar/deepseek-bridge/bridge.log"
)

YANDEX_HINTS = (
    "музык",
    "песн",
    "трек",
    "альбом",
    "радио",
    "громче",
    "тише",
    "громкост",
    "таймер",
    "будильник",
    "следующ",
    "предыдущ",
    "пауза",
    "паузу",
    "продолж",
    "моя волна",
    "блютус",
    "bluetooth",
    "поставь",
    "стоп",
    "дальше",
    "назад",
)

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
HOP = {
    "connection",
    "upgrade",
    "host",
    "sec-websocket-key",
    "sec-websocket-version",
    "sec-websocket-extensions",
    "sec-websocket-protocol",
    "content-length",
    "proxy-connection",
    "keep-alive",
    "transfer-encoding",
}


def log(msg):
    line = msg.replace("\n", " ")
    print(line, flush=True)


def read_varint(data, i):
    n = 0
    shift = 0
    while True:
        if i >= len(data):
            raise ValueError("truncated varint")
        b = data[i]
        i += 1
        n |= (b & 0x7F) << shift
        if not (b & 0x80):
            return n, i
        shift += 7
        if shift > 70:
            raise ValueError("varint too long")


def encode_varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def encode_tag(field, wire):
    return encode_varint((field << 3) | wire)


def encode_bytes_field(field, payload):
    return encode_tag(field, 2) + encode_varint(len(payload)) + payload


def encode_string(field, text):
    return encode_bytes_field(field, text.encode())


def encode_varint_field(field, n):
    return encode_tag(field, 0) + encode_varint(n)


def walk(data):
    fields = []
    i = 0
    while i < len(data):
        key, i = read_varint(data, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            val, i = read_varint(data, i)
            fields.append((field, 0, val))
        elif wire == 1:
            fields.append((field, 1, data[i : i + 8]))
            i += 8
        elif wire == 2:
            ln, i = read_varint(data, i)
            fields.append((field, 2, data[i : i + ln]))
            i += ln
        elif wire == 5:
            fields.append((field, 5, data[i : i + 4]))
            i += 4
        else:
            raise ValueError("unsupported wire type")
    return fields


def first(fields, number, wire):
    for field, wt, val in fields:
        if field == number and wt == wire:
            return val
    return None


def first_str(fields, number):
    raw = first(fields, number, 2)
    if raw is None:
        return None
    return raw.decode("utf-8", "replace")


def split_prefix(data):
    if data.startswith(b"AAPI"):
        return b"AAPI", data[4:]
    return b"", data


def _consume_value(wire, data, i):
    if wire == 0:
        _, j = read_varint(data, i)
        return j
    if wire == 1:
        return i + 8
    if wire == 2:
        ln, j = read_varint(data, i)
        return j + ln
    if wire == 5:
        return i + 4
    raise ValueError("unsupported wire type")


def patch_varint(data, path, value):
    """Append WaitClientApproval the way quasar-bridge does, keeping other bytes."""
    if len(path) == 1:
        return data + encode_varint_field(path[0], value)
    out = bytearray()
    found = False
    i = 0
    while i < len(data):
        start = i
        key, i = read_varint(data, i)
        field, wire = key >> 3, key & 7
        end = _consume_value(wire, data, i)
        if field == path[0] and wire == 2:
            ln, body_at = read_varint(data, i)
            body = data[body_at : body_at + ln]
            patched = patch_varint(body, path[1:], value)
            out += encode_bytes_field(field, patched)
            found = True
        else:
            out += data[start:end]
        i = end
    if not found:
        nested = patch_varint(b"", path[1:], value)
        out += encode_bytes_field(path[0], nested)
    return bytes(out)


def enable_approval(data):
    prefix, body = split_prefix(data)
    # TClientMessage.Event=1, VoiceInput=3, Request=3, UniproxyOptions=17, WaitClientApproval=4
    patched = patch_varint(body, [1, 3, 3, 17, 4], 1)
    return prefix + patched


def new_id_like(sample):
    raw = os.urandom(16).hex()
    if isinstance(sample, str) and sample.count("-") == 4 and len(sample) == 36:
        return (
            f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
        )
    return f"{raw[0:8]}-{raw[8:16]}-{raw[16:24]}-{raw[24:32]}"


def parse_client(data):
    _prefix, body = split_prefix(data)
    top = walk(body)
    event = first(top, 1, 2)
    if event is None:
        return None
    ev = walk(event)
    header = first(ev, 1, 2)
    if header is None:
        return None
    mid = first_str(walk(header), 1)
    if not mid:
        return None
    kind = None
    payload = None
    if first(ev, 3, 2) is not None:
        kind, payload = "voice", first(ev, 3, 2)
    elif first(ev, 2, 2) is not None:
        kind, payload = "text", first(ev, 2, 2)
    return {
        "id": mid,
        "kind": kind,
        "payload": payload,
        "continue_for": _nested_id(first(ev, 10, 2)),
        "cancel_for": _nested_id(first(ev, 11, 2)),
    }


def _nested_id(blob):
    if blob is None:
        return None
    return first_str(walk(blob), 1)


def parse_server(data):
    _prefix, body = split_prefix(data)
    top = walk(body)
    event = first(top, 1, 2)
    info = {"kind": None, "id": None, "ref": None, "stream": None, "text": None, "end": False}
    if event is None:
        return info
    ev = walk(event)
    header = first(ev, 1, 2)
    if header is not None:
        hf = walk(header)
        info["id"] = first_str(hf, 1)
        info["ref"] = first_str(hf, 2)
        info["stream"] = first(hf, 4, 0)
    for number, name in ((13, "asr"), (2, "alice"), (14, "tts"), (10, "ack"), (15, "ready")):
        blob = first(ev, number, 2)
        if blob is not None:
            info["kind"] = name
            if name == "asr":
                af = walk(blob)
                info["end"] = first(af, 3, 0) == 1
                rec = first(af, 4, 2)
                if rec is not None:
                    rf = walk(rec)
                    text = first_str(rf, 3) or ""
                    if not text:
                        words = []
                        for field, wire, val in rf:
                            if field == 2 and wire == 2:
                                word = first_str(walk(val), 1)
                                if word:
                                    words.append(word)
                        text = " ".join(words)
                    info["text"] = text
            break
    return info


def request_meta(payload):
    fields = walk(payload)
    header = first(fields, 1, 2)
    hf = walk(header) if header is not None else []
    return {
        "request_id": first_str(hf, 1) or "",
        "seq": first(hf, 3, 0) or 0,
        "dialog_id": first_str(hf, 4) or "",
    }


def build_cancel(request_message_id, like):
    header = encode_string(1, new_id_like(like))
    reason = encode_bytes_field(4, b"")
    cancel = encode_string(1, request_message_id) + reason
    event = encode_bytes_field(1, header) + encode_bytes_field(11, cancel)
    return b"AAPI" + encode_bytes_field(1, event)


def build_continue(request_message_id, like):
    header = encode_string(1, new_id_like(like))
    body = encode_string(1, request_message_id)
    event = encode_bytes_field(1, header) + encode_bytes_field(10, body)
    return b"AAPI" + encode_bytes_field(1, event)


def build_alice_response(meta, ref_message_id, text, like):
    header = (
        encode_string(1, meta["request_id"] or ref_message_id)
        + encode_string(2, new_id_like(like))
        + encode_varint_field(3, meta["seq"])
        + encode_string(4, meta["dialog_id"])
    )
    speech = encode_string(2, text)
    voice = (
        encode_bytes_field(1, speech)
        + encode_varint_field(2, 0)
        + encode_varint_field(9, 1)
    )
    card = (
        encode_string(1, "simple_text")
        + encode_string(2, text)
        + encode_string(6, new_id_like(like))
    )
    response = encode_bytes_field(1, card)
    body = (
        encode_bytes_field(1, header)
        + encode_bytes_field(2, voice)
        + encode_bytes_field(3, response)
    )
    event_header = encode_string(1, new_id_like(like)) + encode_string(2, ref_message_id)
    event = encode_bytes_field(1, event_header) + encode_bytes_field(2, body)
    return b"AAPI" + encode_bytes_field(1, event)


def build_tts(tts_id, text):
    tts = encode_string(1, "ru-RU") + encode_string(3, "audio/opus") + encode_string(7, text)
    header = encode_string(1, tts_id)
    event = encode_bytes_field(1, header) + encode_bytes_field(13, tts)
    return b"AAPI" + encode_bytes_field(1, event)


def route_for(text):
    folded = text.lower().replace("ё", "е")
    for hint in YANDEX_HINTS:
        if hint in folded:
            return "yandex"
    return "llm"


def speakable(text):
    from agent.config import SPOKEN_CHAR_LIMIT

    cleaned = text.replace("**", "").replace("`", "").replace("#", "")
    cleaned = cleaned.replace("*", "")
    return " ".join(cleaned.split())[:SPOKEN_CHAR_LIMIT]


def failure_text(code):
    if code in (401, 403):
        return "Ключ DeepSeek не подошёл."
    if code == 429:
        return "DeepSeek ограничил запросы. Попробуй чуть позже."
    return "Сейчас не получилось получить ответ."


class FrameReader:
    def __init__(self, reader):
        self.reader = reader
        self.buf = bytearray()

    async def read_frame(self):
        while True:
            frame = self._try()
            if frame is not None:
                return frame
            chunk = await self.reader.read(65536)
            if not chunk:
                raise ConnectionError("eof")
            self.buf += chunk

    def _try(self):
        if len(self.buf) < 2:
            return None
        b0, b1 = self.buf[0], self.buf[1]
        fin = bool(b0 & 0x80)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F
        i = 2
        if length == 126:
            if len(self.buf) < 4:
                return None
            length = int.from_bytes(self.buf[2:4], "big")
            i = 4
        elif length == 127:
            if len(self.buf) < 10:
                return None
            length = int.from_bytes(self.buf[2:10], "big")
            i = 10
        if length > 8 * 1024 * 1024:
            raise ValueError("frame too large")
        if masked:
            if len(self.buf) < i + 4:
                return None
            mask = bytes(self.buf[i : i + 4])
            i += 4
        else:
            mask = b""
        if len(self.buf) < i + length:
            return None
        data = bytes(self.buf[i : i + length])
        del self.buf[: i + length]
        if mask:
            data = bytes(b ^ mask[n % 4] for n, b in enumerate(data))
        return fin, opcode, data

    async def messages(self):
        parts = []
        opcode = None
        while True:
            fin, op, data = await self.read_frame()
            if op == 0x8:
                raise ConnectionError("close")
            if op == 0x9:
                yield ("ping", data)
                continue
            if op == 0xA:
                continue
            if op == 0:
                parts.append(data)
            else:
                opcode = op
                parts = [data]
            if fin:
                yield (opcode, b"".join(parts))
                parts = []
                opcode = None


def encode_frame(opcode, data, mask):
    n = len(data)
    mask_bit = 0x80 if mask else 0
    if n < 126:
        header = bytes([0x80 | opcode, mask_bit | n])
    elif n < 65536:
        header = bytes([0x80 | opcode, mask_bit | 126]) + n.to_bytes(2, "big")
    else:
        header = bytes([0x80 | opcode, mask_bit | 127]) + n.to_bytes(8, "big")
    if not mask:
        return header + data
    key = os.urandom(4)
    masked = bytes(b ^ key[i % 4] for i, b in enumerate(data))
    return header + key + masked


class Session:
    def __init__(self):
        self.requests = {}
        self.blocked = set()
        self.history = []
        self.up_lock = asyncio.Lock()
        self.down_lock = asyncio.Lock()
        self.mode = MODE

    async def send_up(self, writer, opcode, data):
        async with self.up_lock:
            writer.write(encode_frame(opcode, data, True))
            await writer.drain()

    async def send_down(self, writer, opcode, data):
        async with self.down_lock:
            writer.write(encode_frame(opcode, data, False))
            await writer.drain()

    async def on_client(self, opcode, data, up, down):
        if self.mode != "hybrid" or opcode != 2:
            await self.send_up(up, opcode, data)
            return
        try:
            msg = parse_client(data)
        except Exception:
            log("client frame did not parse, forwarded")
            await self.send_up(up, opcode, data)
            return
        if msg is None:
            await self.send_up(up, opcode, data)
            return
        if msg["kind"] == "voice":
            await self._on_voice(msg, data, up)
            return
        if msg["continue_for"]:
            req = self.requests.get(msg["continue_for"])
            if req is not None and not req["cloud"] and not req["local"]:
                if req["continuation"] is None:
                    req["continuation"] = data
                    log(f"held continue {msg['continue_for'][-4:]}")
                return
            if req is not None and req["local"]:
                return
        if msg["cancel_for"]:
            req = self.requests.get(msg["cancel_for"])
            if req is not None:
                req["canceled"] = True
        await self.send_up(up, opcode, data)

    async def _on_voice(self, msg, data, up):
        meta = {"request_id": "", "seq": 0, "dialog_id": ""}
        try:
            meta = request_meta(msg["payload"])
        except Exception:
            log("voice meta parse failed")
        try:
            gated = enable_approval(data)
        except Exception:
            log("approval patch failed, forwarding original")
            await self.send_up(up, 2, data)
            return
        req = {
            "id": msg["id"],
            "meta": meta,
            "text": "",
            "final": False,
            "started": False,
            "cloud": False,
            "local": False,
            "canceled": False,
            "continuation": None,
            "tts_id": None,
            "blocked_streams": set(),
        }
        self.requests[msg["id"]] = req
        if len(self.requests) > 32:
            old = next(iter(self.requests))
            self.requests.pop(old, None)
        log(f"voice {msg['id'][-4:]} aapi={data.startswith(b'AAPI')}")
        await self.send_up(up, 2, gated)

    async def on_server(self, opcode, data, up, down):
        if self.mode != "hybrid" or opcode != 2:
            await self.send_down(down, opcode, data)
            return
        if self._drop_audio(data):
            return
        try:
            info = parse_server(data)
        except Exception:
            await self.send_down(down, opcode, data)
            return
        req = self._match(info)
        schedule = False
        if req is not None and info["kind"] == "asr" and info["end"] and not req["final"]:
            req["final"] = True
            req["text"] = info["text"] or ""
            schedule = True
            log(f"asr final chars={len(req['text'])} req={req['id'][-4:]}")
        if req is not None and req["local"] and info["kind"] in ("alice", "tts"):
            if info["ref"] == req["id"] or info["id"] == req["id"]:
                if info["kind"] == "tts" and info["stream"] is not None:
                    self.blocked.add(info["stream"] & 0xFFFFFFFF)
                log(f"drop cloud {info['kind']} {req['id'][-4:]}")
                return
        out = data
        if req is not None and req["tts_id"] and req["tts_id"].encode() in data:
            if len(req["tts_id"]) == len(req["id"]):
                out = data.replace(req["tts_id"].encode(), req["id"].encode())
        await self.send_down(down, opcode, out)
        if schedule and not req["started"]:
            req["started"] = True
            asyncio.create_task(self._resolve(req, up, down))

    def _drop_audio(self, data):
        if data.startswith(b"AAPI") or len(data) < 4:
            return False
        stream_id = int.from_bytes(data[:4], "big")
        return stream_id in self.blocked

    def _match(self, info):
        for key in (info.get("ref"), info.get("id")):
            if key and key in self.requests:
                return self.requests[key]
        for req in self.requests.values():
            if req["tts_id"] and req["tts_id"] in (info.get("ref"), info.get("id")):
                return req
        return None

    async def _resolve(self, req, up, down):
        try:
            text = (req["text"] or "").strip()
            if not text:
                await self._release_yandex(req, up)
                return
            route = route_for(text)
            log(f"route {route} chars={len(text)} req={req['id'][-4:]}")
            if route == "yandex":
                await self._release_yandex(req, up)
                return
            answer, err = await asyncio.to_thread(self._ask, text)
            if req["canceled"]:
                return
            end_session = False
            if err is not None:
                log(f"deepseek error {err}")
                answer = failure_text(err)
            elif getattr(answer, "end_session", False):
                end_session = True
                answer = ""
            elif getattr(answer, "text", None) is not None:
                answer = answer.text
            answer = speakable(answer or "")
            req["local"] = True
            await self.send_up(up, 2, build_cancel(req["id"], req["id"]))
            if end_session or not answer:
                log(f"llm silent req={req['id'][-4:]}")
                return
            tts_id = new_id_like(req["id"])
            req["tts_id"] = tts_id
            await self.send_down(
                down, 2, build_alice_response(req["meta"], req["id"], answer, req["id"])
            )
            await self.send_up(up, 2, build_tts(tts_id, answer))
            log(f"llm reply chars={len(answer)} req={req['id'][-4:]}")
        except Exception:
            log("resolve failed " + traceback.format_exc().splitlines()[-1])

    def _ask(self, text):
        from agent.think import answer as agent_answer

        try:
            from agent.memory import get_memory_manager

            get_memory_manager().set_clear_turns_callback(self.history.clear)
        except Exception as exc:
            log(f"memory hook failed {type(exc).__name__}")
        result = agent_answer(text, self.history)
        if result.error is None and result.text and not result.end_session:
            self.history.append({"role": "user", "content": text})
            self.history.append({"role": "assistant", "content": result.text})
            try:
                from agent.pipeline.tools import consume_last_started_job

                started = consume_last_started_job()
                if started:
                    job_id, title = started
                    self.history.append(
                        {
                            "role": "assistant",
                            "content": f"Запущена задача «{title}» ({job_id}).",
                        }
                    )
            except Exception:
                pass
            del self.history[:-8]
        if result.end_session:
            self.history.clear()
        if result.error is not None:
            return None, result.error
        return result, None

    async def _release_yandex(self, req, up):
        req["cloud"] = True
        payload = req["continuation"] or build_continue(req["id"], req["id"])
        await self.send_up(up, 2, payload)
        log(f"released to yandex req={req['id'][-4:]}")


async def read_http(reader):
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = await reader.read(4096)
        if not chunk:
            raise ConnectionError("eof before headers")
        data += chunk
        if len(data) > 65536:
            raise ValueError("headers too large")
    head, rest = bytes(data).split(b"\r\n\r\n", 1)
    lines = head.decode("latin1").split("\r\n")
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, val = line.split(":", 1)
            headers[key.strip().lower()] = val.strip()
    return lines[0], headers, rest


def ws_accept(key):
    import base64
    import hashlib

    digest = hashlib.sha1((key + WS_GUID).encode()).digest()
    return base64.b64encode(digest).decode()


async def dial_upstream(target, headers):
    path = target if target.startswith("/") else UPSTREAM_PATH
    context = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE"))
    reader, writer = await asyncio.open_connection(
        UPSTREAM_HOST, 443, ssl=context, server_hostname=UPSTREAM_HOST
    )
    key = base64_key()
    protocol = headers.get("sec-websocket-protocol", "")
    lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {UPSTREAM_HOST}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        "Sec-WebSocket-Version: 13",
        f"Sec-WebSocket-Key: {key}",
    ]
    if protocol:
        lines.append(f"Sec-WebSocket-Protocol: {protocol}")
    for name, value in headers.items():
        if name in HOP or name == "sec-websocket-protocol":
            continue
        lines.append(f"{name}: {value}")
    writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
    await writer.drain()
    status_line, response_headers, rest = await read_http(reader)
    if " 101 " not in status_line:
        writer.close()
        raise ConnectionError("upstream status " + status_line[:80])
    return reader, writer, response_headers, rest


def base64_key():
    import base64

    return base64.b64encode(os.urandom(16)).decode()


class PrefixedReader:
    def __init__(self, reader, prefix):
        self.reader = reader
        self.prefix = bytearray(prefix)

    async def read(self, n):
        if self.prefix:
            take = bytes(self.prefix[:n])
            del self.prefix[:n]
            return take
        return await self.reader.read(n)


async def handle_client(reader, writer):
    peer = writer.get_extra_info("peername")
    up_writer = None
    try:
        request_line, headers, rest = await read_http(reader)
        _method, target, _version = request_line.split(" ", 2)
        if rest:
            reader = PrefixedReader(reader, rest)
        log(f"accept {peer} {target.split('?', 1)[0]}")
        up_reader, up_writer, up_headers, up_rest = await dial_upstream(target, headers)
        if up_rest:
            up_reader = PrefixedReader(up_reader, up_rest)
        accept = ws_accept(headers["sec-websocket-key"])
        selected = up_headers.get("sec-websocket-protocol", "")
        response = [
            "HTTP/1.1 101 Switching Protocols",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Accept: {accept}",
        ]
        if selected:
            response.append(f"Sec-WebSocket-Protocol: {selected}")
        writer.write(("\r\n".join(response) + "\r\n\r\n").encode())
        await writer.drain()
        log("upstream open")
        session = Session()
        try:
            from agent.pipeline.config import pipeline_enabled
            from agent.pipeline.service import get_job_service

            if pipeline_enabled():
                get_job_service().ensure_started()
        except Exception as exc:
            log(f"pipeline start failed {type(exc).__name__}")
        client_frames = FrameReader(reader)
        server_frames = FrameReader(up_reader)

        async def client_loop():
            async for opcode, data in client_frames.messages():
                if opcode == "ping":
                    await session.send_down(writer, 0xA, data)
                    continue
                await session.on_client(opcode, data, up_writer, writer)

        async def server_loop():
            async for opcode, data in server_frames.messages():
                if opcode == "ping":
                    await session.send_up(up_writer, 0xA, data)
                    continue
                await session.on_server(opcode, data, up_writer, writer)

        tasks = [asyncio.create_task(client_loop()), asyncio.create_task(server_loop())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, (ConnectionError, asyncio.CancelledError)):
                log(f"session error {type(exc).__name__}: {exc}")
    except Exception as exc:
        log(f"connection failed {type(exc).__name__}: {exc}")
    finally:
        log(f"closed {peer}")
        writer.close()
        if up_writer is not None:
            up_writer.close()


async def serve():
    server = await asyncio.start_server(handle_client, LISTEN, PORT)
    sockets = ", ".join(str(s.getsockname()) for s in server.sockets)
    log(f"listening {sockets} mode={MODE}")
    async with server:
        await server.serve_forever()


def selftest():
    header = encode_string(1, "req") + encode_varint_field(3, 7) + encode_string(4, "dlg")
    treq = encode_bytes_field(17, b"")
    alice = encode_bytes_field(1, header) + encode_bytes_field(3, treq)
    event_header = encode_string(1, "abcdabcd-abcdabcd-abcdabcd-abcdabcd")
    event = encode_bytes_field(1, event_header) + encode_bytes_field(3, alice)
    raw = b"AAPI" + encode_bytes_field(1, event)
    patched = enable_approval(raw)
    msg = parse_client(patched)
    assert msg["kind"] == "voice", msg
    request_fields = walk(msg["payload"])
    options = walk(first(walk(first(request_fields, 3, 2)), 17, 2))
    assert first(options, 4, 0) == 1
    assert request_meta(msg["payload"])["dialog_id"] == "dlg"

    recognition = encode_string(3, "какая погода")
    asr = encode_varint_field(3, 1) + encode_bytes_field(4, recognition)
    sheader = encode_string(1, "sid") + encode_string(2, msg["id"])
    sevent = encode_bytes_field(1, sheader) + encode_bytes_field(13, asr)
    server = b"AAPI" + encode_bytes_field(1, sevent)
    info = parse_server(server)
    assert info["end"] and info["text"] == "какая погода" and info["ref"] == msg["id"]
    assert route_for("какая погода") == "llm"
    assert route_for("поставь музыку") == "yandex"
    answer = build_alice_response(
        {"request_id": "req", "seq": 1, "dialog_id": "dlg"}, msg["id"], "Сорок два.", msg["id"]
    )
    assert answer.startswith(b"AAPI")
    assert parse_server(answer)["kind"] == "alice"
    tts = build_tts(new_id_like(msg["id"]), "Сорок два.")
    assert parse_client(tts)["id"]
    _assert_agent_tools()
    print("selftest ok")


def _assert_agent_tools():
    import tempfile
    from pathlib import Path

    from agent.catalog import enabled_tool_names, execute
    from agent.config import STATION_TOOLS, TOKEN_FILE as agent_token
    from agent.think import build_instructions

    assert agent_token == TOKEN_FILE
    saved = {}
    for name in STATION_TOOLS:
        key = "BRIDGE_TOOL_" + name.upper()
        saved[key] = os.environ.pop(key, None)
    try:
        names = set(enabled_tool_names())
        for required in (
            "get_weather",
            "web_search",
            "run_python",
            "describe_runtime",
            "decline",
            "search_memory",
            "rewrite_self",
            "reset_self",
            "get_home",
            "control_home",
        ):
            assert required in names, required
        for name in STATION_TOOLS:
            assert name not in names, name
        text, ended = execute("set_timer", '{"duration_seconds": 5}')
        assert ended is False and "выключена" in text
        assert route_for("поставь таймер на пять минут") == "yandex"
        assert route_for("включи свет в зале") == "llm"
        assert route_for("выключи лампу") == "llm"
        assert route_for("включи музыку") == "yandex"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.environ["MEMORY_DB_PATH"] = str(root / "memory.db")
            os.environ["PERSONALITY_PATH"] = str(root / "personality.json")
            os.environ["PERSONALITY_OVERLAY_PATH"] = str(root / "overlay.json")
            instructions = build_instructions("какая погода")
            assert "get_weather" in instructions
            assert "web_search" in instructions
            assert "rewrite_self" in instructions
            assert "самопальной" in instructions
            assert "Яндекс Станции" in instructions
            assert "Alice" in instructions
            assert "«Алиса» не пиши" in instructions
            assert "wake-фразу" in instructions
            assert "800 токенов" in instructions
            assert "45 секунд" in instructions
            assert "500 символов" in instructions
            assert "set_timer" not in instructions
            assert "control_home" in instructions
            assert "describe_runtime" in instructions
            assert "run_python" in instructions
            pipe_saved = os.environ.pop("BRIDGE_PIPELINE", None)
            assert "start_background_job" not in enabled_tool_names()
            assert "start_background_job" not in instructions
            os.environ["BRIDGE_PIPELINE"] = "1"
            os.environ["JOBS_DB_PATH"] = str(root / "jobs.db")
            assert "start_background_job" in enabled_tool_names()
            assert "start_background_job" in build_instructions("как агент изучи")
            if pipe_saved is not None:
                os.environ["BRIDGE_PIPELINE"] = pipe_saved
            else:
                os.environ.pop("BRIDGE_PIPELINE", None)
            os.environ.pop("JOBS_DB_PATH", None)
            ran, ran_end = execute("run_python", '{"code": "print(6 * 7)"}')
            assert ran_end is False and ran.strip() == "42", ran
            os.environ["HA_TOKEN"] = "secret-marker"
            leaked, _ = execute(
                "run_python",
                '{"code": "import os; print(os.environ.get(\'HA_TOKEN\', \'gone\'))"}',
            )
            assert "secret-marker" not in leaked and "gone" in leaked, leaked
            os.environ.pop("HA_TOKEN", None)
            layout, layout_end = execute("describe_runtime", "{}")
            assert layout_end is False
            assert "uniproxy.alice.yandex.net" in layout
            assert "api.deepseek.com" in layout
            assert "Локально на колонке" in layout
            assert "run_python:" in layout
            assert "set_timer" in layout
            import agent.catalog as catalog

            original = catalog.home_tool.get_home

            def _boom(target: str = "") -> str:
                raise RuntimeError("нет связи с Home Assistant")

            catalog.home_tool.get_home = _boom
            try:
                crashed, decline = execute("get_home", "{}")
            finally:
                catalog.home_tool.get_home = original
            assert decline is False
            assert "нет связи с Home Assistant" in crashed
            assert crashed.startswith("Ошибка инструмента get_home")
            os.environ["BRIDGE_TOOL_SET_TIMER"] = "1"
            assert "set_timer" in enabled_tool_names()
            assert "set_timer" in build_instructions("поставь таймер")
            assert route_for("поставь таймер на пять минут") == "yandex"
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
        os.environ.pop("MEMORY_DB_PATH", None)
        os.environ.pop("PERSONALITY_PATH", None)
        os.environ.pop("PERSONALITY_OVERLAY_PATH", None)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
    else:
        os.environ.setdefault(
            "SSL_CERT_FILE", "/opt/etc/ssl/certs/ca-certificates.crt"
        )
        try:
            asyncio.run(serve())
        except KeyboardInterrupt:
            pass
