import json
import os
import sys
import time

APP = "NovaAgent"


def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, rel)


def data_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    p = os.path.join(base, APP)
    os.makedirs(p, exist_ok=True)
    return p


DEFAULTS = {
    "name": "нова",
    "lang": "ru",
    "provider": "openrouter",
    "models": {},
    "keys": {},
    "base_url": "",
    "vision_enabled": False,
    "vision_model": "",
    "llama_lib": "",
    "llama_model": "",
    "llama_mmproj": "",
    "threads": 0,
    "ctx": 2048,
    "tts_enabled": True,
    "tts_engine": "edge",
    "tts_voices": {},
    "tts_rate": 20,
    "cfg_ver": 2,
    "stt_engine": "google",
    "vosk_path": "",
    "mic": -1,
    "lite": False,
    "history": 8,
    "max_tokens": 300,
    "custom_apps": "",
    "wake": True,
    "ack": "Да, хозяин",
    "autolisten": True,
    "setup_done": False,
    "persona": "friend",
    "owner": "хозяин",
    "city": "",
    "brief_on": False,
    "brief_time": "08:00",
    "last_brief": "",
    "tray": True,
    "close_to_tray": True,
    "hotkey": "ctrl+alt+n",
    "quiet": False,
    "interrupt": False,
    "converse": False,
    "confirm": True,
    "proactive": False,
    "council_mode": "off",
    "council": [],
    "fallback": True,
    "tg_token": "",
    "tg_chat": "",
    "ha_url": "",
    "ha_token": "",
    "music": "youtube",
    "autostart": False,
}


def log(msg):
    try:
        with open(os.path.join(data_dir(), "agent.log"), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


class Config(dict):
    def __init__(self):
        super().__init__(json.loads(json.dumps(DEFAULTS)))
        self.path = os.path.join(data_dir(), "config.json")
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.update(saved)
            if int(saved.get("cfg_ver", 1)) < 2:
                # speech was too slow at the old default of 0, speed it up once (still adjustable in settings)
                if int(saved.get("tts_rate", 0)) == 0:
                    self["tts_rate"] = 20
                self["cfg_ver"] = 2
        except Exception:
            pass

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(dict(self), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def eff_history(self):
        return 3 if self["lite"] else int(self["history"])

    def eff_tokens(self, prov=None):
        base = int(self["max_tokens"])
        if (prov or self["provider"]) in ("local", "ollama", "lmstudio"):
            return min(200, base) if self["lite"] else base
        # cloud reasoning models spend tokens on thinking, so keep a safe floor
        base = max(base, 800)
        return min(base, 500) if self["lite"] else base
