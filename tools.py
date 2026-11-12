import base64
import datetime
import io
import os
import re
import subprocess
import time
import urllib.parse
import webbrowser

from . import apps, memory, pc, plugins, services
from .config import data_dir

SITES = {
    "youtube": "https://www.youtube.com", "ютуб": "https://www.youtube.com",
    "ютьюб": "https://www.youtube.com", "ютюб": "https://www.youtube.com",
    "йутуб": "https://www.youtube.com", "ютуп": "https://www.youtube.com",
    "google": "https://www.google.com", "гугл": "https://www.google.com",
    "яндекс": "https://ya.ru", "yandex": "https://ya.ru",
    "вк": "https://vk.com", "вконтакте": "https://vk.com", "vk": "https://vk.com",
    "github": "https://github.com", "гитхаб": "https://github.com",
    "почта": "https://mail.google.com", "gmail": "https://mail.google.com",
    "twitch": "https://www.twitch.tv", "твитч": "https://www.twitch.tv",
    "netflix": "https://www.netflix.com", "нетфликс": "https://www.netflix.com",
    "chatgpt": "https://chatgpt.com", "чат гпт": "https://chatgpt.com",
    "карты": "https://maps.google.com", "переводчик": "https://translate.google.com",
    "википедия": "https://ru.wikipedia.org", "wikipedia": "https://en.wikipedia.org",
}
APPS = {
    "блокнот": "notepad", "notepad": "notepad",
    "калькулятор": "calc", "calculator": "calc",
    "paint": "mspaint", "пейнт": "mspaint",
    "проводник": "explorer", "explorer": "explorer",
    "командная строка": "cmd", "cmd": "cmd", "терминал": "cmd",
    "диспетчер задач": "taskmgr", "task manager": "taskmgr",
    "панель управления": "control", "control panel": "control",
    "настройки": "ms-settings:", "settings": "ms-settings:",
    "chrome": "chrome", "хром": "chrome", "гугл хром": "chrome",
    "firefox": "firefox", "фаерфокс": "firefox", "файрфокс": "firefox",
    "edge": "msedge", "эдж": "msedge",
    "telegram": "tg://", "телеграм": "tg://", "телеграмм": "tg://",
    "discord": "discord:", "дискорд": "discord:",
    "steam": "steam://open/main", "стим": "steam://open/main",
    "spotify": "spotify:", "спотифай": "spotify:",
    "word": "winword", "ворд": "winword", "excel": "excel", "эксель": "excel",
    "vlc": "vlc",
}

R = {
    "ru": {"open": "Открываю %s", "search": "Ищу %s", "yt": "Ищу на ютубе %s", "ok": "Готово",
           "time": "Сейчас %s", "date": "Сегодня %s", "novision": "Режим зрения выключен в настройках",
           "look": "Смотрю на экран", "fail": "Не получилось открыть %s"},
    "en": {"open": "Opening %s", "search": "Searching %s", "yt": "Searching YouTube for %s", "ok": "Done",
           "time": "It is %s", "date": "Today is %s", "novision": "Vision is turned off in settings",
           "look": "Looking at the screen", "fail": "Could not open %s"},
}
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
          "октября", "ноября", "декабря"]

KEYS = {"playpause": 0xB3, "next": 0xB0, "prev": 0xB1, "up": 0xAF, "down": 0xAE, "mute": 0xAD}


def _t(cfg, key):
    return R.get(cfg["lang"], R["en"])[key]


def _key(vk, times=1):
    import ctypes
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


def custom_apps(cfg):
    d = {}
    for line in cfg["custom_apps"].splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip().lower()] = v.strip().strip('"')
    return d


def resolve(name, cfg):
    n = name.strip().lower()
    c = custom_apps(cfg)
    if n in c:
        return c[n]
    if n in SITES:
        return SITES[n]
    if n in APPS:
        return APPS[n]
    return None


def _start(target):
    if re.match(r"^[a-z][a-z0-9+.-]*:", target) and not re.match(r"^[a-z]:[\\/]", target, re.I):
        os.startfile(target)
    elif os.path.exists(target):
        os.startfile(target)
    else:
        subprocess.Popen(["cmd", "/c", "start", "", target], creationflags=0x08000000)


