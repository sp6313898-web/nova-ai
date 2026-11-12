import math
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import ttk

from . import llm as llmmod
from . import localsetup
from .ui import BG, DIM, FG, HOT, LINE, PANEL, Flat, fade_window, mix

CLOUD = ["groq", "openrouter", "gemini", "cerebras", "mistral", "nvidia", "github", "zai"]
VOICES = [("Светлана, женский", "ru-RU-SvetlanaNeural"), ("Дмитрий, мужской", "ru-RU-DmitryNeural"),
          ("Aria, English", "en-US-AriaNeural"), ("Guy, English", "en-US-GuyNeural")]
STEPS = [("Слух", "Распознавание речи (Vosk, офлайн)"), ("Мозг", "Искусственный интеллект"),
         ("Голос", "Озвучка ответов")]
ERR = "#c25b5b"


class Wizard:
    W = 556

    def __init__(self, app):
        self.app = app
        self.cfg = app.cfg
        self.busy = False
        self.st = [0, 0, 0]
        self.vis = [0.0, 0.0, 0.0]
        self.active = 0
        self.msg_short = ""
        self.target = self.cur = 0.0
        self.base = self.span = 0.0
        self.t = 0.0
        self.voice = VOICES[0][1]
        self.last = time.perf_counter()
        w = self.w = tk.Toplevel(app.root)
        w.title("Быстрая настройка")
        w.configure(bg=BG)
        w.geometry("620x720")
        w.resizable(False, False)
        w.transient(app.root)
        body = tk.Frame(w, bg=BG, padx=32, pady=24)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="Быстрая настройка", bg=BG, fg=HOT, font=("Segoe UI", 17, "bold")).pack(anchor="w")
        tk.Label(body, text="Нажмите одну кнопку. Потом просто говорите: Нова, привет, открой ютуб.",
                 bg=BG, fg=DIM, font=("Segoe UI", 10), wraplength=540, justify="left").pack(anchor="w",
                                                                                       pady=(4, 14))
        self.cv = tk.Canvas(body, bg=BG, width=self.W, height=132, highlightthickness=0, bd=0)
        self.cv.pack(anchor="w")
        self.ring, self.dot, self.ttl, self.stx = [], [], [], []
        for i, (t, d) in enumerate(STEPS):
            cy = 24 + i * 42
            self.ring.append(self.cv.create_oval(6, cy - 10, 26, cy + 10, outline=LINE, width=2))
            self.dot.append(self.cv.create_oval(11, cy - 5, 21, cy + 5, fill=BG, outline=""))
            self.ttl.append(self.cv.create_text(44, cy - 8, text=t, anchor="w", fill=DIM,
                                                font=("Segoe UI", 11, "bold")))
            self.cv.create_text(44, cy + 9, text=d, anchor="w", fill="#555555", font=("Segoe UI", 9))
            self.stx.append(self.cv.create_text(self.W, cy, text="ожидание", anchor="e", fill=DIM,
                                                font=("Segoe UI", 9)))
        self.pb = tk.Canvas(body, bg=PANEL, width=self.W, height=4, highlightthickness=0, bd=0)
        self.pb.pack(anchor="w", pady=(6, 6))
        self.fill = self.pb.create_rectangle(0, 0, 0, 4, fill=HOT, outline="")
        self.msg = tk.Label(body, text="", bg=BG, fg=DIM, font=("Segoe UI", 9), wraplength=540, justify="left",
                            anchor="w")
        self.msg.pack(fill="x", pady=(0, 10))

        def lab(t):
            tk.Label(body, text=t, bg=BG, fg=DIM, font=("Segoe UI", 10), anchor="w").pack(fill="x")
        lab("Голос ассистента")
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=(2, 10))
        self.v_voice = tk.StringVar(value=VOICES[0][0])
        ttk.Combobox(row, textvariable=self.v_voice, state="readonly", width=40,
                     values=[v[0] for v in VOICES]).pack(side="left", fill="x", expand=True)
        Flat(row, "Проверить", self.test_voice).pack(side="left", padx=(8, 0))
        lab("Локальная модель ИИ (без ключей, всё скачается само)")
        self.v_model = tk.StringVar(value=localsetup.MODELS[0][0])
        ttk.Combobox(body, textvariable=self.v_model, state="readonly", width=60,
                     values=[m[0] for m in localsetup.MODELS]).pack(fill="x", pady=(2, 12))
        big = Flat(body, "Установить всё и запустить", self.go_local)
        big.config(padx=22, pady=11, font=("Segoe UI", 11))
        big.pack(fill="x")
        tk.Frame(body, bg=LINE, height=1).pack(fill="x", pady=16)
        lab("Или облачный ИИ бесплатно: выберите сервис и вставьте ключ")
        self.v_prov = tk.StringVar(value=llmmod.PROVIDERS[CLOUD[0]][0])
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=(2, 6))
        ttk.Combobox(row, textvariable=self.v_prov, state="readonly", width=40,
                     values=[llmmod.PROVIDERS[k][0] for k in CLOUD]).pack(side="left", fill="x", expand=True)
        Flat(row, "Получить ключ", self.open_key).pack(side="left", padx=(8, 0))
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=(0, 6))
        self.v_key = tk.StringVar()
        tk.Entry(row, textvariable=self.v_key, show="*", bg=PANEL, fg=FG, insertbackground=FG, relief="flat",
                 font=("Segoe UI", 10), highlightthickness=1, highlightbackground=LINE,
                 highlightcolor=DIM).pack(side="left", fill="x", expand=True, ipady=5)
        Flat(row, "Подключить", self.go_cloud).pack(side="left", padx=(8, 0))
        foot = tk.Frame(body, bg=BG)
        foot.pack(fill="x", side="bottom")
        Flat(foot, "Расширенные настройки", self.advanced).pack(side="left")
        Flat(foot, "Закрыть", self.w.destroy).pack(side="right")
        if not self.cfg["lite"]:
            fade_window(w, 0.3)
        self.tick()

    # ---------- animation ----------
    def tick(self):
        try:
            if not self.w.winfo_exists():
                return
        except tk.TclError:
            return
        now = time.perf_counter()
        dt = min(0.1, now - self.last)
        self.last = now
        self.t += dt
        anim = not self.cfg["lite"]
        k = 1 - math.exp(-dt * (6 if anim else 60))
        for i in range(3):
            s = self.st[i]
            self.vis[i] += ((1.0 if s == 2 else 0.0) - self.vis[i]) * k
            pulse = 0.5 + 0.5 * math.sin(self.t * 4) if s == 1 else 0.0
            if s == 3:
                ring, dot, tcol = ERR, "#7a2e2e", HOT
            else:
                ring = mix(LINE, "#8a8a8a", max(self.vis[i], pulse))
                dot = mix(BG, HOT, self.vis[i]) if s != 1 else mix(BG, "#9a9a9a", pulse)
                tcol = mix(DIM, HOT, max(self.vis[i], 0.7 if s == 1 else 0.0))
            self.cv.itemconfig(self.ring[i], outline=ring)
            self.cv.itemconfig(self.dot[i], fill=dot)
            self.cv.itemconfig(self.ttl[i], fill=tcol)
            self.cv.itemconfig(self.stx[i], text={0: "ожидание", 1: self.msg_short or "выполняю",
                                                  2: "готово", 3: "ошибка"}[s],
                               fill=ERR if s == 3 else (HOT if s == 2 else DIM))
        self.cur += (self.target - self.cur) * k
        self.pb.coords(self.fill, 0, 0, self.W * self.cur, 4)
        self.w.after(33 if anim else 120, self.tick)

    # ---------- helpers ----------
    def set_msg(self, text, err=False):
        self.msg.config(text=text, fg=ERR if err else DIM)

    def begin(self, i, base, span):
        self.active = i
        self.st[i] = 1
        self.base, self.span = base, span
        self.msg_short = ""

    def finish_step(self, i):
        self.st[i] = 2
        self.target = self.base + self.span

    def prog(self, done, total, text):
        self.msg_short = text if len(text) < 44 else text[:43]
        self.target = self.base + self.span * ((done / float(total)) if total else 0.0)

    def open_key(self):
        keys = [k for k in CLOUD if llmmod.PROVIDERS[k][0] == self.v_prov.get()]
        if keys:
            webbrowser.open(llmmod.PROVIDERS[keys[0]][3])

    def advanced(self):
        from .ui import Settings
        Settings(self.app)

    def prepare(self):
        self.voice = {n: i for n, i in VOICES}.get(self.v_voice.get(), VOICES[0][1])
        cfg = self.cfg
        cfg["lang"] = "en" if self.voice.startswith("en-") else "ru"
        if cfg["lang"] == "en" and cfg["ack"] == "Да, хозяин":
            cfg["ack"] = "Yes, master"
        if cfg["lang"] == "ru" and cfg["ack"] == "Yes, master":
            cfg["ack"] = "Да, хозяин"
        cfg["tts_engine"] = "edge"
        cfg["tts_voices"]["edge"] = self.voice

    def test_voice(self):
        self.prepare()
        self.app.agent.tts.say(self.cfg["ack"])

    # ---------- flows ----------
    def go_local(self):
        if self.busy:
            return
        self.prepare()
        idx = [m[0] for m in localsetup.MODELS].index(self.v_model.get())
        self.start("local", idx)

    def go_cloud(self):
        if self.busy:
            return
        key = self.v_key.get().strip()
        if not key:
            self.set_msg("Вставьте ключ. Кнопка Получить ключ откроет страницу регистрации", True)
            return
        self.prepare()
        prov = [k for k in CLOUD if llmmod.PROVIDERS[k][0] == self.v_prov.get()][0]
        self.cfg["provider"] = prov
        self.cfg["keys"][prov] = key
        if prov == "groq":
            self.cfg["keys"]["groq"] = key
        self.start("cloud", 0)

    def start(self, mode, idx):
        self.busy = True
        self.st = [0, 0, 0]
        self.target = 0.0
        self.set_msg("Идёт установка. Окно можно не закрывать, это займёт несколько минут")
        threading.Thread(target=self.work, args=(mode, idx), daemon=True).start()

    def work(self, mode, idx):
        cfg = self.cfg
        res = {}
        try:
            self.begin(0, 0.0, 0.15 if mode == "local" else 0.7)
            if not localsetup.vosk_ready(cfg):
                res["vosk"] = localsetup.install_vosk(cfg["lang"], self.prog)
            self.finish_step(0)
            if mode == "local":
                self.begin(1, 0.15, 0.1)
                res["srv"] = localsetup.install_llama(self.prog)
                self.base, self.span = 0.25, 0.7
                res["mdl"], res["mm"] = localsetup.install_model(idx, self.prog)
                res["vision"] = localsetup.MODELS[idx][2]
            else:
                self.begin(1, 0.7, 0.25)
                self.msg_short = "проверяю ключ"
                llm = llmmod.LLM(cfg)
                "".join(llm.stream([{"role": "user", "content": "Reply with one short word: ok"}]))
            self.finish_step(1)
            self.begin(2, 0.95, 0.05)
            self.msg_short = "настраиваю"
            time.sleep(0.5)
            self.finish_step(2)
            self.target = 1.0
            self.app.root.after(0, lambda: self.finish(mode, res))
        except Exception as e:
            self.st[self.active] = 3
            self.app.root.after(0, lambda: self.fail(e))

    def fail(self, e):
        self.busy = False
        self.set_msg("Ошибка: %s" % e, True)

    def finish(self, mode, res):
        cfg = self.cfg
        cfg["stt_engine"] = "vosk"
        if "vosk" in res:
            cfg["vosk_path"] = res["vosk"]
        cfg["wake"] = True
        cfg["autolisten"] = True
        cfg["tts_enabled"] = True
        if mode == "local":
            cfg["provider"] = "local"
            cfg["llama_lib"], cfg["llama_model"], cfg["llama_mmproj"] = res["srv"], res["mdl"], res["mm"]
            if res.get("vision"):
                cfg["vision_enabled"] = True
        cfg["setup_done"] = True
        cfg.save()
        self.app.agent.reload()
        self.app.start_listening()
        self.busy = False
        self.set_msg("Готово. Скажите: Нова, привет, открой ютуб")
        self.app.sys_msg("Готово. Скажите: «Нова, привет, открой ютуб»")
        self.w.after(1800, self.w.destroy)
