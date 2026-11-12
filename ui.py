import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import webbrowser

from . import llm as llmmod
from . import localsetup, pc
from . import tts as ttsmod
from .agent import Agent
from .config import Config, resource_path
from .hotkey import Hotkey
from .stt import STT_ENGINES
from .tray import start_tray

BG = "#000000"
PANEL = "#0a0a0a"
LINE = "#1d1d1d"
FG = "#e8e8e8"
DIM = "#707070"
HOT = "#ffffff"
FONT = ("Segoe UI", 10)

STATES = {"awake": "слушаю вас", "idle": "ожидание", "thinking": "думаю", "speaking": "говорю", "listening": "слушаю",
          "hearing": "слышу", "recognizing": "распознаю"}


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    return "#%02x%02x%02x" % (int(ar + (br - ar) * t), int(ag + (bg - ag) * t), int(ab + (bb - ab) * t))


def ease(t):
    return 1 - (1 - max(0.0, min(1.0, t))) ** 3


def fade_window(win, dur=0.3):
    try:
        win.attributes("-alpha", 0.0)
    except Exception:
        return
    t0 = time.perf_counter()

    def step():
        p = min(1.0, (time.perf_counter() - t0) / dur)
        try:
            win.attributes("-alpha", ease(p))
        except Exception:
            return
        if p < 1:
            win.after(16, step)
    step()


FLATS = []
ANIM_ON = [True]


class Flat(tk.Label):
    def __init__(self, master, text, command):
        super().__init__(master, text=text, bg=BG, fg=DIM, font=FONT, padx=14, pady=6, cursor="hand2",
                         highlightthickness=1, highlightbackground=LINE)
        self.command = command
        self.on = False
        self.h = self.ht = self.a = self.at = 0.0
        FLATS.append(self)
        self.bind("<Enter>", lambda e: setattr(self, "ht", 1.0))
        self.bind("<Leave>", lambda e: setattr(self, "ht", 0.0))
        self.bind("<Button-1>", lambda e: self.command())

    def set_on(self, on):
        self.on = on
        self.at = 1.0 if on else 0.0

    def step(self, dt):
        old = (self.h, self.a)
        for attr, tgt in (("h", "ht"), ("a", "at")):
            v, t = getattr(self, attr), getattr(self, tgt)
            if v != t:
                if not ANIM_ON[0]:
                    v = t
                else:
                    d = dt / 0.16
                    v = min(t, v + d) if t > v else max(t, v - d)
                setattr(self, attr, v)
        if old != (self.h, self.a):
            fg = mix(DIM, HOT, self.h)
            bg = BG
            br = mix(LINE, DIM, self.h)
            if self.a > 0:
                fg, bg, br = mix(fg, BG, self.a), mix(BG, HOT, self.a), mix(br, HOT, self.a)
            self.config(fg=fg, bg=bg, highlightbackground=br)


def lab(p, text):
    return tk.Label(p, text=text, bg=BG, fg=DIM, font=FONT, anchor="w")


def ent(p, var, show=None, width=46):
    return tk.Entry(p, textvariable=var, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT,
                    highlightthickness=1, highlightbackground=LINE, highlightcolor=DIM, show=show,
                    width=width)


def chk(p, text, var):
    return tk.Checkbutton(p, text=text, variable=var, bg=BG, fg=FG, selectcolor=BG, activebackground=BG,
                          activeforeground=HOT, font=FONT, bd=0, highlightthickness=0, anchor="w")


def setup_style(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure("TNotebook", background=BG, borderwidth=0)
    s.configure("TNotebook.Tab", background=BG, foreground=DIM, padding=(14, 7), borderwidth=0)
    s.map("TNotebook.Tab", foreground=[("selected", HOT)], background=[("selected", BG)])
    s.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=FG, arrowcolor=DIM,
                bordercolor=LINE, lightcolor=PANEL, darkcolor=PANEL, selectbackground=PANEL,
                selectforeground=FG)
    s.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)])
    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", HOT)
    root.option_add("*TCombobox*Listbox.selectForeground", BG)