def open_target(name, cfg, strict=False):
    t = resolve(name, cfg)
    if t is None:
        if strict:
            return None
        t = name
    key = apps.canon_app(name)
    try:
        if t.startswith("http"):
            webbrowser.open(t)
        elif key in apps.WINDOWED:
            # start, wait until the window really exists and bring it to the front,
            # so that the next step (typing, a click) lands in this app
            if name.strip().lower() in custom_apps(cfg):
                _start(t)
            ok, err = apps.ensure_app(key, 15.0, launch=name.strip().lower() not in custom_apps(cfg))
            if not ok:
                return err
        else:
            _start(t)
    except Exception:
        return _t(cfg, "fail") % name
    return _t(cfg, "open") % name


STORE = None
PLUGIN_CMDS = []
PLUGIN_ACTS = {}
DANGEROUS = {"kill_heavy", "shutdown", "restart", "close_window", "forget_all"}
AGENT_ACTS = {"stop", "quiet", "look", "readsel", "readfile", "think", "scenario", "scenario_save",
              "scenario_make", "scenario_list", "scenario_del", "brief", "vclick"}
INFO = {"weather", "news", "sysinfo", "top", "clipread", "time", "date", "todo_list", "reminders_list",
        "facts_list", "temp", "battery"}
PERSONAS = {"друг": "friend", "строг": "strict", "весел": "funny", "дворецк": "butler"}


def reload_plugins():
    global PLUGIN_CMDS, PLUGIN_ACTS
    PLUGIN_CMDS, PLUGIN_ACTS = plugins.load()


def _fmt_due(due):
    d = int(due - time.time())
    if d < 3600:
        return "через %d мин" % max(1, round(d / 60.0))
    return "в " + datetime.datetime.fromtimestamp(due).strftime("%H:%M")


def _remind(arg, cfg):
    r = memory.parse_when(memory.digitize(arg))
    if not r:
        return "Не понял, когда напомнить. Скажите, например: напомни через 10 минут позвонить"
    STORE.add_reminder(r[0], r[1] or "Время вышло")
    return "Напомню %s" % _fmt_due(r[0])


def _timer(arg, cfg):
    t = memory.digitize(arg.lower())
    if not re.search(r"\b(?:через|на)\b", t):
        t = "на " + t
    r = memory.parse_when(t)
    if not r:
        return "Не понял на сколько поставить таймер"
    STORE.add_reminder(r[0], "Таймер сработал", "timer")
    return "Таймер %s" % _fmt_due(r[0])


def _alarm(arg, cfg):
    t = memory.digitize(arg.lower())
    if t[:1].isdigit():
        t = "на " + t
    r = memory.parse_when(t, alarm=True)
    if not r:
        return "Не понял на какое время поставить будильник"
    STORE.add_reminder(r[0], "Будильник", "alarm")
    return "Будильник %s" % _fmt_due(r[0])


def _list_reminders(arg, cfg):
    rs = sorted(STORE.reminders, key=lambda r: r["due"])
    if not rs:
        return "Напоминаний нет"
    return "Напоминания: " + "; ".join("%s %s" % (_fmt_due(r["due"]), r["text"]) for r in rs[:5])


def _todo_list(arg, cfg):
    o = STORE.todo_open()
    return ("В списке дел: " + "; ".join(o[:8])) if o else "Список дел пуст"


def _openfile(arg, cfg):
    f = pc.find_files(arg, 1)
    if not f:
        return "Файл не нашёл"
    os.startfile(f[0])
    return "Открываю %s" % os.path.basename(f[0])


def _persona(arg, cfg):
    for k, v in PERSONAS.items():
        if arg.lower().startswith(k):
            cfg["persona"] = v
            cfg.save()
            return "Хорошо"
    return "Не знаю такого характера"


def _two(arg):
    p = [x.strip() for x in arg.split("|")]
    return p + [""] * (2 - len(p))


