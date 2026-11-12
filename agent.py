import datetime
import queue
import re
import threading
import time
import traceback

from . import council, memory, pc, services, tools
from .config import log
from .llm import LLM
from .stt import Listener
from .tts import TTS

TAG = re.compile(r"\[\[\s*(\w+)\s*\|?([^\]]*)\]\]")
END = re.compile(r"[.!?…]+[\s\"')»]|\n")
CLAUSE = re.compile(r"[,;:—]\s")
ALIASES = ["нова", "нава", "новая", "ново", "новы", "новой", "нову", "nova"]
GREET = re.compile(r"^(?:привет|приветик|здравствуй|здравствуйте|эй|слушай|ты тут|ты здесь|слышишь|"
                   r"hello|hi|hey)\b[\s,]*")
PERSONA = {"friend": "Be warm and friendly.", "strict": "Be strict, brief and businesslike.",
           "funny": "Be witty and playful, with light humor.",
           "butler": "Speak like a refined, polite butler."}
CLAIM = re.compile(r"\b(?:открыва|открою|ввожу|введу|захожу|зайду|запуска|запущу|нажима|нажму|печата|"
                   r"включа|включу|отправля|отправлю|пишу|напишу|ищу|ставлю|перехожу)\w*", re.I)
ASKED = re.compile(r"^(?:открой|запусти|включи|зайди|войди|введи|набери|напиши|нажми|отправь|найди|"
                   r"перейди|покажи|поставь|закрой|сверни|разверни|выбери|залогинься)\b", re.I)
PROMPTS = {"kill_heavy": "Закрыть тяжёлые программы", "shutdown": "Выключить компьютер",
           "restart": "Перезагрузить компьютер", "close_window": "Закрыть текущее окно",
           "forget_all": "Стереть всю память обо мне"}
SAVEABLE = {"open_app", "open_url", "youtube", "music", "media", "volume", "volume_set", "search", "key",
            "minimize", "steam_open", "steam_game", "wait"}
TAGS = ("[[open_url|url]] [[open_app|name]] [[youtube|query]] [[search|query]] [[music|query]] "
        "[[media|playpause/next/prev]] [[volume|up/down/mute]] [[volume_set|0-100]] [[type|text]] [[key|ctrl+c]] "
        "[[click|x|y]] [[vclick|what to click on screen]] [[scroll|n]] [[screenshot|]] [[clipread|]] "
        "[[sysinfo|]] [[top|]] [[kill_heavy|]] [[remind|через 10 минут сделать X]] [[timer|5 минут]] "
        "[[alarm|7 30]] [[remember|fact about the user]] [[todo_add|task]] [[note|text]] [[weather|city]] "
        "[[news|]] [[telegram|text to my own Saved Messages]] [[tg_send|contact or @username|text]] "
        "[[calendar|title and time]] [[ha|domain.service|entity_id]] "
        "[[scenario|name]] [[readsel|translate/summarize/explain]] [[look|]] [[minimize|]] [[lock|]] "
        "[[wait|seconds]] [[focus|app name]] [[password|text]] [[steam_open|library/store/friends]] "
        "[[steam_game|game name in English]] [[steam_login|account name]]")


def wake_split(text, cfg):
    names = set(ALIASES if cfg["name"] == "нова" else []) | {cfg["name"]}
    words = re.findall(r"[\w'-]+", text.lower())
    for i, w in enumerate(words[:4]):
        if w in names:
            rest = " ".join(words[i + 1:])
            for _ in range(3):
                rest = GREET.sub("", rest).strip()
            return True, rest
    return False, text


def extract(buf):
    acts = []

    def rep(m):
        acts.append((m.group(1).lower(), m.group(2).strip()))
        return ""
    return TAG.sub(rep, buf), acts


def split_ready(buf, first):
    i = buf.find("[[")
    safe = buf if i < 0 else buf[:i]
    tail = "" if i < 0 else buf[i:]
    last = -1
    for m in END.finditer(safe):
        last = m.end()
    if last < 0 and first and len(safe) > 28:
        for m in CLAUSE.finditer(safe):
            last = m.end()
    if last < 0:
        return "", buf
    return safe[:last], safe[last:] + tail