class Settings:
    def __init__(self, app):
        self.app = app
        self.cfg = app.cfg
        cfg = self.cfg
        w = self.w = tk.Toplevel(app.root)
        w.title("Настройки")
        w.configure(bg=BG)
        w.geometry("700x720")
        w.transient(app.root)
        nb = ttk.Notebook(w)
        nb.pack(fill="both", expand=True, padx=16, pady=(14, 6))
        self.keys = dict(cfg["keys"])
        self.kv = {p: tk.StringVar(value=self.keys.get(p, "")) for p in list(llmmod.PROVIDERS) + ["groq"]}
        self.models = dict(cfg["models"])
        self.voices = dict(cfg["tts_voices"])
        self.voice_map = {}
        self.cur_provider = cfg["provider"]
        self.cur_engine = cfg["tts_engine"]

        # ----- model tab -----
        t = self.tab(nb, "Модель")
        self.plist = list(llmmod.PROVIDERS.keys())
        self.v_prov = tk.StringVar(value=llmmod.PROVIDERS[cfg["provider"]][0])
        lab(t, "Провайдер").pack(fill="x")
        cb = ttk.Combobox(t, textvariable=self.v_prov, state="readonly", width=60,
                          values=[llmmod.PROVIDERS[k][0] for k in self.plist])
        cb.pack(fill="x", pady=(2, 4))
        cb.bind("<<ComboboxSelected>>", self.on_provider)
        self.note = tk.Label(t, bg=BG, fg=DIM, font=("Segoe UI", 9), justify="left", anchor="w",
                             wraplength=610, text=llmmod.PROVIDERS[self.cur_provider][5])
        self.note.pack(fill="x", pady=(0, 8))
        lab(t, "API ключ (для локальных не нужен)").pack(fill="x")
        krow = tk.Frame(t, bg=BG)
        krow.pack(fill="x", pady=(2, 10))
        self.key_entry = ent(krow, self.kv[self.cur_provider], show="*", width=40)
        self.key_entry.pack(side="left", fill="x", expand=True)
        Flat(krow, "Получить ключ", self.open_key_page).pack(side="left", padx=(8, 0))
        lab(t, "Модель").pack(fill="x")
        row = tk.Frame(t, bg=BG)
        row.pack(fill="x", pady=(2, 10))
        self.v_model = tk.StringVar(value=self.models.get(self.cur_provider)
                                    or llmmod.PROVIDERS[self.cur_provider][2])
        self.cb_model = ttk.Combobox(row, textvariable=self.v_model, width=50,
                                     values=llmmod.PROVIDERS[self.cur_provider][4])
        self.cb_model.pack(side="left", fill="x", expand=True)
        Flat(row, "Список", self.fetch_models).pack(side="left", padx=(8, 0))
        lab(t, "Адрес API (только для своего API)").pack(fill="x")
        self.v_base = tk.StringVar(value=cfg["base_url"])
        ent(t, self.v_base).pack(fill="x", pady=(2, 10))
        self.v_vis = tk.BooleanVar(value=cfg["vision_enabled"])
        chk(t, "Включить vision (модель видит экран)", self.v_vis).pack(fill="x")
        lab(t, "Vision модель (пусто = основная). Кнопка Список покажет модели с картинками").pack(
            fill="x", pady=(8, 0))
        self.v_vmodel = tk.StringVar(value=cfg["vision_model"])
        ent(t, self.v_vmodel).pack(fill="x", pady=(2, 10))
        lab(t, "Имя ассистента").pack(fill="x")
        self.v_name = tk.StringVar(value=cfg["name"])
        ent(t, self.v_name, width=20).pack(anchor="w", pady=(2, 0))

        # ----- local tab -----
        t = self.tab(nb, "Локальная ИИ")
        self.busy = False
        tk.Label(t, bg=BG, fg=FG, font=FONT, justify="left", anchor="w", wraplength=620,
                 text="Быстрый старт: выберите модель и нажмите Скачать и настроить. Программа сама скачает "
                      "llama.cpp и модель, пропишет пути и переключится на локальную ИИ. Интернет нужен "
                      "только для загрузки. Для старых ПК берите модель 1B-1.5B.").pack(fill="x", pady=(0, 10))
        self.v_lib = tk.StringVar(value=cfg["llama_lib"])
        self.v_gguf = tk.StringVar(value=cfg["llama_model"])
        self.v_mm = tk.StringVar(value=cfg["llama_mmproj"])
        self.v_thr = tk.StringVar(value=str(cfg["threads"]))
        self.v_ctx = tk.StringVar(value=str(cfg["ctx"]))
        row = tk.Frame(t, bg=BG)
        row.pack(fill="x")
        self.v_lm = tk.StringVar(value=localsetup.MODELS[0][0])
        ttk.Combobox(row, textvariable=self.v_lm, state="readonly", width=48,
                     values=[m[0] for m in localsetup.MODELS]).pack(side="left", fill="x", expand=True)
        Flat(row, "Скачать и настроить", self.install_local).pack(side="left", padx=(8, 0))
        self.pb = tk.Canvas(t, bg=PANEL, height=4, highlightthickness=0, bd=0)
        self.pb.pack(fill="x", pady=(10, 4))
        self.pb_fill = self.pb.create_rectangle(0, 0, 0, 4, fill=HOT, outline="")
        self.pb_text = tk.Label(t, bg=BG, fg=DIM, font=("Segoe UI", 9), anchor="w", text=self.local_status())
        self.pb_text.pack(fill="x", pady=(0, 12))
        brow = tk.Frame(t, bg=BG)
        brow.pack(fill="x", pady=(0, 12))
        Flat(brow, "Запустить", self.start_local).pack(side="left")
        Flat(brow, "Остановить", self.stop_local).pack(side="left", padx=8)
        self.l_run = tk.Label(brow, bg=BG, fg=DIM, font=("Segoe UI", 9), anchor="w", justify="left",
                              wraplength=380, text=self.run_status())
        self.l_run.pack(side="left", padx=(6, 0))
        tk.Frame(t, bg=LINE, height=1).pack(fill="x", pady=(0, 10))
        lab(t, "Вручную, если файлы уже есть:").pack(fill="x", pady=(0, 6))
        self.pick(t, "llama-server.exe или llama.dll", self.v_lib, [("llama", "*.exe *.dll")])
        self.pick(t, "Модель .gguf", self.v_gguf, [("gguf", "*.gguf")])
        self.pick(t, "Vision проектор mmproj .gguf (только для локального vision)", self.v_mm, [("gguf", "*.gguf")])
        prow = tk.Frame(t, bg=BG)
        prow.pack(fill="x")
        lab(prow, "Потоки CPU (0 = авто)   ").pack(side="left")
        ent(prow, self.v_thr, width=6).pack(side="left")
        lab(prow, "      Контекст   ").pack(side="left")
        ent(prow, self.v_ctx, width=8).pack(side="left")

        # ----- voice tab -----
        t = self.tab(nb, "Голос")
        self.v_tts_on = tk.BooleanVar(value=cfg["tts_enabled"])
        chk(t, "Озвучивать ответы", self.v_tts_on).pack(fill="x")
        lab(t, "Движок").pack(fill="x", pady=(8, 0))
        self.elist = [k for k, _ in ttsmod.ENGINES]
        self.v_eng = tk.StringVar(value=dict(ttsmod.ENGINES)[cfg["tts_engine"]])
        cb = ttk.Combobox(t, textvariable=self.v_eng, state="readonly", width=60,
                          values=[v for _, v in ttsmod.ENGINES])
        cb.pack(fill="x", pady=(2, 8))
        cb.bind("<<ComboboxSelected>>", self.on_engine)
        lab(t, "Голос").pack(fill="x")
        self.v_voice = tk.StringVar(value=self.voices.get(self.cur_engine, ""))
        self.cb_voice = ttk.Combobox(t, textvariable=self.v_voice, width=60)
        self.cb_voice.pack(fill="x", pady=(2, 6))
        row = tk.Frame(t, bg=BG)
        row.pack(fill="x", pady=(0, 8))
        self.v_vq = tk.StringVar()
        ent(row, self.v_vq, width=24).pack(side="left")
        Flat(row, "Загрузить / найти голоса", self.fetch_voices).pack(side="left", padx=8)
        Flat(row, "Проверить", self.test_voice).pack(side="left")
        lab(t, "Fish Audio API ключ").pack(fill="x")
        self.v_fish = tk.StringVar(value=self.keys.get("fish", ""))
        ent(t, self.v_fish, show="*").pack(fill="x", pady=(2, 8))
        lab(t, "ElevenLabs API ключ").pack(fill="x")
        self.v_el = tk.StringVar(value=self.keys.get("elevenlabs", ""))
        ent(t, self.v_el, show="*").pack(fill="x", pady=(2, 8))
        lab(t, "Скорость речи (проценты)").pack(fill="x")
        self.v_rate = tk.IntVar(value=cfg["tts_rate"])
        tk.Scale(t, from_=-50, to=50, resolution=10, orient="horizontal", variable=self.v_rate, bg=BG,
                 fg=DIM, troughcolor=PANEL, highlightthickness=0, bd=0, length=240,
                 activebackground=HOT).pack(anchor="w")

        # ----- stt tab -----
        t = self.tab(nb, "Распознавание")
        lab(t, "Движок распознавания речи").pack(fill="x")
        self.v_stt = tk.StringVar(value=dict(STT_ENGINES)[cfg["stt_engine"]])
        ttk.Combobox(t, textvariable=self.v_stt, state="readonly", width=60,
                     values=[v for _, v in STT_ENGINES]).pack(fill="x", pady=(2, 10))
        lab(t, "Groq API ключ (для Whisper и для модели Groq)").pack(fill="x")
        ent(t, self.kv["groq"], show="*").pack(fill="x", pady=(2, 10))
        self.v_vosk = tk.StringVar(value=cfg["vosk_path"])
        row = self.pick(t, "Папка модели Vosk (офлайн)", self.v_vosk, None, folder=True)
        lab(t, "Язык").pack(fill="x")
        self.v_lang = tk.StringVar(value=cfg["lang"])
        ttk.Combobox(t, textvariable=self.v_lang, state="readonly", values=["ru", "en"], width=8).pack(
            anchor="w", pady=(2, 10))
        lab(t, "Микрофон").pack(fill="x")
        self.mics = [("По умолчанию", -1)]
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0:
                    self.mics.append(("%d  %s" % (i, d["name"]), i))
        except Exception:
            pass
        cur = [n for n, i in self.mics if i == cfg["mic"]]
        self.v_mic = tk.StringVar(value=cur[0] if cur else self.mics[0][0])
        ttk.Combobox(t, textvariable=self.v_mic, state="readonly", width=60,
                     values=[n for n, _ in self.mics]).pack(fill="x", pady=(2, 10))
        self.v_wake = tk.BooleanVar(value=cfg["wake"])
        chk(t, "Активация голосом: сначала скажите имя (Нова), потом команду", self.v_wake).pack(fill="x")
        self.v_auto = tk.BooleanVar(value=cfg["autolisten"])
        chk(t, "Слушать сразу при запуске", self.v_auto).pack(fill="x")
        lab(t, "Ответ на имя").pack(fill="x", pady=(8, 0))
        self.v_ack = tk.StringVar(value=cfg["ack"])
        ent(t, self.v_ack, width=30).pack(anchor="w", pady=(2, 0))

        # ----- behaviour tab -----
        self.fields = []
        t = self.tab(nb, "Поведение")
        self.field(t, "Характер", "persona", opts=[("friend", "Друг"), ("strict", "Строгий"),
                                                    ("funny", "Весёлый"), ("butler", "Дворецкий")])
        self.field(t, "Как обращаться к вам", "owner")
        self.field(t, "Тихий режим (отвечать только текстом)", "quiet", "bool")
        self.field(t, "Перебивать голосом (лучше в наушниках)", "interrupt", "bool")
        self.field(t, "Режим диалога: после имени слушать 30 секунд без повторения", "converse", "bool")
        self.field(t, "Спрашивать подтверждение опасных действий", "confirm", "bool")
        self.field(t, "Подсказывать привычные действия", "proactive", "bool")
        self.field(t, "Утренняя сводка (погода, дела, новости)", "brief_on", "bool")
        self.field(t, "Время сводки, ЧЧ:ММ", "brief_time")
        self.field(t, "Значок в трее", "tray", "bool")
        self.field(t, "Закрытие окна сворачивает в трей", "close_to_tray", "bool")
        self.field(t, "Запускать вместе с Windows", "autostart", "bool")
        self.field(t, "Горячая клавиша вызова, например ctrl+alt+n", "hotkey")

        # ----- integrations tab -----
        t = self.tab(nb, "Интеграции")
        self.field(t, "Город для погоды (пусто = определить по IP)", "city")
        self.field(t, "Музыка по команде включи музыку", "music",
                   opts=[("youtube", "YouTube"), ("ytmusic", "YouTube Music"), ("spotify", "Spotify")])
        self.field(t, "Telegram: токен бота (от BotFather)", "tg_token")
        self.field(t, "Telegram: ваш chat id", "tg_chat")
        self.field(t, "Home Assistant: адрес, например http://192.168.1.5:8123", "ha_url")
        self.field(t, "Home Assistant: долгоживущий токен", "ha_token")
        Flat(t, "Открыть папку плагинов", self.open_plugins).pack(anchor="w", pady=(14, 0))

        # ----- council tab -----
        t = self.tab(nb, "Совет ИИ")
        tk.Label(t, bg=BG, fg=DIM, font=("Segoe UI", 9), justify="left", anchor="w", wraplength=620,
                 text="Несколько моделей отвечают одновременно, а главная собирает из их ответов лучший. "
                      "Отметьте участников и вставьте ключи. Бесплатные: Groq, Gemini, OpenRouter, Cerebras и "
                      "другие. Claude, GPT и Grok требуют платный ключ.").pack(fill="x", pady=(0, 6))
        self.field(t, "Режим", "council_mode",
                   opts=[("off", "Выключен"), ("auto", "Авто: сложные вопросы обсуждают все модели"),
                         ("always", "Всегда: каждый ответ обсуждают все модели"),
                         ("race", "Гонка: отвечает самая быстрая")])
        self.field(t, "Если модель недоступна, переключаться на другую", "fallback", "bool")
        self.csel = {}
        for p in ("groq", "gemini", "openrouter", "cerebras", "mistral", "nvidia", "zai", "github", "deepseek",
                  "openai", "anthropic", "xai"):
            row = tk.Frame(t, bg=BG)
            row.pack(fill="x", pady=1)
            self.csel[p] = tk.BooleanVar(value=(p in cfg["council"]))
            chk(row, llmmod.PROVIDERS[p][0].split(" (")[0], self.csel[p]).pack(side="left")
            ent(row, self.kv[p], show="*", width=36).pack(side="right")

        # ----- system tab -----
        t = self.tab(nb, "Система")
        self.v_lite = tk.BooleanVar(value=cfg["lite"])
        chk(t, "Лёгкий режим для старых процессоров (короткие ответы, меньше контекст)", self.v_lite).pack(fill="x")
        lab(t, "Сообщений в памяти диалога").pack(fill="x", pady=(10, 0))
        self.v_hist = tk.StringVar(value=str(cfg["history"]))
        ent(t, self.v_hist, width=8).pack(anchor="w", pady=(2, 10))
        lab(t, "Максимум токенов ответа").pack(fill="x")
        self.v_tok = tk.StringVar(value=str(cfg["max_tokens"]))
        ent(t, self.v_tok, width=8).pack(anchor="w", pady=(2, 10))
        lab(t, "Свои программы: по строке  название=путь к exe").pack(fill="x")
        self.apps = tk.Text(t, height=6, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT,
                            highlightthickness=1, highlightbackground=LINE)
        self.apps.insert("1.0", cfg["custom_apps"])
        self.apps.pack(fill="x", pady=(2, 0))

        bar = tk.Frame(w, bg=BG)
        bar.pack(fill="x", padx=16, pady=(0, 14))
        Flat(bar, "Сохранить", self.save).pack(side="right")
        Flat(bar, "Закрыть", w.destroy).pack(side="right", padx=8)
        Flat(bar, "Проверить ИИ", self.test_llm).pack(side="left")
        if not cfg["lite"]:
            fade_window(w, 0.25)

    def field(self, t, label, key, kind="str", opts=None):
        if kind == "bool":
            v = tk.BooleanVar(value=bool(self.cfg[key]))
            chk(t, label, v).pack(fill="x")
        else:
            cur = self.cfg[key]
            show = next((l for o, l in opts if o == cur), str(cur)) if opts else str(cur)
            v = tk.StringVar(value=show)
            lab(t, label).pack(fill="x", pady=(6, 0))
            if opts:
                ttk.Combobox(t, textvariable=v, state="readonly", width=60,
                             values=[l for _, l in opts]).pack(fill="x", pady=(2, 2))
            else:
                ent(t, v, width=50).pack(fill="x", pady=(2, 2))
        self.fields.append((key, v, kind, opts))

    def open_plugins(self):
        from . import plugins
        os.startfile(plugins.plugins_dir())

    def tab(self, nb, title):
        f = tk.Frame(nb, bg=BG, padx=14, pady=14)
        nb.add(f, text=title)
        return f

    def pick(self, parent, title, var, types, folder=False):
        lab(parent, title).pack(fill="x")
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(2, 10))
        ent(row, var, width=52).pack(side="left", fill="x", expand=True)

        def browse():
            p = filedialog.askdirectory() if folder else filedialog.askopenfilename(filetypes=types)
            if p:
                var.set(p)
        Flat(row, "Обзор", browse).pack(side="left", padx=(8, 0))

    # ----- handlers -----
    def prov_key(self):
        lbl = self.v_prov.get()
        for k in self.plist:
            if llmmod.PROVIDERS[k][0] == lbl:
                return k
        return self.cur_provider

    def eng_key(self):
        lbl = self.v_eng.get()
        for k, v in ttsmod.ENGINES:
            if v == lbl:
                return k
        return self.cur_engine

    def on_provider(self, _e=None):
        self.models[self.cur_provider] = self.v_model.get().strip()
        self.cur_provider = self.prov_key()
        self.key_entry.config(textvariable=self.kv[self.cur_provider])
        self.v_model.set(self.models.get(self.cur_provider) or llmmod.PROVIDERS[self.cur_provider][2])
        self.cb_model["values"] = llmmod.PROVIDERS[self.cur_provider][4]
        self.note.config(text=llmmod.PROVIDERS[self.cur_provider][5])

    def open_key_page(self):
        url = llmmod.PROVIDERS[self.prov_key()][3]
        if url:
            webbrowser.open(url)

    def local_status(self):
        srv = localsetup.find_server() or (self.cfg["llama_lib"] if self.cfg["llama_lib"] else "")
        mdl = self.cfg["llama_model"]
        return "llama.cpp: %s   |   модель: %s" % ("готова" if srv else "не установлена",
                                                  os.path.basename(mdl) if mdl else "не выбрана")

    def run_status(self):
        return "Работает, модель готова" if self.app.agent.llm.local_running() else "Остановлена"

    def start_local(self):
        if self.busy:
            return
        if not self.v_lib.get().strip():
            self.v_lib.set(localsetup.find_server())
        if not self.v_gguf.get().strip():
            self.v_gguf.set(localsetup.find_model())
        if not self.v_lib.get().strip() or not self.v_gguf.get().strip():
            messagebox.showinfo("Локальная ИИ", "Сначала нажмите Скачать и настроить или укажите файлы вручную",
                                parent=self.w)
            return
        self.v_prov.set(llmmod.PROVIDERS["local"][0])
        self.on_provider()
        self.save(close=False)
        self.busy = True
        self.l_run.config(text="Запускаю, подождите (для большой модели до нескольких минут)")
        llm = self.app.agent.llm

        def work():
            try:
                llm.start_local()
                err = None
            except Exception as e:
                err = e
            self.app.root.after(0, lambda: self.run_done(err))
        threading.Thread(target=work, daemon=True).start()

    def run_done(self, err):
        self.busy = False
        try:
            if err:
                self.l_run.config(text="Ошибка запуска")
                messagebox.showerror("Локальная ИИ", str(err), parent=self.w)
            else:
                self.l_run.config(text="Работает, модель готова. Можно писать в чат")
                self.app.sys_msg("Локальная модель запущена")
        except tk.TclError:
            pass

    def stop_local(self):
        self.app.agent.llm.stop_local()
        self.l_run.config(text="Остановлена")

    def test_llm(self):
        self.save(close=False)
        self.app.sys_msg("Проверяю подключение к ИИ")
        llm = self.app.agent.llm

        def work():
            try:
                out = "".join(llm.stream([{"role": "user", "content": "Reply with one short word: ok"}])).strip()
                res, err = out, None
            except Exception as e:
                res, err = None, e

            def show():
                try:
                    if err:
                        messagebox.showerror("Проверка ИИ", str(err), parent=self.app.root)
                    else:
                        messagebox.showinfo("Проверка ИИ", "Работает. Ответ модели: %s" % res[:200],
                                            parent=self.app.root)
                except tk.TclError:
                    pass
            self.app.root.after(0, show)
        threading.Thread(target=work, daemon=True).start()

    def set_prog(self, done, total, text):
        try:
            w = max(1, self.pb.winfo_width())
            self.pb.coords(self.pb_fill, 0, 0, w * (done / float(total) if total else 0), 4)
            self.pb_text.config(text=text)
        except tk.TclError:
            pass

    def install_local(self):
        if self.busy:
            return
        idx = [m[0] for m in localsetup.MODELS].index(self.v_lm.get())
        self.busy = True
        last = [0.0]

        def prog(done, total, text):
            now = time.time()
            if now - last[0] < 0.1 and done < total:
                return
            last[0] = now
            self.app.root.after(0, lambda: self.set_prog(done, total, text))

        def work():
            try:
                srv = localsetup.install_llama(prog)
                mdl, mm = localsetup.install_model(idx, prog)
                res, err = (srv, mdl, mm), None
            except Exception as e:
                res, err = None, e
            self.app.root.after(0, lambda: self.local_done(res, err, localsetup.MODELS[idx][2]))
        threading.Thread(target=work, daemon=True).start()

    def local_done(self, res, err, vision):
        self.busy = False
        try:
            if err:
                self.set_prog(0, 1, "Ошибка: %s" % err)
                messagebox.showerror("Локальная ИИ", str(err), parent=self.w)
                return
            srv, mdl, mm = res
            self.v_lib.set(srv)
            self.v_gguf.set(mdl)
            self.v_mm.set(mm)
            if vision:
                self.v_vis.set(True)
            self.v_prov.set(llmmod.PROVIDERS["local"][0])
            self.on_provider()
            self.save(close=False)
            self.set_prog(1, 1, "Готово. Локальная ИИ включена, можно писать в чат")
        except tk.TclError:
            pass

    def on_engine(self, _e=None):
        self.voices[self.cur_engine] = self.voice_map.get(self.v_voice.get(), self.v_voice.get())
        self.cur_engine = self.eng_key()
        self.v_voice.set(self.voices.get(self.cur_engine, ""))
        self.cb_voice["values"] = []
        self.voice_map = {}

    def bg(self, fn, done):
        def run():
            try:
                r = fn()
                self.app.root.after(0, lambda: done(r, None))
            except Exception as e:
                self.app.root.after(0, lambda: done(None, e))
        threading.Thread(target=run, daemon=True).start()

    def fetch_models(self):
        p = self.cur_provider = self.prov_key()
        key, base = self.kv[p].get().strip(), self.v_base.get().strip()

        def done(r, e):
            if e:
                messagebox.showerror("Модели", str(e), parent=self.w)
            else:
                self.cb_model["values"] = r
        self.bg(lambda: llmmod.list_models(self.cfg, p, base, key), done)

    def fetch_voices(self):
        self.apply_keys()
        eng = self.cur_engine = self.eng_key()

        def done(r, e):
            if e:
                messagebox.showerror("Голоса", str(e), parent=self.w)
                return
            self.voice_map = dict(r)
            self.cb_voice["values"] = [l for l, _ in r]
            if r:
                self.v_voice.set(r[0][0])
        self.bg(lambda: ttsmod.list_voices(eng, self.cfg, self.v_vq.get()), done)

    def apply_keys(self):
        for p, v in self.kv.items():
            self.keys[p] = v.get().strip()
        self.keys["fish"] = self.v_fish.get().strip()
        self.keys["elevenlabs"] = self.v_el.get().strip()
        self.cfg["keys"] = dict(self.keys)

    def test_voice(self):
        self.save(close=False)
        self.app.agent.tts.say("Привет. Это проверка голоса." if self.cfg["lang"] == "ru"
                               else "Hello. This is a voice test.")

    def num(self, var, default):
        try:
            return int(var.get())
        except Exception:
            return default

    def save(self, close=True):
        cfg = self.cfg
        self.apply_keys()
        self.models[self.cur_provider] = self.v_model.get().strip()
        self.voices[self.cur_engine] = self.voice_map.get(self.v_voice.get(), self.v_voice.get()).strip()
        cfg["provider"] = self.prov_key()
        cfg["models"] = dict(self.models)
        cfg["base_url"] = self.v_base.get().strip()
        cfg["vision_enabled"] = self.v_vis.get()
        cfg["vision_model"] = self.v_vmodel.get().strip()
        cfg["name"] = self.v_name.get().strip().lower() or "нова"
        cfg["llama_lib"] = self.v_lib.get().strip()
        cfg["llama_model"] = self.v_gguf.get().strip()
        cfg["llama_mmproj"] = self.v_mm.get().strip()
        cfg["threads"] = self.num(self.v_thr, 0)
        cfg["ctx"] = self.num(self.v_ctx, 2048)
        cfg["tts_enabled"] = self.v_tts_on.get()
        cfg["tts_engine"] = self.eng_key()
        cfg["tts_voices"] = dict(self.voices)
        cfg["tts_rate"] = self.v_rate.get()
        cfg["stt_engine"] = next((k for k, v in STT_ENGINES if v == self.v_stt.get()), "google")
        cfg["vosk_path"] = self.v_vosk.get().strip()
        cfg["lang"] = self.v_lang.get()
        cfg["mic"] = dict(self.mics).get(self.v_mic.get(), -1)
        for key, v, kind, opts in self.fields:
            if kind == "bool":
                cfg[key] = v.get()
            elif opts:
                cfg[key] = next((o for o, l in opts if l == v.get()), cfg[key])
            else:
                cfg[key] = v.get().strip()
        cfg["council"] = [p for p, v in self.csel.items() if v.get()]
        cfg["wake"] = self.v_wake.get()
        cfg["autolisten"] = self.v_auto.get()
        cfg["ack"] = self.v_ack.get().strip() or "Да, хозяин"
        cfg["lite"] = self.v_lite.get()
        cfg["history"] = self.num(self.v_hist, 8)
        cfg["max_tokens"] = self.num(self.v_tok, 300)
        cfg["custom_apps"] = self.apps.get("1.0", "end").strip()
        cfg.save()
        self.app.agent.reload()
        self.app.apply_system()
        self.app.sys_msg("Настройки сохранены")
        if close:
            self.w.destroy()