def _volume(arg, cfg):
    if arg == "mute":
        _key(KEYS["mute"])
    else:
        _key(KEYS["up" if arg == "up" else "down"], 5)
    return _t(cfg, "ok")


def _media(arg, cfg):
    _key(KEYS.get({"pause": "playpause", "play": "playpause"}.get(arg, arg), KEYS["playpause"]))
    return _t(cfg, "ok")


def _min(arg, cfg):
    pc.press("win+d")
    return _t(cfg, "ok")


def _lock(arg, cfg):
    import ctypes
    ctypes.windll.user32.LockWorkStation()
    return _t(cfg, "ok")


def _note(arg, cfg):
    with open(os.path.join(data_dir(), "notes.txt"), "a", encoding="utf-8") as f:
        f.write("%s  %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), arg))
    return _t(cfg, "ok")


def _open_url(arg, cfg):
    if re.match(r"^[a-z][a-z0-9+.-]*://", arg, re.I) and not arg.lower().startswith(("http://", "https://")):
        _start(arg)  # steam://, tg://, spotify://
    else:
        webbrowser.open(arg if arg.startswith("http") else "https://" + arg)
    return _t(cfg, "ok")


def _date(arg, cfg):
    d = datetime.date.today()
    s = "%d %s %d" % (d.day, MONTHS[d.month - 1], d.year) if cfg["lang"] == "ru" else d.strftime("%B %d, %Y")
    return _t(cfg, "date") % s


def _wait(arg, cfg):
    try:
        time.sleep(max(0.0, min(30.0, float(arg.replace(",", ".") or 1))))
    except ValueError:
        time.sleep(1.0)
    return ""


def _focus(arg, cfg):
    key = apps.canon_app(arg)
    if key in apps.WINDOWED:
        ok, err = apps.ensure_app(key, 10.0)
        return "" if ok else err
    if pc.wait_window([arg.lower()], [], 6.0):
        return ""
    return "Не нашёл окно %s" % arg


def _password(arg, cfg):
    t = arg.strip().strip("\"'\u00ab\u00bb")
    if re.fullmatch(r"[\d\s]+", t):
        t = re.sub(r"\s+", "", t)  # speech recognition writes digits with spaces
    if not t:
        return "Не услышал пароль"
    pc.type_text(t)
    time.sleep(0.15)
    pc.press("enter")
    return "Ввёл пароль"


def _login(arg, cfg):
    if apps.LAST[0] == "steam":
        return apps.steam_login(arg)
    return "Не понял, в каком приложении входить. Скажите, например: зайди в аккаунт %s в стиме" % arg


def _tg_send(arg, cfg):
    contact, _, text = arg.partition("|")
    return apps.tg_send(contact, text)


def _telegram(arg, cfg):
    if cfg.get("tg_token") and cfg.get("tg_chat"):
        return services.telegram(arg, cfg)
    return apps.tg_send("мне", arg)  # no bot configured: write to Saved Messages from the real account


def _ok(fn):
    def w(arg, cfg):
        fn(arg)
        return _t(cfg, "ok")
    return w


ACT = {
    "open_url": _open_url,
    "open_app": lambda a, c: open_target(a, c),
    "youtube": lambda a, c: (webbrowser.open("https://www.youtube.com/results?search_query=" +
                                             urllib.parse.quote(a)), _t(c, "yt") % a)[1],
    "search": lambda a, c: (webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(a)),
                            _t(c, "search") % a)[1],
    "music": lambda a, c: services.music(a, c),
    "media": _media, "volume": _volume,
    "volume_set": lambda a, c: (pc.set_volume(int(re.sub(r"\D", "", a) or 50)), _t(c, "ok"))[1],
    "minimize": _min, "lock": _lock,
    "time": lambda a, c: _t(c, "time") % datetime.datetime.now().strftime("%H:%M"),
    "date": _date, "note": _note,
    "type": lambda a, c: (pc.type_text(a), _t(c, "ok"))[1],
    "key": lambda a, c: (_t(c, "ok") if pc.press(a) else "Не знаю такую клавишу"),
    "click": lambda a, c: (pc.click(*[int(x) for x in _two(a)]), _t(c, "ok"))[1],
    "scroll": lambda a, c: (pc.scroll(int(a or -3)), _t(c, "ok"))[1],
    "screenshot": lambda a, c: "Скриншот сохранён в папку Изображения: " + os.path.basename(pc.screenshot_save()),
    "clipread": lambda a, c: ("В буфере: " + pc.clip_get()[:400]) if pc.clip_get() else "Буфер пуст",
    "sysinfo": lambda a, c: pc.sysinfo(), "top": lambda a, c: pc.top_procs(),
    "temp": lambda a, c: pc.temperature(), "battery": lambda a, c: pc.battery(),
    "kill_heavy": lambda a, c: pc.kill_heavy(),
    "shutdown": lambda a, c: pc.shutdown(False), "restart": lambda a, c: pc.shutdown(True),
    "shutdown_cancel": lambda a, c: pc.shutdown_cancel(),
    "close_window": lambda a, c: (pc.press("alt+f4"), _t(c, "ok"))[1],
    "remember": lambda a, c: (STORE.remember(a), "Запомнил")[1],
    "forget": lambda a, c: (STORE.forget(a), "Забыл")[1],
    "forget_all": lambda a, c: (STORE.forget(None), "Память очищена")[1],
    "facts_list": lambda a, c: ("Я знаю: " + "; ".join(STORE.facts[-8:])) if STORE.facts else "Пока ничего не знаю о вас",
    "remind": _remind, "timer": _timer, "alarm": _alarm, "reminders_list": _list_reminders,
    "reminders_clear": lambda a, c: (STORE.clear_reminders(), "Убрал все напоминания")[1],
    "todo_add": lambda a, c: (STORE.todo_add(a), "Добавил в список дел")[1],
    "todo_list": _todo_list,
    "todo_done": lambda a, c: "Вычеркнул" if STORE.todo_done(a) else "Такой задачи нет",
    "todo_clear": lambda a, c: (STORE.todo_clear(), "Список дел очищен")[1],
    "weather": lambda a, c: services.weather(a, c), "news": lambda a, c: services.news(c),
    "telegram": _telegram, "tg_send": _tg_send, "password": _password, "login": _login,
    "wait": _wait, "focus": _focus,
    "steam_open": lambda a, c: apps.steam_open(a.lower() or "library"),
    "steam_game": lambda a, c: apps.steam_play(a),
    "steam_login": lambda a, c: apps.steam_login(a),
    "calendar": lambda a, c: _calendar(a, c),
    "mail": lambda a, c: services.mail(a),
    "ha": lambda a, c: services.ha_call(a, c),
    "openfile": _openfile, "persona": _persona,
}


