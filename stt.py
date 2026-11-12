import collections
import io
import json
import queue
import threading
import wave

STT_ENGINES = [
    ("google", "Google (бесплатно, онлайн)"),
    ("groq", "Groq Whisper (бесплатный лимит, быстро)"),
    ("vosk", "Vosk (офлайн, лёгкий для старых ПК)"),
    ("openai", "OpenAI Whisper (платный ключ)"),
]


def _rms(data):
    try:
        import audioop
        return audioop.rms(data, 2)
    except Exception:
        import array
        a = array.array("h", data)[::4]
        if not a:
            return 0
        return int((sum(x * x for x in a) / len(a)) ** 0.5)


def _wav(pcm):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    return b.getvalue()


class Listener:
    def __init__(self, cfg, on_text, busy_fn, on_error, on_barge=None):
        self.cfg = cfg
        self.on_barge = on_barge
        self.on_text = on_text
        self.busy = busy_fn
        self.on_error = on_error
        self.running = False
        self.state = "listening"
        self.level = 0.0
        self._vosk = None
        self._vosk_path = None

    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False

    def _loop(self):
        try:
            import sounddevice as sd
            q = queue.Queue()
            dev = self.cfg["mic"] if self.cfg["mic"] >= 0 else None
            stream = sd.RawInputStream(samplerate=16000, channels=1, dtype="int16", blocksize=480,
                                       device=dev, callback=lambda d, f, t, s: q.put(bytes(d)))
        except Exception as e:
            self.running = False
            self.on_error("Микрофон: %s" % e)
            return
        noise = None
        pre = collections.deque(maxlen=10)
        voiced = []
        speaking = False
        hits = 0
        barge = 0
        silence = 0
        self.state = "listening"
        with stream:
            while self.running:
                try:
                    data = q.get(timeout=0.2)
                except queue.Empty:
                    continue
                if self.busy():
                    if self.cfg["interrupt"]:
                        lv = _rms(data)
                        self.level = min(1.0, lv / 4000.0)
                        pre.append(data)
                        barge = barge + 1 if lv > max(1800.0, (noise or 0.0) * 6) else 0
                        if barge >= 5 and self.on_barge:
                            barge = 0
                            self.on_barge()
                        continue
                    self.level = 0.0
                    pre.clear()
                    voiced = []
                    speaking = False
                    hits = 0
                    continue
                level = _rms(data)
                self.level = min(1.0, level / 4000.0)
                if noise is None:
                    noise = float(level)
                    continue
                thr = max(350.0, noise * 3.0)
                if not speaking:
                    pre.append(data)
                    noise = noise * 0.97 + level * 0.03
                    hits = hits + 1 if level > thr else 0
                    if hits >= 3:
                        speaking = True
                        voiced = list(pre)
                        silence = 0
                        self.state = "hearing"
                else:
                    voiced.append(data)
                    silence = silence + 1 if level < thr * 0.7 else 0
                    if silence >= 17 or len(voiced) > 500:
                        audio = b"".join(voiced)
                        voiced = []
                        speaking = False
                        hits = 0
                        pre.clear()
                        if len(audio) > 16000 * 2 * 0.4:
                            self.state = "recognizing"
                            try:
                                text = self._recognize(audio)
                            except Exception as e:
                                text = ""
                                self.on_error("Распознавание: %s" % e)
                            self.state = "listening"
                            try:
                                while True:
                                    q.get_nowait()
                            except queue.Empty:
                                pass
                            if text:
                                self.on_text(text)
                        else:
                            self.state = "listening"
        self.state = "listening"
        self.level = 0.0

    def _recognize(self, pcm):
        eng = self.cfg["stt_engine"]
        lang = self.cfg["lang"]
        if eng == "google":
            import speech_recognition as sr
            try:
                return sr.Recognizer().recognize_google(
                    sr.AudioData(pcm, 16000, 2), language={"ru": "ru-RU", "en": "en-US"}.get(lang, "en-US"))
            except sr.UnknownValueError:
                return ""
        if eng == "groq":
            import requests
            key = self.cfg["keys"].get("groq", "")
            if not key:
                raise RuntimeError("нет ключа Groq")
            r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                              headers={"Authorization": "Bearer " + key},
                              files={"file": ("a.wav", _wav(pcm), "audio/wav")},
                              data={"model": "whisper-large-v3-turbo", "language": lang}, timeout=30)
            if r.status_code >= 400:
                raise RuntimeError("Groq %d" % r.status_code)
            return r.json().get("text", "").strip()
        if eng == "openai":
            import requests
            key = self.cfg["keys"].get("openai", "")
            if not key:
                raise RuntimeError("нет ключа OpenAI")
            r = requests.post("https://api.openai.com/v1/audio/transcriptions",
                              headers={"Authorization": "Bearer " + key},
                              files={"file": ("a.wav", _wav(pcm), "audio/wav")},
                              data={"model": "whisper-1", "language": lang}, timeout=30)
            if r.status_code >= 400:
                raise RuntimeError("OpenAI %d" % r.status_code)
            return r.json().get("text", "").strip()
        if eng == "vosk":
            from vosk import Model, KaldiRecognizer, SetLogLevel
            path = self.cfg["vosk_path"]
            if not path:
                raise RuntimeError("укажите папку модели Vosk")
            if self._vosk_path != path:
                SetLogLevel(-1)
                self._vosk = Model(path)
                self._vosk_path = path
            rec = KaldiRecognizer(self._vosk, 16000)
            rec.AcceptWaveform(pcm)
            return json.loads(rec.FinalResult()).get("text", "").strip()
        return ""