def system_prompt(cfg, store):
    s = ("You are %s, a voice assistant living on the user's Windows PC. Address the user as %s. Answer in the "
         "user's language in 1-3 short spoken sentences, plain text only, no markdown, no emoji, no lists. %s "
         % (cfg["name"].capitalize(), cfg["owner"], PERSONA.get(cfg["persona"], PERSONA["friend"])))
    s += ("To act on the computer put action tags at the very start of the answer, then a short confirmation. "
          "Tags: " + TAGS + ". Use tags only when the user asks for an action. "
          "Tags run in the order written. open_app, steam_open and tg_send already wait until the window is open "
          "and in front, so for several steps just write all tags in a row, for example "
          "[[open_app|telegram]][[password|1234]] . To type a password use [[password|...]], to type any other "
          "text use [[type|...]]. HONESTY RULE: never say you opened, typed, logged in or clicked anything unless "
          "the matching tag is in your answer. If no tag can do what the user asks, say briefly that you cannot "
          "do it yet and what the user can do instead. ")
    if store.facts:
        s += "Known facts about the user: " + "; ".join(store.facts[-15:]) + ". "
    ha = services.ha_entities(cfg)
    if ha:
        s += "Smart home entities (id=name): " + ha + ". "
    if not cfg["vision_enabled"]:
        s += "Screen vision is off. "
    return s