def _calendar(arg, cfg):
    r = memory.parse_when(memory.digitize(arg))
    due, title = (r if r else (time.time() + 3600, arg))
    return services.calendar(title or arg, due)


def run(action, arg, cfg):
    """Executes an action. Returns reply text, or None if the action is unknown."""
    if action == "__plugin":
        fn, m = arg
        return fn(m, cfg) or ""
    fn = ACT.get(action) or PLUGIN_ACTS.get(action)
    if fn is None:
        return None
    if action in PLUGIN_ACTS and action not in ACT:
        return fn(arg, cfg) or ""
    return fn((arg or "").strip(), cfg) or ""


def screenshot_b64(max_side=1024):
    from PIL import ImageGrab
    img = ImageGrab.grab().convert("RGB")
    full = img.size
    img.thumbnail((max_side, max_side))
    b = io.BytesIO()
    img.save(b, "JPEG", quality=70)
    return base64.b64encode(b.getvalue()).decode(), img.size, full


def norm(t, cfg):
    t = t.lower().strip()
    t = re.sub(r"[^\w\s:/.+-]", " ", t, flags=re.U)
    t = re.sub(r"\s+", " ", t).strip()
    name = cfg["name"].lower().strip()
    for _ in range(2):
        if name:
            t = re.sub(r"^(?:привет |эй |слушай |hey |hi |ok |ну )?%s[ ,]+" % re.escape(name), "", t)
        t = re.sub(r"^(?:привет|ну|а|эй|слушай|hey|hi|ok|пожалуйста|please)\s+", "", t)
    t = re.sub(r"\s+(?:пожалуйста|please)$", "", t)
    return memory.digitize(t.strip())