KINDS = {
    "who": (DIM, ("Segoe UI", 9)),
    "user": ("#a0a0a0", ("Segoe UI", 11)),
    "bot": (FG, ("Segoe UI", 11)),
    "sys": (DIM, ("Segoe UI", 9, "italic")),
    "err": ("#c25b5b", ("Segoe UI", 9)),
}
ORB = {"awake": (0.22, 0.85), "idle": (0.06, 0.35), "listening": (0.14, 0.55), "hearing": (0.2, 0.95),
       "recognizing": (0.12, 0.8), "thinking": (0.12, 0.8), "speaking": (0.5, 1.0)}
NBARS = 56
RAD = 34
OH = 150


class App:
    def __init__(self):
        self.cfg = Config()
        self.q = queue.Queue()
        self.root = tk.Tk()
        self.root.title("Nova")
        self.root.geometry("780x640")
        self.root.minsize(560, 480)
        self.root.configure(bg=BG)
        try:
            self.root.iconbitmap(default=resource_path("assets/icon.ico"))
        except Exception:
            pass
        setup_style(self.root)
        self.agent = Agent(self.cfg, self.q.put)
        self.bot_open = False
        self.n = 0
        self.fades = []
        self.stick = False
        self.amp = 0.06
        self.br = 0.35
        self.arcv = 0.0
        self.t = 0.0
        self.cx = 390
        self.ef = self.eft = 0.0
        self.st_cur = ""
        self.st_alpha = 0.0
        self.last = time.perf_counter()
        self.build()
        self.tray = None
        self.hk = Hotkey()
        self.apply_system()
        if "--tray" in sys.argv and self.tray:
            self.root.withdraw()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if not self.cfg["setup_done"]:
            self.sys_msg("Нажмите Настройка: всё установится одной кнопкой.")
            self.root.after(900, self.open_wizard)
        else:
            self.sys_msg("Скажите: Нова, привет, открой ютуб. Или напишите команду.")
            if self.cfg["autolisten"]:
                self.root.after(700, self.start_listening)
        if not self.cfg["lite"]:
            fade_window(self.root, 0.45)
        self.pump()
        self.tick()

    def build(self):
        r = self.root
        top = tk.Frame(r, bg=BG)
        top.pack(fill="x", padx=24, pady=(18, 0))
        tk.Label(top, text="N O V A", bg=BG, fg=HOT, font=("Segoe UI", 12, "bold")).pack(side="left")
        self.state = tk.Label(top, text="", bg=BG, fg=DIM, font=FONT)
        self.state.pack(side="right")
        self.cv = tk.Canvas(r, bg=BG, height=OH, highlightthickness=0, bd=0)
        self.cv.pack(fill="x", padx=24)
        self.cv.bind("<Configure>", lambda e: setattr(self, "cx", e.width / 2))
        self.angles = [(2 * math.pi * i / NBARS - math.pi / 2) for i in range(NBARS)]
        self.cos = [math.cos(a) for a in self.angles]
        self.sin = [math.sin(a) for a in self.angles]
        cy = OH / 2
        self.bars = [self.cv.create_line(0, 0, 0, 0, width=2, capstyle="round", fill=BG, tags="bar")
                     for _ in range(NBARS)]
        self.ring = self.cv.create_oval(0, 0, 0, 0, outline=BG, width=1)
        self.core = self.cv.create_oval(0, 0, 0, 0, outline="", fill=BG)
        self.arc = self.cv.create_arc(0, 0, 0, 0, start=0, extent=80, style="arc", outline=BG, width=2)
        self.cy = cy
        tk.Frame(r, bg=LINE, height=1).pack(fill="x", padx=24)
        mid = tk.Frame(r, bg=BG)
        mid.pack(fill="both", expand=True, padx=24, pady=12)
        self.chat = tk.Text(mid, bg=BG, fg=FG, font=("Segoe UI", 11), relief="flat", wrap="word",
                            state="disabled", highlightthickness=0, spacing3=8, cursor="arrow",
                            selectbackground="#2a2a2a")
        self.chat.pack(fill="both", expand=True)
        tk.Frame(r, bg=LINE, height=1).pack(fill="x", padx=24)
        bot = tk.Frame(r, bg=BG)
        bot.pack(fill="x", padx=24, pady=14)
        self.var = tk.StringVar()
        self.entry = tk.Entry(bot, textvariable=self.var, bg=BG, fg=HOT, insertbackground=HOT, relief="flat",
                              font=("Segoe UI", 11), highlightthickness=1, highlightbackground=LINE,
                              highlightcolor=LINE)
        self.entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 10))
        self.entry.bind("<Return>", lambda ev: self.send())
        self.entry.bind("<FocusIn>", lambda ev: setattr(self, "eft", 1.0))
        self.entry.bind("<FocusOut>", lambda ev: setattr(self, "eft", 0.0))
        self.entry.focus_set()
        self.mic = Flat(bot, "Слушать", self.toggle_mic)
        self.mic.pack(side="left")
        Flat(bot, "Стоп", self.agent.stop).pack(side="left", padx=8)
        Flat(bot, "Настройка", self.open_wizard).pack(side="left")

    def open_wizard(self):
        from .wizard import Wizard
        w = getattr(self, "wiz", None)
        if w is not None:
            try:
                if w.w.winfo_exists():
                    w.w.lift()
                    return
            except tk.TclError:
                pass
        self.wiz = Wizard(self)

    def start_listening(self):
        if not self.agent.listener.running:
            self.toggle_mic()

    def send(self):
        t = self.var.get().strip()
        if t:
            self.var.set("")
            self.agent.submit(t)

    def toggle_mic(self):
        on = not self.agent.listener.running
        self.agent.set_listening(on)
        self.mic.set_on(on)
        self.mic.config(text="Слушаю" if on else "Слушать")

    # ----- chat -----
    def add(self, text, kind):
        c = self.chat
        self.stick = self.stick or c.yview()[1] >= 0.97
        c.config(state="normal")
        self.n += 1
        tag = "m%d" % self.n
        color, font = KINDS[kind]
        if ANIM_ON[0]:
            c.tag_configure(tag, foreground=BG, font=font)
            self.fades.append((tag, color, time.perf_counter(), 0.45))
        else:
            c.tag_configure(tag, foreground=color, font=font)
        c.insert("end", text, tag)
        c.config(state="disabled")

    def sys_msg(self, t):
        self.close_bot()
        self.add(t + "\n", "sys")

    def close_bot(self):
        if self.bot_open:
            self.add("\n", "bot")
            self.bot_open = False

    def handle(self, kind, val):
        if kind == "user":
            self.close_bot()
            self.add("ты   ", "who")
            self.add(val + "\n", "user")
        elif kind == "bot":
            if not self.bot_open:
                self.add("нова   ", "who")
                self.bot_open = True
            self.add(val, "bot")
        elif kind == "bot_end":
            self.close_bot()
        elif kind == "sys":
            self.sys_msg(val)
        elif kind == "error":
            self.close_bot()
            self.add(val + "\n", "err")

    def pump(self):
        try:
            while True:
                self.handle(*self.q.get_nowait())
        except queue.Empty:
            pass
        if not self.agent.listener.running and self.mic.on:
            self.mic.set_on(False)
            self.mic.config(text="Слушать")
        self.root.after(60, self.pump)

    # ----- animation -----
    def tick(self):
        now = time.perf_counter()
        dt = min(0.1, now - self.last)
        self.last = now
        anim = not self.cfg["lite"]
        ANIM_ON[0] = anim
        for f in list(FLATS):
            try:
                f.step(dt)
            except tk.TclError:
                FLATS.remove(f)
        self.orb_step(dt, anim)
        self.fade_step(now)
        self.state_step(dt, anim)
        self.scroll_step(anim)
        if self.ef != self.eft:
            d = dt / 0.2
            self.ef = min(self.eft, self.ef + d) if self.eft > self.ef else max(self.eft, self.ef - d)
            c = mix(LINE, "#8a8a8a", self.ef)
            self.entry.config(highlightbackground=c, highlightcolor=c)
        self.root.after(33 if anim else 150, self.tick)

    def orb_step(self, dt, anim):
        key = self.agent.state_key()
        ta, tb = ORB.get(key, ORB["idle"])
        if key == "hearing":
            ta = 0.15 + 0.85 * self.agent.listener.level
        k = 1 - math.exp(-dt * 8) if anim else 1.0
        self.amp += (ta - self.amp) * k
        self.br += (tb - self.br) * k
        think = 1.0 if key in ("thinking", "recognizing") else 0.0
        self.arcv += (think - self.arcv) * k
        if anim:
            self.t += dt
        t = self.t
        cx, cy = self.cx, self.cy
        fast = 3.2 if key == "speaking" else 1.6
        breath = 0.5 + 0.5 * math.sin(t * 1.6)
        for i, ln in enumerate(self.bars):
            w = 0.5 + 0.5 * math.sin(t * fast + i * 0.65) * math.sin(t * 1.1 + i * 0.23 + 1.0)
            length = 3 + self.amp * 26 * (w if anim else 0.6) + breath * 2.5 * (1 - self.amp)
            r0 = RAD + 8
            self.cv.coords(ln, cx + self.cos[i] * r0, cy + self.sin[i] * r0,
                           cx + self.cos[i] * (r0 + length), cy + self.sin[i] * (r0 + length))
        self.cv.itemconfig("bar", fill=mix(BG, HOT, self.br))
        rr = RAD + 2 + breath * 1.5 + self.amp * 3
        self.cv.coords(self.ring, cx - rr, cy - rr, cx + rr, cy + rr)
        self.cv.itemconfig(self.ring, outline=mix(BG, "#5a5a5a", self.br))
        cr = RAD - 10 + breath * 2 + self.amp * 5
        self.cv.coords(self.core, cx - cr, cy - cr, cx + cr, cy + cr)
        self.cv.itemconfig(self.core, fill=mix("#0c0c0c", HOT, self.br * 0.9))
        ar = RAD + 16
        self.cv.coords(self.arc, cx - ar, cy - ar, cx + ar, cy + ar)
        self.cv.itemconfig(self.arc, start=(t * 240) % 360, outline=mix(BG, HOT, self.arcv))

    def fade_step(self, now):
        keep = []
        for tag, color, t0, dur in self.fades:
            p = (now - t0) / dur
            self.chat.tag_configure(tag, foreground=mix(BG, color, ease(p)))
            if p < 1:
                keep.append((tag, color, t0, dur))
        self.fades = keep

    def state_step(self, dt, anim):
        want = STATES.get(self.agent.state_key(), "")
        if not anim:
            self.st_cur, self.st_alpha = want, 1.0
        elif want != self.st_cur:
            self.st_alpha -= dt / 0.12
            if self.st_alpha <= 0:
                self.st_cur, self.st_alpha = want, 0.0
        else:
            self.st_alpha = min(1.0, self.st_alpha + dt / 0.2)
        base = "#8a8a8a" if self.st_cur == STATES["idle"] else HOT
        self.state.config(text=self.st_cur, fg=mix(BG, base, self.st_alpha))

    def scroll_step(self, anim):
        if not self.stick:
            return
        first, last = self.chat.yview()
        rem = 1.0 - last
        if rem < 0.002:
            self.chat.yview_moveto(1.0)
            self.stick = False
        else:
            self.chat.yview_moveto(first + rem * (0.3 if anim else 1.0))

    def apply_system(self):
        cfg = self.cfg
        if cfg["tray"] and not self.tray:
            self.tray = start_tray(self)
        elif not cfg["tray"] and self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
            self.tray = None
        self.hk.stop()
        if cfg["hotkey"]:
            self.hk.start(cfg["hotkey"], lambda: self.root.after(0, self.on_hotkey))
        try:
            pc.set_autostart(bool(cfg["autostart"]))
        except Exception:
            pass

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def on_hotkey(self):
        self.show()
        self.agent.wake_now()
        self.start_listening()
        self.sys_msg("Слушаю вас")

    def toggle_quiet(self):
        self.cfg["quiet"] = not self.cfg["quiet"]
        self.cfg.save()
        if self.cfg["quiet"]:
            self.agent.tts.stop()
        self.sys_msg("Тихий режим включён" if self.cfg["quiet"] else "Голос включён")

    def close(self):
        if self.cfg["tray"] and self.cfg["close_to_tray"] and self.tray:
            self.root.withdraw()
        else:
            self.quit()

    def quit(self):
        try:
            self.hk.stop()
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        try:
            self.agent.close()
        finally:
            self.root.destroy()

    def run(self):
        self.root.mainloop()
