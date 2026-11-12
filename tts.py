import asyncio
import concurrent.futures
import os
import queue
import threading
import time
import uuid

from .config import data_dir

ENGINES = [
    ("edge", "Edge TTS (бесплатно, сотни голосов)"),
    ("fish", "Fish Audio (API ключ)"),
    ("elevenlabs", "ElevenLabs (API ключ)"),
    ("sapi", "Windows SAPI (офлайн, самый лёгкий)"),
]
DEFAULT_EDGE = {"ru": "ru-RU-SvetlanaNeural", "en": "en-US-AriaNeural"}


def _mci(cmd, buf=None, n=0):
    import ctypes
    return ctypes.windll.winmm.mciSendStringW(cmd, buf, n, 0)


class TTS:
    def __init__(self, cfg):
        self.cfg = cfg
        self.gen = 0
        self.aq = queue.Queue()  # (gen, future) in speaking order; synthesis runs in parallel
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        self.inflight = 0
        self.lock = threading.Lock()
        self.on_error = None
        self._sapi_obj = None
        self.tmp = os.path.join(data_dir(), "tmp")
        os.makedirs(self.tmp, exist_ok=True)
        for f in os.listdir(self.tmp):
            try:
                os.remove(os.path.join(self.tmp, f))
            except Exception:
                pass
        threading.Thread(target=self._play_loop, daemon=True).start()

    @property
    def busy(self):
        return self.inflight > 0

    def _dec(self):
        with self.lock:
            self.inflight = max(0, self.inflight - 1)

    def say(self, text):
        if not self.cfg["tts_enabled"] or not text.strip():
            return
        with self.lock:
            self.inflight += 1
            gen = self.gen
            # synthesis of the next phrases starts right away, while the previous one is still playing
            fut = self.pool.submit(self._synth_item, gen, text)
            self.aq.put((gen, fut))

    def stop(self):
        with self.lock:
            self.gen += 1
        try:
            while True:
                _, fut = self.aq.get_nowait()
                if not fut.cancel() and fut.done():
                    try:
                        item = fut.result()
                        if item and item[1] == "file":
                            self._rm(item[2])
                    except Exception:
                        pass
                self._dec()
        except queue.Empty:
            pass

    def _rm(self, p):
        try:
            os.remove(p)
        except Exception:
            pass

    def _err(self, e):
        if self.on_error:
            self.on_error("Голос: %s" % e)

    def _voice(self):
        eng = self.cfg["tts_engine"]
        v = self.cfg["tts_voices"].get(eng, "")
        if not v and eng == "edge":
            v = DEFAULT_EDGE.get(self.cfg["lang"], DEFAULT_EDGE["en"])
        return v

    # ---------- synthesis ----------
    def _synth_item(self, gen, text):
        if gen != self.gen:
            return None
        eng = self.cfg["tts_engine"]
        if eng == "sapi":
            return (gen, "sapi", text)
        path = self._synth_file(eng, text)
        if gen != self.gen:  # stopped while synthesizing
            self._rm(path)
            return None
        return (gen, "file", path)

    def _synth_file(self, eng, text):
        path = os.path.join(self.tmp, uuid.uuid4().hex + ".mp3")
        cfg = self.cfg
        if eng == "edge":
            import edge_tts
            rate = "%+d%%" % int(cfg["tts_rate"])

            async def go():
                await edge_tts.Communicate(text, self._voice(), rate=rate).save(path)
            asyncio.run(go())
        elif eng == "fish":
            import requests
            key = cfg["keys"].get("fish", "")
            if not key:
                raise RuntimeError("нет ключа Fish Audio")
            body = {"text": text, "format": "mp3", "mp3_bitrate": 128, "latency": "balanced",
                    "normalize": True}
            if self._voice():
                body["reference_id"] = self._voice()
            if cfg["tts_rate"]:
                body["prosody"] = {"speed": max(0.5, min(2.0, 1 + cfg["tts_rate"] / 100.0))}
            r = requests.post("https://api.fish.audio/v1/tts",
                              headers={"Authorization": "Bearer " + key, "model": "s1"},
                              json=body, timeout=60)
            if r.status_code >= 400:
                raise RuntimeError("Fish %d: %s" % (r.status_code, r.text[:150]))
            with open(path, "wb") as f:
                f.write(r.content)
        elif eng == "elevenlabs":
            import requests
            key = cfg["keys"].get("elevenlabs", "")
            if not key or not self._voice():
                raise RuntimeError("нужны ключ и голос ElevenLabs")
            r = requests.post("https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=mp3_44100_64"
                              % self._voice(), headers={"xi-api-key": key},
                              json={"text": text, "model_id": "eleven_flash_v2_5"}, timeout=60)
            if r.status_code >= 400:
                raise RuntimeError("ElevenLabs %d: %s" % (r.status_code, r.text[:150]))
            with open(path, "wb") as f:
                f.write(r.content)
        else:
            raise RuntimeError("неизвестный движок")
        return path

    # ---------- playback ----------
    def _play_loop(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass
        while True:
            gen, fut = self.aq.get()
            item = None
            try:
                item = fut.result(timeout=60)
                if item is None or item[0] != self.gen:
                    continue
                if item[1] == "sapi":
                    self._play_sapi(item[2], item[0])
                else:
                    self._play_file(item[2], item[0])
            except concurrent.futures.CancelledError:
                pass
            except Exception as e:
                self._err(e)
            finally:
                if item and item[1] == "file":
                    self._rm(item[2])
                self._dec()

    def _play_file(self, path, gen):
        alias = "nova" + uuid.uuid4().hex[:6]
        _mci('open "%s" type mpegvideo alias %s' % (path, alias))
        _mci("play " + alias)
        import ctypes
        buf = ctypes.create_unicode_buffer(64)
        time.sleep(0.05)
        while gen == self.gen:
            _mci("status %s mode" % alias, buf, 64)
            if buf.value != "playing":
                break
            time.sleep(0.03)
        _mci("stop " + alias)
        _mci("close " + alias)

    def _sapi(self):
        if not self._sapi_obj:
            import win32com.client
            self._sapi_obj = win32com.client.Dispatch("SAPI.SpVoice")
        return self._sapi_obj

    def _play_sapi(self, text, gen):
        v = self._sapi()
        v.Rate = int(self.cfg["tts_rate"] / 10)
        want = self.cfg["tts_voices"].get("sapi", "")
        if want:
            for t in v.GetVoices():
                if t.GetDescription() == want:
                    v.Voice = t
                    break
        v.Speak(text, 1)
        while not v.WaitUntilDone(50):
            if gen != self.gen:
                v.Speak("", 3)
                break


# ---------- voice lists (return [(label, id)]) ----------
def list_voices(engine, cfg, query=""):
    lang = cfg["lang"]
    q = query.strip().lower()
    if engine == "edge":
        import edge_tts
        vs = asyncio.run(edge_tts.list_voices())
        out = []
        for v in vs:
            label = "%s  %s" % (v["ShortName"], v.get("Gender", ""))
            if q:
                if q in label.lower() or q in v.get("Locale", "").lower():
                    out.append((label, v["ShortName"]))
            elif v["Locale"].lower().startswith(lang):
                out.append((label, v["ShortName"]))
        return sorted(out)
    if engine == "fish":
        import requests
        key = cfg["keys"].get("fish", "")
        if not key:
            raise RuntimeError("Введите ключ Fish Audio")
        params = {"page_size": 50, "page_number": 1, "sort_by": "task_count"}
        if q:
            params["title"] = q
        else:
            params["language"] = lang
        r = requests.get("https://api.fish.audio/model", headers={"Authorization": "Bearer " + key},
                         params=params, timeout=20)
        if r.status_code >= 400:
            raise RuntimeError("Fish %d" % r.status_code)
        return [(it["title"], it["_id"]) for it in r.json().get("items", [])]
    if engine == "elevenlabs":
        import requests
        key = cfg["keys"].get("elevenlabs", "")
        if not key:
            raise RuntimeError("Введите ключ ElevenLabs")
        r = requests.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key}, timeout=20)
        if r.status_code >= 400:
            raise RuntimeError("ElevenLabs %d" % r.status_code)
        return [(v["name"], v["voice_id"]) for v in r.json().get("voices", [])
                if not q or q in v["name"].lower()]
    if engine == "sapi":
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        v = win32com.client.Dispatch("SAPI.SpVoice")
        return [(t.GetDescription(), t.GetDescription()) for t in v.GetVoices()]
    return []