def split_steps(rest):
    return [p.strip() for p in re.split(
        r"\s+(?=(?:открой|запусти|включи|найди|громкость|нажми|набери|напечатай)\b)|\s+и\s+|\s+потом\s+|\s+затем\s+",
        rest) if p.strip()]


_KEYS = {"enter": "enter", "ентер": "enter", "энтер": "enter", "пробел": "space", "таб": "tab",
         "эскейп": "esc", "escape": "esc", "esc": "esc", "backspace": "backspace", "удалить": "delete",
         "delete": "delete"}

TABLE = [
    (r"^(?:стоп|замолчи|хватит|тихо|помолчи|stop|shut up|quiet)$", "stop", ""),
    (r"^(?:тихий режим|режим тишины|не говори|молчи|quiet mode)$", "quiet", "on"),
    (r"^(?:говори|голосовой режим|можешь говорить|включи голос|speak)$", "quiet", "off"),
    (r"^(?:отмени выключение|отмени перезагрузку)$", "shutdown_cancel", ""),
    (r"^(?:посмотри на экран|что на экране|look at (?:my )?screen|what.s on (?:my )?screen)$", "look", ""),
    (r"^(?:прочитай (?:мне )?экран|прочитай что на экране|перескажи (?:эту )?страницу|перескажи экран|о чем эта страница)$",
     "look", "Read the visible text on the screen and summarize it briefly"),
    (r"^(?:созови совет|совет моделей|подумай хорошо|спроси все модели|спроси всех)\s*(.*)$", "think", 1),
    (r"^(переведи|перескажи|прочитай|объясни|исправь)\s+(?:мне\s+)?(?:выделенн\w+|то что я выделил|выделенный текст)$",
     "readsel", 1),
    (r"^(?:перескажи|прочитай|суммируй)\s+файл\s+(.+)$", "readfile", 1),
    (r"^(?:найди|открой)\s+файл\s+(.+)$", "openfile", 1),
    # --- Steam ---
    (r"^(?:открой|открыть|запусти|покажи|зайди в|перейди в|включи)\s+(?:мою\s+)?библиотеку(?:\s+игр)?(?:\s+(?:в\s+)?(?:стим\w*|steam))?$",
     "steam_open", "library"),
    (r"^(?:открой|открыть|запусти|покажи|зайди в|перейди в)\s+(?:в\s+)?(?:стим\w*|steam)\s+(?:мою\s+)?библиотеку(?:\s+игр)?$",
     "steam_open", "library"),
    (r"^(?:открой|покажи|перейди в)\s+(?:магазин|стор)(?:\s+(?:в\s+)?(?:стим\w*|steam))?$", "steam_open", "store"),
    (r"^(?:открой|покажи)\s+(?:мои\s+)?друзей(?:\s+(?:в\s+)?(?:стим\w*|steam))?$", "steam_open", "friends"),
    (r"^(?:зайди|войди|залогинься|авторизуйся|переключись|перейди)\s+(?:в|на|под)\s+(?:мой\s+)?(?:аккаунт|акк|профиль|учетку|учетную запись)\s+(?:в\s+)?(?:стим\w*\s+|steam\s+)?(.+?)(?:\s+(?:в\s+)?(?:стим\w*|steam))?$",
     "login", 1),
    (r"^(?:зайди|войди|залогинься|авторизуйся)\s+(?:в\s+)?(?:стим\w*|steam)\s+(?:под\s+|на\s+|в\s+)?(?:аккаунт\s+|акк\s+)?(.+)$",
     "steam_login", 1),
    (r"^(?:открой|запусти|включи|найди)\s+(?:мне\s+)?(?:игру\s+)?(.+?)\s+(?:в\s+)?(?:моей\s+)?(?:библиотеке|стиме|steam|стим)(?:\s+(?:стим|steam))?$",
     "steam_game", 1),
    (r"^(?:найди|открой|запусти|включи)\s+(?:в\s+)?(?:моей\s+)?(?:библиотеке|стиме)(?:\s+(?:стим|steam))?\s+(?:игру\s+)?(.+)$",
     "steam_game", 1),
    (r"^(?:запусти|включи|открой|найди)\s+игру\s+(.+)$", "steam_game", 1),
    (r"^(?:давай\s+)?(?:поиграем|погнали играть)\s+в\s+(.+)$", "steam_game", 1),
    # --- Telegram from the user's own account ---
    (r"^(?:напиши|отправь|скинь)\s+(?:мне|себе)\s+(?:в\s+)?(?:телеграм\w*|telegram)\s+(.+)$", "telegram", 1),
    (r"^(?:напиши|отправь|скинь)\s+(?:в\s+)?(?:телеграм\w*|telegram)\s+(?:пользователю\s+|контакту\s+)?(@?\S+)\s+(.+)$",
     "tg_send", lambda m: m.group(1) + "|" + m.group(2)),
    (r"^(?:напиши|отправь|скинь)\s+(@?.+?)\s+(?:в\s+)?(?:телеграм\w*|telegram)[:,]?\s+(.+)$",
     "tg_send", lambda m: m.group(1) + "|" + m.group(2)),
    # --- typing ---
    (r"^(?:введи|набери|напечатай|вбей|впиши|печатай)\s+(?:мой\s+|мне\s+)?пароль\s*[:\-]?\s+(.+)$", "password", 1),
    (r"^(?:напиши|отправь)\s+(?:мне\s+)?(?:в\s+)?(?:телеграм\w*|telegram)\s+(.+)$", "telegram", 1),
    (r"^(?:включи|найди|поставь)\s+(?:песню|трек|музыку|музыка)\s+(.+)$", "music", 1),
    (r"^(?:включи\s+)?(?:в\s+)?(?:спотифай|spotify)\s+(.+)$", "music", 1),
    (r"^(?:найди|включи|поищи|запусти|покажи|search|play)\s+(.+?)\s+(?:на|в|on|in)\s+(?:ютубе|ютуб|youtube)$",
     "youtube", 1),
    (r"^(?:найди|загугли|поищи|погугли|google|search for|search)\s+(?:в интернете\s+|в гугле\s+)?(.+)$",
     "search", 1),
    (r"^(?:открой|открыть|запусти|запустить|включи|зайди в|зайди на|войди в|open|launch|start)\s+(.+)$", "open_strict", 1),
    (r"^(?:пауза|поставь на паузу|продолжи|пуск|воспроизведи|play|pause|resume)$", "media", "playpause"),
    (r"^(?:дальше|следующий|следующая|следующий трек|next|skip|скип)$", "media", "next"),
    (r"^(?:предыдущий|предыдущая|предыдущий трек|previous|back)$", "media", "prev"),
    (r"^(?:громкость|звук)\s+(?:на\s+)?(\d+)(?:\s*процент\w*)?$", "volume_set", 1),
    (r"^(?:громче|прибавь звук|прибавь громкость|louder|volume up)$", "volume", "up"),
    (r"^(?:тише|убавь звук|убавь громкость|quieter|volume down)$", "volume", "down"),
    (r"^(?:без звука|выключи звук|включи звук|mute|unmute)$", "volume", "mute"),
    (r"^(?:набери|напечатай|введи|печатай|напиши текст)\s+(.+)$", "type", 1),
    (r"^нажми\s+(?:на\s+)?(?:клавишу\s+)?(enter|ентер|энтер|пробел|таб|эскейп|escape|esc|backspace|удалить|delete)$",
     "key", lambda m: _KEYS[m.group(1)]),
    (r"^(?:скопируй|копировать)$", "key", "ctrl+c"), (r"^(?:вставь|вставить)$", "key", "ctrl+v"),
    (r"^(?:выдели все|выделить все)$", "key", "ctrl+a"), (r"^(?:отмени|отменить)$", "key", "ctrl+z"),
    (r"^(?:сохрани|сохранить)$", "key", "ctrl+s"), (r"^новая вкладка$", "key", "ctrl+t"),
    (r"^закрой вкладку$", "key", "ctrl+w"), (r"^(?:обнови страницу|обнови)$", "key", "f5"),
    (r"^(?:переключи окно|следующее окно|альт таб)$", "key", "alt+tab"),
    (r"^(?:разверни окно|на весь экран)$", "key", "win+up"), (r"^сверни окно$", "key", "win+down"),
    (r"^(?:прокрути вниз|вниз)$", "scroll", "-5"), (r"^(?:прокрути вверх|вверх)$", "scroll", "5"),
    (r"^(?:закрой окно|закрой программу)$", "close_window", ""),
    (r"^(?:сделай скриншот|скриншот|сфотографируй экран)$", "screenshot", ""),
    (r"^нажми\s+(?:на\s+)?(.+)$", "vclick", 1),
    (r"^(?:что в буфере обмена|прочитай буфер|что в буфере)$", "clipread", ""),
    (r"^(?:что грузит (?:процессор|компьютер|комп|пк)|что тормозит)$", "top", ""),
    (r"^(?:закрой тяжелые программы|закрой все тяжелые|освободи память)$", "kill_heavy", ""),
    (r"^(?:состояние (?:компьютера|системы)|как дела у компьютера|загрузка процессора|сколько оперативки)$",
     "sysinfo", ""),
    (r"^температура(?: процессора| компьютера)?$", "temp", ""),
    (r"^(?:заряд батареи|заряд аккумулятора|сколько заряда|сколько процентов заряда)$", "battery", ""),
    (r"^выключи компьютер$", "shutdown", ""), (r"^перезагрузи компьютер$", "restart", ""),
    (r"^(?:сверни все|сверни окна|сверни все окна|покажи рабочий стол|show desktop)$", "minimize", ""),
    (r"^(?:заблокируй компьютер|заблокируй экран|lock|lock screen|lock computer)$", "lock", ""),
    (r"^(?:который час|сколько времени|время|what time is it|what time)$", "time", ""),
    (r"^(?:какое сегодня число|какая сегодня дата|какая дата|what date is it|what.s the date)$", "date", ""),
    (r"^(?:какая )?погода(?: в (.+))?$", "weather", lambda m: m.group(1) or ""),
    (r"^(?:новости|что нового в мире|что в новостях)$", "news", ""),
    (r"^(?:утренняя сводка|доброе утро|сводка дня)$", "brief", ""),
    (r"^(?:запомни что|запомни,? что)\s+(.+)$", "remember", 1),
    (r"^запомни\s+((?:я|мой|моя|мое|моё|мои|меня)\s.+)$", "remember", 1),
    (r"^запомни это как режим\s+(.+)$", "scenario_save", 1),
    (r"^(?:создай|сделай) режим\s+(\S+)\s*:?\s*(.+)$", "scenario_make", lambda m: m.group(1) + "|" + m.group(2)),
    (r"^(?:какие (?:у меня )?(?:режимы|сценарии)|покажи режимы)$", "scenario_list", ""),
    (r"^удали (?:режим|сценарий)\s+(.+)$", "scenario_del", 1),
    (r"^(?:запусти |включи |активируй )?(?:режим|сценарий)\s+(.+)$", "scenario", 1),
    (r"^(?:запомни|заметка|запиши|note|remember)\s+(.+)$", "note", 1),
    (r"^(?:что ты помнишь обо мне|что ты знаешь обо мне|что ты помнишь)$", "facts_list", ""),
    (r"^(?:забудь все|очисти память)$", "forget_all", ""),
    (r"^забудь что\s+(.+)$", "forget", 1),
    (r"^(?:напомни|напомнить)(?: мне)?\s+(.+)$", "remind", 1),
    (r"^(?:поставь )?таймер(?: на)?\s+(.+)$", "timer", 1),
    (r"^(?:поставь )?будильник(?: на)?\s+(.+)$", "alarm", 1),
    (r"^разбуди меня\s+(.+)$", "alarm", 1),
    (r"^(?:какие (?:у меня )?(?:напоминания|таймеры|будильники)|покажи напоминания)$", "reminders_list", ""),
    (r"^отмени (?:все )?(?:напоминания|таймеры|будильники)$", "reminders_clear", ""),
    (r"^(?:добавь в список дел|добавь задачу|в список дел)\s+(.+)$", "todo_add", 1),
    (r"^(?:что в списке дел|мои дела|список дел|покажи дела)$", "todo_list", ""),
    (r"^(?:выполнил|сделал|вычеркни)\s+(.+)$", "todo_done", 1),
    (r"^очисти список дел$", "todo_clear", ""),
    (r"^добавь в календарь\s+(.+)$", "calendar", 1),
    (r"^(?:напиши письмо|новое письмо)\s*(.*)$", "mail", 1),
    (r"^(?:будь|говори|смени характер на)\s+(?:более\s+)?(дружелюбно|друг|строго|строгим|строгий|весело|веселым|весёлым|весёлый|как дворецкий|дворецким|дворецкий)$",
     "persona", 1),
]
_COMPILED = [(re.compile(p), n, a) for p, n, a in TABLE]
_COMPILED_I = [re.compile(p, re.I) for p, n, a in TABLE]
# these rules carry text that must keep its case and punctuation (passwords, messages, typed text)
CASE_RULES = {"type", "password", "tg_send", "telegram", "note"}
# these rules swallow everything after the verb, so the sentence must not be cut at "и"
TEXTY = {"type", "password", "tg_send", "telegram", "note", "search", "youtube", "music", "remind", "remember",
         "todo_add", "calendar", "mail", "scenario_make"}


