import datetime
import json
import os
import re
import threading
import time

from .config import data_dir

ONES = {"ноль": 0, "один": 1, "одна": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
        "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "одиннадцать": 11,
        "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16,
        "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19}
TENS = {"двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70,
        "восемьдесят": 80, "девяносто": 90}
HUND = {"сто": 100, "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500, "шестьсот": 600,
        "семьсот": 700, "восемьсот": 800, "девятьсот": 900}


def digitize(text):
    """Turns Russian number words (as Vosk writes them) into digits."""
    out, cur, last = [], None, 0
    for w in text.split():
        kind = 3 if w in HUND else 2 if w in TENS else 1 if w in ONES else 0
        if kind:
            val = HUND.get(w) or TENS.get(w) or ONES.get(w)
            if cur is not None and kind < last:
                cur += val
            else:
                if cur is not None:
                    out.append(str(cur))
                cur = val
            last = kind
        else:
            if cur is not None:
                out.append(str(cur))
                cur, last = None, 0
            out.append(w)
    if cur is not None:
        out.append(str(cur))
    return " ".join(out)


UNIT = r"(?:сек\w*|мин\w*|час\w*|sec\w*|min\w*|hour\w*)"


def _clean(rest):
    rest = re.sub(r"\s+", " ", rest).strip(" ,.")
    return re.sub(r"^(?:что|чтобы|о том что|про|мне|me to|to)\s+", "", rest).strip()


def parse_when(t, alarm=False, now=None):
    """Returns (due_timestamp, leftover_text) or None."""
    now = now or time.time()
    t = digitize(t.lower())
    m = re.search(r"(?:через|in)\s+(полчаса|час|\d+\s*%s)" % UNIT, t)
    if not m and not alarm:
        m = re.search(r"\bна\s+(полчаса|час|\d+\s*%s)" % UNIT, t)
    if m:
        s = m.group(1)
        if s == "полчаса":
            sec = 1800
        elif s == "час":
            sec = 3600
        else:
            n = int(re.match(r"\d+", s).group())
            u = s[len(str(n)):].strip()
            sec = n * (1 if u.startswith(("сек", "sec")) else 60 if u.startswith(("мин", "min")) else 3600)
        return now + sec, _clean(t[:m.start()] + " " + t[m.end():])
    pre = r"(?:\bв|\bat|\bна)" if alarm else r"(?:\bв|\bat)"
    m = re.search(pre + r"\s+(\d{1,2})(?:[:. ](\d{2}))?\s*(?:час\w*)?\s*(утра|вечера|дня|ночи|am|pm)?", t)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap in ("вечера", "дня", "pm") and h < 12:
        h += 12
    if ap == "ночи" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        return None
    d = datetime.datetime.fromtimestamp(now).replace(hour=h, minute=mi, second=0, microsecond=0)
    if "завтра" in t:
        d += datetime.timedelta(days=1)
    elif d.timestamp() <= now:
        d += datetime.timedelta(days=1)
    rest = (t[:m.start()] + " " + t[m.end():]).replace("завтра", " ")
    return d.timestamp(), _clean(rest)


def _p(n):
    return os.path.join(data_dir(), n)


def _load(n, default):
    try:
        with open(_p(n), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(n, data):
    try:
        with open(_p(n), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.facts = _load("memory.json", [])
        self.reminders = _load("reminders.json", [])
        self.todo = _load("todo.json", [])
        self.scen = _load("scenarios.json", {})
        self.usage = _load("usage.json", {})

    # facts
    def remember(self, text):
        text = text.strip()
        if text and text not in self.facts:
            self.facts.append(text)
            self.facts = self.facts[-60:]
            _save("memory.json", self.facts)

    def forget(self, what=None):
        with self.lock:
            if not what:
                self.facts = []
            else:
                self.facts = [f for f in self.facts if what.lower() not in f.lower()]
            _save("memory.json", self.facts)

    # reminders
    def add_reminder(self, due, text, kind="reminder"):
        with self.lock:
            self.reminders.append({"id": int(time.time() * 1000), "due": due, "text": text, "kind": kind})
            _save("reminders.json", self.reminders)

    def due(self):
        now = time.time()
        with self.lock:
            out = [r for r in self.reminders if r["due"] <= now]
            if out:
                self.reminders = [r for r in self.reminders if r["due"] > now]
                _save("reminders.json", self.reminders)
        return out

    def clear_reminders(self):
        with self.lock:
            self.reminders = []
            _save("reminders.json", self.reminders)

    # todo
    def todo_add(self, text):
        self.todo.append({"text": text.strip(), "done": False})
        _save("todo.json", self.todo)

    def todo_done(self, text):
        n = 0
        for t in self.todo:
            if not t["done"] and text.lower() in t["text"].lower():
                t["done"] = True
                n += 1
        _save("todo.json", self.todo)
        return n

    def todo_open(self):
        return [t["text"] for t in self.todo if not t["done"]]

    def todo_clear(self):
        self.todo = []
        _save("todo.json", self.todo)

    # scenarios
    def save_scenario(self, name, steps):
        self.scen[name.strip().lower()] = steps
        _save("scenarios.json", self.scen)

    def find_scenario(self, name):
        n = name.strip().lower()
        if n in self.scen:
            return n, self.scen[n]
        for k, v in self.scen.items():
            if n and (n in k or k in n):
                return k, v
        return None, None

    def del_scenario(self, name):
        k, _ = self.find_scenario(name)
        if k:
            del self.scen[k]
            _save("scenarios.json", self.scen)
        return bool(k)

    # usage patterns for proactive suggestions
    def log_usage(self, action, arg):
        if action not in ("open_app", "open_url"):
            return
        today = datetime.date.today().isoformat()
        h = str(datetime.datetime.now().hour)
        u = self.usage.setdefault("%s|%s" % (action, arg), {"hours": {}, "sugg": ""})
        days = u["hours"].setdefault(h, [])
        if today not in days:
            days.append(today)
            u["hours"][h] = days[-10:]
        _save("usage.json", self.usage)

    def suggestion(self):
        now = datetime.datetime.now()
        today = now.date().isoformat()
        for key, u in self.usage.items():
            days = u["hours"].get(str(now.hour), [])
            if len(days) >= 3 and today not in days and u.get("sugg") != today:
                u["sugg"] = today
                _save("usage.json", self.usage)
                a, arg = key.split("|", 1)
                return a, arg
        return None
