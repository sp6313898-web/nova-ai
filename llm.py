import base64
import json
import os
import socket
import subprocess
import threading
import time

from .config import data_dir


def _p(label, base, model, url="", sug=(), note=""):
    return (label, base, model, url, list(sug), note)


PROVIDERS = {
    "openrouter": _p("OpenRouter (бесплатные модели, без карты)", "https://openrouter.ai/api/v1",
                     "openrouter/free", "https://openrouter.ai/keys",
                     ["openrouter/free", "openai/gpt-oss-120b:free", "openai/gpt-oss-20b:free",
                      "z-ai/glm-4.5-air:free", "meta-llama/llama-3.3-70b-instruct:free",
                      "qwen/qwen3-coder:free"],
                     "openrouter/free сам выбирает работающую бесплатную модель (в том числе с vision). "
                     "Лимит: 20 запросов в минуту, 50 в день (1000 после пополнения на 10 USD). "
                     "Кнопка Список показывает все текущие :free модели."),
    "groq": _p("Groq (бесплатно, очень быстрый)", "https://api.groq.com/openai/v1", "openai/gpt-oss-20b",
               "https://console.groq.com/keys",
               ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"],
               "Лучший выбор для голоса: минимальная задержка. Лимит около 30 запросов в минуту и 1000 в день "
               "на модель, 8000 токенов в минуту. Нужен вход через аккаунт, возможна проверка телефона."),
    "gemini": _p("Google Gemini (бесплатно, умеет vision)",
                 "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash",
                 "https://aistudio.google.com/apikey",
                 ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3-flash-preview"],
                 "Бесплатный тариф Google AI Studio, модели понимают картинки. Google может использовать "
                 "запросы бесплатного тарифа для улучшения своих продуктов."),
    "cerebras": _p("Cerebras (бесплатно, около 1 млн токенов в день)", "https://api.cerebras.ai/v1",
                   "gpt-oss-120b", "https://cloud.cerebras.ai",
                   ["gpt-oss-120b", "llama3.1-8b", "qwen-3-235b-a22b-instruct-2507"],
                   "Очень быстрая бесплатная модель. Список моделей уточняйте кнопкой Список."),
    "mistral": _p("Mistral (бесплатный тариф)", "https://api.mistral.ai/v1", "mistral-small-latest",
                  "https://console.mistral.ai/api-keys",
                  ["mistral-small-latest", "open-mistral-nemo", "pixtral-12b-2409"],
                  "Бесплатный тариф La Plateforme. pixtral понимает картинки."),
    "nvidia": _p("NVIDIA NIM (бесплатно, много моделей)", "https://integrate.api.nvidia.com/v1",
                 "meta/llama-3.3-70b-instruct", "https://build.nvidia.com",
                 ["meta/llama-3.3-70b-instruct", "nvidia/llama-3.1-nemotron-70b-instruct",
                  "meta/llama-3.2-11b-vision-instruct"],
                 "Ключ начинается с nvapi-. Нужна регистрация с проверкой телефона."),
    "github": _p("GitHub Models (бесплатно с аккаунтом GitHub)", "https://models.inference.ai.azure.com",
                 "gpt-4o-mini", "https://github.com/settings/tokens",
                 ["gpt-4o-mini", "gpt-4o", "Meta-Llama-3.1-70B-Instruct", "Mistral-large-2411"],
                 "В поле ключа вставьте токен GitHub (Personal access token). Лимиты небольшие."),
    "zai": _p("Z.AI GLM (бесплатные Flash модели)", "https://api.z.ai/api/paas/v4", "glm-4.7-flash",
              "https://z.ai/manage-apikey/apikey-list",
              ["glm-4.7-flash", "glm-4.5-flash", "glm-4.6v-flash"],
              "glm-4.6v-flash понимает картинки (для vision укажите её в поле Vision модель)."),
    "anthropic": _p("Anthropic Claude (платный ключ)", "https://api.anthropic.com/v1", "claude-sonnet-5-5",
                    "https://console.anthropic.com/settings/keys",
                    ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"],
                    "Платный API. Для Совета ИИ: добавьте ключ и Claude будет одним из умов."),
    "xai": _p("xAI Grok (платный ключ)", "https://api.x.ai/v1", "grok-4", "https://console.x.ai",
              ["grok-4"], "Платный API. Точное имя модели смотрите кнопкой Список."),
    "deepseek": _p("DeepSeek (платный)", "https://api.deepseek.com/v1", "deepseek-chat",
                   "https://platform.deepseek.com/api_keys", ["deepseek-chat"], ""),
    "openai": _p("OpenAI (платный)", "https://api.openai.com/v1", "gpt-4o-mini",
                 "https://platform.openai.com/api-keys", ["gpt-4o-mini", "gpt-4o"],
                 "Впишите точное имя любой своей модели OpenAI (в том числе новейшей) в поле Модель."),
    "ollama": _p("Ollama (локально)", "http://localhost:11434/v1", "llama3.2:3b", "",
                 ["llama3.2:3b", "qwen2.5:3b"], "Нужна установленная и запущенная Ollama."),
    "lmstudio": _p("LM Studio (локально)", "http://localhost:1234/v1", "local-model", "", [],
                   "Запустите Local Server в LM Studio."),
    "custom": _p("Свой OpenAI-совместимый API", "", "", "", [], "Укажите адрес API, ключ и модель."),
    "local": _p("Локальная ИИ (встроенная llama.cpp)", "", "", "", [],
                "Откройте вкладку Локальная ИИ и нажмите Скачать и настроить: всё установится само."),
}
NO_KEY = ("ollama", "lmstudio", "custom", "local")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class LLM:
    def __init__(self, cfg, provider=None):
        self.cfg = cfg
        self.prov = provider or cfg["provider"]
        self.proc = None
        self.port = None
        self.llama = None
        self._stop = False
        self.lock = threading.Lock()

    def ready(self):
        if self.prov != "local":
            return True
        return bool(self.llama) or bool(self.proc and self.proc.poll() is None)

    def preload(self):
        if self.prov != "local":
            return
        try:
            if self._is_dll():
                self._load_llama()
            else:
                self._ensure_server()
        except Exception:
            pass

    def close(self):
        self._stop = True
        self.stop_local()

    def local_running(self):
        return bool(self.llama) or bool(self.proc and self.proc.poll() is None)

    def start_local(self):
        if self._is_dll():
            self._load_llama()
        else:
            self._ensure_server()

    def stop_local(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.proc = None
        self.llama = None
        try:
            if getattr(self, "_logf", None):
                self._logf.close()
        except Exception:
            pass
        self._logf = None

    def cancel(self):
        self._stop = True

    # ---------- local ----------
    def _is_dll(self):
        return self.cfg["llama_lib"].lower().endswith(".dll")

    def _ensure_server(self):
        with self.lock:
            self._ensure_server_locked()

    def _ensure_server_locked(self):
        import requests
        cfg = self.cfg
        lib, model = cfg["llama_lib"], cfg["llama_model"]
        if not os.path.isfile(lib) or not os.path.isfile(model):
            raise RuntimeError("Укажите llama (server.exe или DLL) и модель .gguf в настройках")
        if self.proc and self.proc.poll() is None:
            return
        self.port = free_port()
        threads = int(cfg["threads"]) or (os.cpu_count() or 2)
        ctx = 1024 if cfg["lite"] else int(cfg["ctx"])
        cmd = [lib, "-m", model, "-c", str(ctx), "-t", str(threads),
               "--host", "127.0.0.1", "--port", str(self.port)]
        if cfg["vision_enabled"] and cfg["llama_mmproj"]:
            cmd += ["--mmproj", cfg["llama_mmproj"]]
        logpath = os.path.join(data_dir(), "llama.log")
        self._logf = open(logpath, "wb")
        self.proc = subprocess.Popen(cmd, stdout=self._logf, stderr=subprocess.STDOUT,
                                     creationflags=0x08000000, cwd=os.path.dirname(lib))
        t0 = time.time()
        while time.time() - t0 < 240:
            if self.proc.poll() is not None:
                code = self.proc.returncode
                try:
                    self._logf.flush()
                    with open(logpath, "rb") as lf:
                        tail = lf.read()[-500:].decode("utf-8", "ignore").strip()
                except Exception:
                    tail = ""
                raise RuntimeError("llama server закрылся (код %s). Возможно, модель велика для ОЗУ или "
                                   "сборка не подходит процессору. Лог: %s\n%s" % (code, logpath, tail))
            try:
                if requests.get("http://127.0.0.1:%d/health" % self.port, timeout=1).status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError("llama server не запустился за 4 минуты")

    def _load_llama(self):
        with self.lock:
            self._load_llama_locked()

    def _load_llama_locked(self):
        if self.llama:
            return
        cfg = self.cfg
        lib = cfg["llama_lib"]
        if not os.path.isfile(lib) or not os.path.isfile(cfg["llama_model"]):
            raise RuntimeError("Укажите llama DLL и модель .gguf в настройках")
        os.environ["LLAMA_CPP_LIB"] = lib
        os.environ["LLAMA_CPP_LIB_PATH"] = os.path.dirname(lib)
        try:
            from llama_cpp import Llama
        except Exception:
            raise RuntimeError("Модуль llama_cpp не вшит в эту сборку. Используйте llama-server.exe")
        handler = None
        if cfg["vision_enabled"] and cfg["llama_mmproj"]:
            from llama_cpp.llama_chat_format import Llava15ChatHandler
            handler = Llava15ChatHandler(clip_model_path=cfg["llama_mmproj"])
        self.llama = Llama(model_path=cfg["llama_model"], n_ctx=1024 if cfg["lite"] else int(cfg["ctx"]),
                           n_threads=int(cfg["threads"]) or (os.cpu_count() or 2),
                           chat_handler=handler, verbose=False)

    # ---------- common ----------
    def _endpoint(self, vision):
        cfg = self.cfg
        p = self.prov
        if p == "local":
            self._ensure_server()
            return "http://127.0.0.1:%d/v1" % self.port, "local", ""
        base = cfg["base_url"] if p == "custom" else PROVIDERS[p][1]
        model = cfg["models"].get(p) or PROVIDERS[p][2]
        if vision and cfg["vision_model"]:
            model = cfg["vision_model"]
        key = cfg["keys"].get(p, "")
        if p not in NO_KEY and not key:
            raise RuntimeError("Не задан API ключ. Откройте настройки, вкладка Модель")
        if not base or not model:
            raise RuntimeError("Не заданы адрес или модель. Откройте настройки")
        return base.rstrip("/"), model, key

    @staticmethod
    def _with_image(messages, image_b64):
        msgs = [dict(m) for m in messages]
        for m in reversed(msgs):
            if m["role"] == "user":
                m["content"] = [{"type": "text", "text": m["content"]},
                                {"type": "image_url",
                                 "image_url": {"url": "data:image/jpeg;base64," + image_b64}}]
                break
        return msgs

    def stream(self, messages, image_b64=None):
        self._stop = False
        cfg = self.cfg
        mt = cfg.eff_tokens(self.prov)
        msgs = self._with_image(messages, image_b64) if image_b64 else messages
        if self.prov == "local" and self._is_dll():
            self._load_llama()
            for part in self.llama.create_chat_completion(messages=msgs, max_tokens=mt, stream=True):
                if self._stop:
                    return
                d = part["choices"][0]["delta"].get("content")
                if d:
                    yield d
            return
        import requests
        base, model, key = self._endpoint(bool(image_b64))
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        prov = self.prov
        extra = {}
        if "gpt-oss" in model:
            if prov in ("groq", "cerebras"):
                extra = {"reasoning_effort": "low"}
            elif prov == "openrouter":
                extra = {"reasoning": {"effort": "low"}}
        attempts = [(model, extra)]
        if extra:
            attempts.append((model, {}))
        if prov == "openrouter" and model != "openrouter/free":
            attempts.append(("openrouter/free", {}))
        r = None
        for i, (m, ex) in enumerate(attempts):
            body = {"model": m, "messages": msgs, "stream": True, "max_tokens": mt, "temperature": 0.7}
            body.update(ex)
            r = requests.post(base + "/chat/completions", headers=headers, json=body, stream=True,
                              timeout=(10, 120))
            if r.status_code < 400:
                break
            if i + 1 < len(attempts) and r.status_code in (400, 402, 404, 429, 500, 502, 503):
                continue
            if r.status_code in (401, 403):
                raise RuntimeError("Неверный или недействительный API ключ (%d)" % r.status_code)
            if r.status_code == 429:
                raise RuntimeError("Лимит бесплатного тарифа исчерпан. Подождите минуту или выберите "
                                   "другую модель или провайдера")
            raise RuntimeError("Ошибка API %d (%s, %s): %s" % (r.status_code, prov, m, r.text[:250]))
        got = False
        for line in r.iter_lines():
            if self._stop:
                r.close()
                return
            if not line:
                continue
            line = line.decode("utf-8", "ignore")
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                d = json.loads(data)["choices"][0]["delta"].get("content")
            except Exception:
                continue
            if d:
                got = True
                yield d
        if not got and not self._stop:
            raise RuntimeError("Модель %s не вернула текст (возможно, ушла в размышления). Нажмите "
                               "Проверить ИИ или выберите другую модель" % model)


def list_models(cfg, provider, base_url, key):
    import requests
    base = base_url if provider == "custom" else PROVIDERS[provider][1]
    if not base:
        raise RuntimeError("Нет адреса API")
    headers = {"Authorization": "Bearer " + key} if key else {}
    r = requests.get(base.rstrip("/") + "/models", headers=headers, timeout=15)
    if r.status_code >= 400:
        raise RuntimeError("Ошибка %d" % r.status_code)
    ids = []
    for m in r.json().get("data", []):
        i = m.get("id", "")
        if i.startswith("models/"):
            i = i[7:]
        ids.append(i)
    if provider == "openrouter":
        ids.sort(key=lambda x: (not x.endswith(":free"), x))
    else:
        ids.sort()
    return ids