def norm_keep(t, cfg):
    """Like norm(), but keeps case and punctuation of the text itself."""
    t = re.sub(r"\s+", " ", t).strip()
    name = cfg["name"].strip()
    for _ in range(2):
        if name:
            t = re.sub(r"^(?:(?:привет|эй|слушай|hey|hi|ok|ну)[ ,]+)?%s[ ,]+" % re.escape(name), "", t, flags=re.I)
        t = re.sub(r"^(?:привет|ну|а|эй|слушай|hey|hi|ok|пожалуйста|please)[ ,]+", "", t, flags=re.I)
    t = re.sub(r"[ ,]+(?:пожалуйста|please)$", "", t, flags=re.I)
    return t.strip()


def match(text, cfg):
    """Returns (action, arg) for a command that needs no AI, or None."""
    t = norm(text, cfg)
    if not t:
        return None
    for rx, fn in PLUGIN_CMDS:
        try:
            m = re.match(rx, t)
        except Exception:
            continue
        if m:
            return "__plugin", (fn, m)
    tk = None
    for (rx, name, a), rxi in zip(_COMPILED, _COMPILED_I):
        m = rx.match(t)
        if not m:
            continue
        if name in CASE_RULES:
            if tk is None:
                tk = norm_keep(text, cfg)
            m2 = rxi.match(tk)
            if m2:
                m = m2
        arg = a(m) if callable(a) else (m.group(a) if isinstance(a, int) else a)
        arg = (arg or "").strip()
        if name == "open_strict":
            rest = re.sub(r"^(?:сайт|приложение|программу|мне|the|app)\s+", "", arg).strip()
            if resolve(rest, cfg) is None:
                continue
            return "open_app", rest
        return name, arg
    return None


_CHAIN = re.compile(r"\s+(?:и\s+затем|и\s+потом|а\s+потом|и\s+после\s+этого|после\s+этого|потом|затем|и)\s+", re.I)


def match_chain(text, cfg):
    """Splits "открой телеграм и введи пароль 123" into steps. Returns a list of (action, arg);
    one element for a single command, [] if the phrase is not understood without the AI."""
    whole = match(text, cfg)
    if whole and whole[0] in TEXTY:
        return [whole]
    parts = [p.strip() for p in _CHAIN.split(norm_keep(text, cfg)) if p.strip()]
    if len(parts) > 1:
        steps = []
        for p in parts:
            h = match(p, cfg)
            if not h:
                steps = []
                break
            steps.append(h)
        if steps:
            return steps
    return [whole] if whole else []