class Agent:
    def __init__(self, cfg, emit):
        self.cfg = cfg
        self.emit = emit
        self.store = memory.Store()
        tools.STORE = self.store
        tools.reload_plugins()
        self.llm = LLM(cfg)
        self.tts = TTS(cfg)
        self.tts.on_error = lambda m: emit("error", m)
        self.listener = self._new_listener()
        self.history = []
        self.jobs = queue.Queue()
        self.state = "idle"
        self.cancel = False
        self.awake_until = 0.0
        self.pending = None
        self.pending_ts = 0.0
        self.recent = []
        self.last_text = ""
        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._ticker, daemon=True).start()
        threading.Thread(target=self.llm.preload, daemon=True).start()

    def _new_listener(self):
        return Listener(self.cfg, self.heard, lambda: self.tts.busy, lambda m: self.emit("error", m),
                        self.stop)

    # ---------- input ----------
    def _win(self):
        return 30 if self.cfg["converse"] else 8

    def submit(self, text):
        self.jobs.put(("text", text, None))

    def is_awake(self):
        if self.tts.busy:
            self.awake_until = max(self.awake_until, time.time() + self._win())
        return time.time() < self.awake_until

    def wake_now(self):
        self.awake_until = time.time() + 12

    def heard(self, text):
        if not self.cfg["wake"]:
            self.submit(text)
            return
        found, rest = wake_split(text, self.cfg)
        if found:
            self.awake_until = time.time() + self._win() + 2
            self.jobs.put(("wake", rest, text))
        elif self.is_awake():
            self.awake_until = time.time() + self._win() + 2
            self.jobs.put(("cmd", text, None))

    def stop(self):
        self.cancel = True
        self.llm.cancel()
        self.tts.stop()

    def set_listening(self, on):
        if on:
            self.listener.start()
        else:
            self.listener.stop()

    def reload(self):
        self.llm.close()
        self.llm = LLM(self.cfg)
        threading.Thread(target=self.llm.preload, daemon=True).start()
        self.tts.stop()
        tools.reload_plugins()
        was = self.listener.running
        self.listener.stop()
        self.listener = self._new_listener()
        if was:
            self.listener.start()

    def close(self):
        self.listener.stop()
        self.tts.stop()
        self.llm.close()

    def state_key(self):
        if self.tts.busy:
            return "speaking"
        if self.state != "idle":
            return self.state
        if self.listener.running:
            if self.cfg["wake"] and self.is_awake():
                return "awake"
            return self.listener.state
        return "idle"

    # ---------- worker ----------
    def _worker(self):
        while True:
            kind, text, extra = self.jobs.get()
            self.cancel = False
            try:
                if kind == "brief":
                    self._brief()
                elif kind == "wake":
                    self.emit("user", extra)
                    self._out(self.cfg["ack"])
                    self.emit("bot_end", None)
                    if text:
                        self._process(text, False)
                else:
                    self._process(text, True)
            except Exception as e:
                log(traceback.format_exc())
                self.emit("bot_end", None)
                self.emit("error", str(e))
            finally:
                self.state = "idle"

    def _ticker(self):
        last_sugg = time.time()
        while True:
            time.sleep(1)
            try:
                for r in self.store.due():
                    self.awake_until = time.time() + 25
                    self._out(r["text"], True)
                    self.emit("bot_end", None)
                cfg = self.cfg
                now = datetime.datetime.now()
                today = now.date().isoformat()
                if cfg["brief_on"] and cfg["last_brief"] != today:
                    try:
                        bh, bm = [int(x) for x in cfg["brief_time"].split(":")]
                        diff = now.hour * 60 + now.minute - (bh * 60 + bm)
                    except Exception:
                        diff = -1
                    if 0 <= diff < 180 and self.jobs.empty():
                        cfg["last_brief"] = today
                        cfg.save()
                        self.jobs.put(("brief", "", None))
                idle = self.state == "idle" and not self.tts.busy and self.jobs.empty()
                if cfg["proactive"] and idle and self.listener.running and time.time() - last_sugg > 300:
                    last_sugg = time.time()
                    s = self.store.suggestion()
                    if s:
                        self._suggest(*s)
            except Exception:
                log(traceback.format_exc())

    def _suggest(self, action, arg):
        self.pending = (action, arg)
        self.pending_ts = time.time()
        self.awake_until = time.time() + 25
        name = re.sub(r"^https?://(www\.)?", "", arg)
        self._out("Обычно в это время вы открываете %s. Открыть?" % name)
        self.emit("bot_end", None)

    # ---------- processing ----------
    def _out(self, text, force=False):
        clean = text.strip()
        if clean:
            self.emit("bot", clean + " ")
            if force or not self.cfg["quiet"]:
                self.tts.say(clean)

    def _reply(self, text):
        self._out(text)
        self.emit("bot_end", None)

    def _process(self, text, echo=True):
        if echo:
            self.emit("user", text)
        self.last_text = text
        if self.pending and time.time() - self.pending_ts < 40:
            name, arg = self.pending
            self.pending = None
            t = tools.norm(text, self.cfg)
            if re.match(r"^(?:да|давай|подтверждаю|конечно|ага|yes|ok|окей|делай|выполняй|открой|включи)\b", t):
                r = self.execute(name, arg, True)
                if r:
                    self._reply(r)
            else:
                self._reply("Отменено")
            return
        self.pending = None
        steps = tools.match_chain(text, self.cfg)
        if steps:
            self._run_steps(steps)
            return
        self._ask(text, None, True)

    def _run_steps(self, steps):
        """Runs commands one after another. Stops at the first failure so that a password is never
        typed into the wrong window after the app failed to open."""
        multi = len(steps) > 1
        for i, (name, arg) in enumerate(steps):
            if self.cancel:
                break
            before = self.pending
            r = self.execute(name, arg)
            if r:
                self._out(r)
            if self.pending is not before and self.pending is not None:
                break  # waiting for a yes/no confirmation
            if r and r.startswith("Не "):
                break
            if multi and i + 1 < len(steps) and name in ("open_app", "open_url", "steam_open", "steam_game",
                                                         "tg_send", "steam_login"):
                time.sleep(1.2)
        self.emit("bot_end", None)

    def execute(self, name, arg, confirmed=False):
        cfg = self.cfg
        if name in tools.DANGEROUS and cfg["confirm"] and not confirmed:
            self.pending = (name, arg)
            self.pending_ts = time.time()
            self.awake_until = time.time() + 25
            return PROMPTS.get(name, "Подтвердите действие") + ". Скажите да или нет"
        if name == "stop":
            self.stop()
            return ""
        if name == "quiet":
            cfg["quiet"] = (arg == "on")
            cfg.save()
            if cfg["quiet"]:
                self.tts.stop()
                return "Тихий режим. Отвечаю только текстом"
            return "Голос снова включён"
        if name == "look":
            self._look(arg or self.last_text)
            return ""
        if name == "vclick":
            return self._vclick(arg)
        if name == "readsel":
            return self._readsel(arg)
        if name == "readfile":
            return self._readfile(arg)
        if name == "think":
            if not arg:
                return "Что обсудить с советом?"
            self._ask(arg, None, True, True)
            return ""
        if name == "brief":
            self._brief()
            return ""
        if name.startswith("scenario"):
            return self._scen(name, arg)
        try:
            r = tools.run(name, arg, cfg)
        except Exception as e:
            log(traceback.format_exc())
            return "Не получилось: %s" % e
        if r is None:
            return "Не умею действие %s" % name
        self.recent.append((time.time(), name, arg))
        self.recent = self.recent[-30:]
        self.store.log_usage(name, arg)
        return r

    # ---------- scenarios ----------
    def _scen(self, name, arg):
        st = self.store
        if name == "scenario_list":
            return ("Режимы: " + ", ".join(st.scen)) if st.scen else "Режимов пока нет. Скажите: запомни это как режим работа"
        if name == "scenario_del":
            return "Удалил" if st.del_scenario(arg) else "Такого режима нет"
        if name == "scenario_save":
            steps, seen = [], None
            for t, n, a in self.recent:
                if time.time() - t < 900 and n in SAVEABLE and (n, a) != seen:
                    steps.append([n, a])
                    seen = (n, a)
            if not steps:
                return "Не вижу недавних действий, которые можно запомнить"
            st.save_scenario(arg, steps)
            return "Запомнил режим %s, действий: %d" % (arg, len(steps))
        if name == "scenario_make":
            nm, _, txt = arg.partition("|")
            steps = []
            for seg in tools.split_steps(txt):
                h = tools.match(seg, self.cfg)
                if h and h[0] in SAVEABLE | {"type"}:
                    steps.append([h[0], h[1]])
            if not steps:
                return "Не понял, какие действия включить в режим"
            st.save_scenario(nm, steps)
            return "Создал режим %s, действий: %d" % (nm, len(steps))
        k, steps = st.find_scenario(arg)
        if not k:
            return "Режима %s нет" % arg
        self._out("Запускаю режим " + k)
        for a, ar in steps:
            if a in tools.DANGEROUS:
                continue
            self.execute(a, ar, True)
            time.sleep(0.8)
        return ""

    # ---------- reading, vision ----------
    def _task(self, instr, content):
        msgs = [{"role": "system", "content": "You are a helpful voice assistant. Answer in the user's language "
                                                "unless told otherwise. Plain text, no markdown, no emoji."},
                {"role": "user", "content": instr + "\n\n" + content[:6000]}]
        self.state = "thinking"
        self._speak_stream(msgs, None, False)
        self.emit("bot_end", None)

    def _readsel(self, verb):
        text = pc.copy_selection()
        if not text.strip():
            return "Ничего не выделено"
        v = verb.lower()
        if v.startswith(("перев", "transl")):
            ins = "Translate this text into Russian (if it is already Russian, into English). Output only the translation."
        elif v.startswith(("объясн", "expl")):
            ins = "Explain this text simply."
        elif v.startswith(("исправ", "fix")):
            ins = "Correct grammar and spelling. Output only the corrected text."
        elif v.startswith("проч"):
            ins = "Restate the content in clear spoken language."
        else:
            ins = "Summarize this text briefly."
        self._task(ins, text)
        return ""

    def _readfile(self, name):
        f = pc.find_files(name, 1)
        if not f:
            return "Файл не нашёл"
        try:
            text = pc.read_file_text(f[0])
        except Exception as e:
            return "Не смог прочитать файл: %s" % e
        self._task("Summarize this file briefly (file: %s)." % f[0].split("\\")[-1], text)
        return ""

    def _look(self, instr):
        if not self.cfg["vision_enabled"]:
            self._reply(tools._t(self.cfg, "novision"))
            return
        self.emit("sys", "Смотрю на экран")
        img, _, _ = tools.screenshot_b64()
        msgs = [{"role": "system", "content": system_prompt(self.cfg, self.store)},
                {"role": "user", "content": instr or "Describe what is on the screen briefly."}]
        self.state = "thinking"
        self._speak_stream(msgs, img, False)
        self.emit("bot_end", None)

    def _vclick(self, desc):
        if not self.cfg["vision_enabled"]:
            return tools._t(self.cfg, "novision")
        img, (w, h), (fw, fh) = tools.screenshot_b64()
        q = ("This is a screenshot of size %dx%d pixels. Find: %s. Answer ONLY with JSON like {\"x\":123,\"y\":45} "
             "giving the center pixel of it in this image, or {\"x\":-1,\"y\":-1} if it is not visible." % (w, h, desc))
        out = "".join(self.llm.stream([{"role": "user", "content": q}], img))
        m = re.search(r"x\W+(-?\d+).*?y\W+(-?\d+)", out, re.S)
        if not m or int(m.group(1)) < 0:
            return "Не вижу этого на экране"
        pc.click(int(m.group(1)) * fw / float(w), int(m.group(2)) * fh / float(h))
        return "Нажал"

    def _brief(self):
        cfg = self.cfg
        h = datetime.datetime.now().hour
        greet = "Доброе утро" if h < 12 else "Добрый день" if h < 18 else "Добрый вечер"
        parts = ["%s, %s. %s." % (greet, cfg["owner"], tools.run("date", "", cfg))]
        try:
            parts.append(services.weather("", cfg))
        except Exception:
            pass
        todo = self.store.todo_open()
        if todo:
            parts.append("В списке дел %d: %s" % (len(todo), "; ".join(todo[:4])))
        n = len([r for r in self.store.reminders if r["due"] - time.time() < 86400])
        if n:
            parts.append("Напоминаний на ближайшие сутки: %d" % n)
        try:
            parts.append(services.news(cfg, 3))
        except Exception:
            pass
        for p in parts:
            self._out(p)
        self.emit("bot_end", None)

    # ---------- LLM ----------
    def _gen(self, msgs, image):
        cfg = self.cfg
        if cfg["council_mode"] == "race" and image is None and len(council.members(cfg)) >= 2:
            return council.race(cfg, msgs, image)
        if cfg["fallback"] and len(council.cloud_members(cfg)) >= 2:
            return council.fallback(cfg, self.llm, msgs, image)
        return self.llm.stream(msgs, image)

    def _council_on(self, text, force):
        cfg = self.cfg
        mem = council.members(cfg)
        if len(mem) < 2:
            return False
        if force or cfg["council_mode"] == "always":
            return True
        return cfg["council_mode"] == "auto" and council.needs_council(text)

    def _tag(self, name, arg, deferred):
        """Runs one action tag from the model. Returns False if it failed."""
        if name == "think":
            return True
        if name in ("look", "readsel", "readfile", "scenario", "vclick", "brief"):
            deferred.append((name, arg))
            return True
        before = self.pending
        r = self.execute(name, arg)
        failed = bool(r) and r.startswith("Не ")
        if r and (name in tools.INFO or name in ("remind", "timer", "alarm", "ha", "telegram", "tg_send",
                                                 "steam_game", "steam_login", "steam_open", "login", "password")
                  or self.pending is not before or failed):
            self._out(r)
        return not failed

    def _speak_stream(self, msgs, image, allow_tags=True):
        """Speaks the answer while it streams. Action tags run in order in their own thread, so waiting for
        a window to open never delays the voice. Returns (spoken, deferred, number_of_tags_run)."""
        buf, said, deferred, first = "", [], [], True
        aq = queue.Queue()
        state = {"ran": 0, "failed": False}

        def runner():
            while True:
                item = aq.get()
                if item is None:
                    return
                if state["failed"] or self.cancel:
                    continue
                try:
                    state["ran"] += 1
                    if not self._tag(item[0], item[1], deferred):
                        state["failed"] = True
                except Exception as e:
                    state["failed"] = True
                    log(traceback.format_exc())
                    self.emit("error", str(e))
        worker = threading.Thread(target=runner, daemon=True)
        worker.start()
        try:
            for chunk in self._gen(msgs, image):
                if self.cancel:
                    break
                buf += chunk
                buf, acts = extract(buf)
                if allow_tags:
                    for a in acts:
                        aq.put(a)
                ready, buf = split_ready(buf, first)
                if ready.strip():
                    first = False
                    said.append(ready.strip())
                    self._out(ready)
            if not self.cancel:
                buf, acts = extract(buf)
                if allow_tags:
                    for a in acts:
                        aq.put(a)
                buf = buf.replace("[[", "").strip()
                if buf:
                    said.append(buf)
                    self._out(buf)
        finally:
            aq.put(None)
            worker.join(timeout=90)
        return said, deferred, state["ran"]

    def _ask(self, text, image, remember, force_council=False):
        self.state = "thinking"
        cfg = self.cfg
        n = cfg.eff_history() * 2
        base = [{"role": "system", "content": system_prompt(cfg, self.store)}] + self.history[-n:] + \
               [{"role": "user", "content": text}]
        msgs = base
        if image is None and self._council_on(text, force_council):
            self.emit("sys", "Совет ИИ: " + ", ".join(council.members(cfg)))
            cands = council.gather(cfg, base)
            if cands:
                msgs = council.synth_messages(base, cands)
        elif not self.llm.ready():
            self.emit("sys", "Загружаю локальную модель, это займёт несколько секунд")
        said, deferred, ran = self._speak_stream(msgs, image)
        # the model announced an action but wrote no tag, so nothing happened: ask once more, strictly
        if (not self.cancel and image is None and ran == 0 and not deferred and said
                and ASKED.match(tools.norm_keep(text, cfg)) and CLAIM.search(" ".join(said))):
            retry = msgs + [{"role": "assistant", "content": " ".join(said)},
                            {"role": "user", "content": "Nothing happened: you wrote no action tags. Answer ONLY "
                             "with the needed [[tags]] in order (add [[wait|2]] between steps if needed), no other "
                             "words. If no tag can do this, say in one short sentence that you cannot."}]
            said2, deferred2, ran2 = self._speak_stream(retry, None)
            deferred += deferred2
            if ran2 == 0 and not deferred2 and not said2:
                self._out("Не получилось подобрать команду для этого действия")
        self.emit("bot_end", None)
        if remember and said:
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": " ".join(said)}]
            self.history = self.history[-40:]
        for name, arg in deferred:
            if self.cancel:
                break
            r = self.execute(name, arg)
            if r:
                self._reply(r)
