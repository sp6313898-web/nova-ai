"""Reliable control of desktop apps: window waiting/focus, Steam (library, games, accounts), Telegram.

Every function returns a short text for the assistant to say. The text describes what REALLY happened:
"Не ..." means the action failed, so the assistant never claims success it did not achieve."""
import difflib
import glob
import os
import re
import subprocess
import time

from . import pc

# name -> (window title parts, process names, launch target)
WINDOWED = {
    "telegram": (["telegram"], ["telegram.exe"], "tg://"),
    "steam": (["steam"], ["steamwebhelper.exe", "steam.exe"], "steam://open/main"),
    "discord": (["discord"], ["discord.exe"], "discord:"),
    "spotify": (["spotify"], ["spotify.exe"], "spotify:"),
}
ALIAS = {"телеграм": "telegram", "телеграмм": "telegram", "тг": "telegram", "стим": "steam",
         "дискорд": "discord", "спотифай": "spotify"}
LAST = [""]  # the app the user worked with most recently, for "log in to account X"

# Russian spoken names -> names used in Steam
GAME_ALIASES = {
    "дота": "dota 2", "доту": "dota 2", "дота 2": "dota 2", "доту 2": "dota 2",
    "кс": "counter-strike", "кс го": "counter-strike", "контру": "counter-strike", "контр страйк": "counter-strike",
    "контер страйк": "counter-strike", "кс 2": "counter-strike 2", "кска": "counter-strike",
    "гта": "grand theft auto", "гта 5": "grand theft auto v", "майнкрафт": "minecraft",
    "террарию": "terraria", "террария": "terraria", "терарию": "terraria", "терария": "terraria",
    "кс2": "counter-strike 2", "cs2": "counter-strike 2", "тф2": "team fortress 2", "ведьмак": "the witcher", "ведьмака": "the witcher",
    "киберпанк": "cyberpunk 2077", "рейдж": "rage", "пабг": "pubg", "апекс": "apex legends",
    "раст": "rust", "раста": "rust", "тф 2": "team fortress 2", "лефт 4 дед": "left 4 dead 2",
    "готику": "gothic", "скайрим": "skyrim", "фоллаут": "fallout", "ведьмак 3": "the witcher 3",
    "сталкер": "s.t.a.l.k.e.r.", "хроники": "chronicles", "доту два": "dota 2", "дота два": "dota 2",
}


def canon_app(name):
    n = name.strip().lower()
    return ALIAS.get(n, n)


def _wait_gone(procs, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not pc.process_running(*procs):
            return True
        time.sleep(0.5)
    return False


def ensure_app(name, timeout=12.0, launch=True):
    """Starts the app if needed, waits for its window and brings it to the front.
    Returns (ok, text)."""
    key = canon_app(name)
    if key not in WINDOWED:
        return True, ""
    LAST[0] = key
    titles, procs, target = WINDOWED[key]
    h = pc.find_window(titles, procs)
    if not h and launch:
        try:
            os.startfile(target)
        except Exception as e:
            return False, "Не получилось открыть %s: %s" % (name, e)
    if pc.wait_window(titles, procs, timeout):
        return True, ""
    return False, "Не дождался окна %s, оно не появилось за %d секунд" % (name, int(timeout))


# ======================= Steam =======================
def steam_path():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        try:
            p = winreg.QueryValueEx(k, "SteamPath")[0]
        finally:
            winreg.CloseKey(k)
        if p and os.path.isdir(p):
            return os.path.normpath(p)
    except Exception:
        pass
    for p in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        if os.path.isdir(p):
            return p
    return ""


def vdf_pairs(text):
    """All "key" "value" pairs of a Valve KeyValues file, in order."""
    return re.findall(r'"([^"]*)"\s+"((?:[^"\\]|\\.)*)"', text)


def steam_libraries(root=None):
    root = root or steam_path()
    libs = [root] if root else []
    f = os.path.join(root, "steamapps", "libraryfolders.vdf") if root else ""
    if f and os.path.isfile(f):
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                for k, v in vdf_pairs(fh.read()):
                    if k == "path":
                        p = os.path.normpath(v.replace("\\\\", "\\"))
                        if p not in libs and os.path.isdir(p):
                            libs.append(p)
        except Exception:
            pass
    return libs


def parse_manifest(text):
    d = dict(vdf_pairs(text))
    return d.get("appid", ""), d.get("name", "")


def steam_games(root=None):
    games = []
    for lib in steam_libraries(root):
        for f in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
            try:
                with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                    appid, name = parse_manifest(fh.read())
                if appid.isdigit() and name:
                    games.append((appid, name))
            except Exception:
                continue
    return games


def _norm_game(s):
    s = s.lower().replace("ё", "е")
    s = re.sub(r"[^\w\s.]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def best_game(query, games):
    """Fuzzy search among installed games. Returns (appid, name) or None."""
    q = _norm_game(query)
    if not q:
        return None
    q = GAME_ALIASES.get(q, q)
    best, score = None, 0.0
    for appid, name in games:
        n = _norm_game(name)
        if q == n:
            s = 1.0
        elif n.startswith(q) or q in n:
            s = 0.9 - min(0.3, (len(n) - len(q)) / 100.0)
        elif q.startswith(n):
            s = 0.75
        else:
            s = difflib.SequenceMatcher(None, q, n).ratio() * 0.8
            # every word of the query appears in the name
            if all(w in n for w in q.split()):
                s = max(s, 0.7)
        if s > score:
            best, score = (appid, name), s
    return best if score >= 0.55 else None


def steam_open(what="library"):
    """Opens Steam on a page: library / store / friends / main."""
    ok, err = ensure_app("steam", 20)
    if not ok:
        return err
    uri = {"library": "steam://nav/games", "store": "steam://nav/store", "friends": "steam://open/friends",
           "main": "steam://open/main", "downloads": "steam://nav/downloads"}.get(what, "steam://nav/games")
    try:
        os.startfile(uri)
    except Exception as e:
        return "Не получилось открыть страницу Steam: %s" % e
    time.sleep(1.0)
    if what == "library":
        return "Открыл библиотеку Steam"
    return "Открыл Steam"


def steam_play(query):
    root = steam_path()
    if not root:
        return "Не нашёл Steam на этом компьютере"
    games = steam_games(root)
    if not games:
        return "Не нашёл ни одной установленной игры в Steam"
    hit = best_game(query, games)
    if not hit:
        try:
            os.startfile("steam://nav/games")
        except Exception:
            pass
        names = ", ".join(n for _, n in games[:6])
        return "Не нашёл игру %s среди установленных. Например: %s" % (query, names)
    appid, name = hit
    try:
        os.startfile("steam://rungameid/" + appid)
    except Exception as e:
        return "Не получилось запустить %s: %s" % (name, e)
    return "Запускаю %s" % name


def steam_accounts(root=None):
    root = root or steam_path()
    f = os.path.join(root, "config", "loginusers.vdf") if root else ""
    out = []
    if not f or not os.path.isfile(f):
        return out
    with open(f, "r", encoding="utf-8", errors="ignore") as fh:
        text = fh.read()
    for m in re.finditer(r'"(\d{16,20})"\s*\{(.*?)\}', text, re.S):
        d = dict(vdf_pairs(m.group(2)))
        out.append({"id": m.group(1), "account": d.get("AccountName", ""), "persona": d.get("PersonaName", ""),
                    "remember": d.get("RememberPassword", "0") == "1",
                    "recent": d.get("MostRecent", "0") == "1"})
    return out


def steam_active_user():
    """Steam account id (32-bit) of the logged-in user, 0 if nobody is logged in."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess")
        try:
            return int(winreg.QueryValueEx(k, "ActiveUser")[0])
        finally:
            winreg.CloseKey(k)
    except Exception:
        return 0


def _wait_login(timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if steam_active_user():
            return True
        time.sleep(1.0)
    return False


def pick_account(name, accounts):
    n = name.strip().lower()
    for a in accounts:
        if n in (a["account"].lower(), a["persona"].lower()):
            return a
    for a in accounts:
        if n and (n in a["account"].lower() or n in a["persona"].lower()):
            return a
    names = [a["account"].lower() for a in accounts] + [a["persona"].lower() for a in accounts]
    close = difflib.get_close_matches(n, names, 1, 0.6)
    if close:
        for a in accounts:
            if close[0] in (a["account"].lower(), a["persona"].lower()):
                return a
    return None


def steam_login(name):
    """Switches Steam to a saved account by writing AutoLoginUser and restarting Steam.
    This works only for accounts that were logged in once with "Remember my password"."""
    root = steam_path()
    if not root:
        return "Не нашёл Steam на этом компьютере"
    accs = steam_accounts(root)
    acc = pick_account(name, accs)
    exe = os.path.join(root, "steam.exe")
    if not acc:
        ensure_app("steam", 15)
        if accs:
            return "Не нашёл аккаунт %s. Сохранённые: %s" % (
                name, ", ".join(a["persona"] or a["account"] for a in accs))
        return "Не нашёл сохранённых аккаунтов Steam. Войдите один раз вручную с галочкой Запомнить пароль"
    label = acc["persona"] or acc["account"]
    # already in this account?
    try:
        if steam_active_user() and (steam_active_user() == int(acc["id"]) - 76561197960265728):
            ensure_app("steam", 10)
            return "Вы уже в аккаунте %s" % label
    except Exception:
        pass
    if not acc["remember"]:
        ensure_app("steam", 15)
        return ("Не могу войти в %s сам: Steam не сохранил пароль. Войдите один раз вручную с галочкой "
                "Запомнить пароль, потом я смогу переключаться" % label)
    try:
        import winreg
        k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        try:
            winreg.SetValueEx(k, "AutoLoginUser", 0, winreg.REG_SZ, acc["account"])
            winreg.SetValueEx(k, "RememberPassword", 0, winreg.REG_DWORD, 1)
        finally:
            winreg.CloseKey(k)
    except Exception as e:
        return "Не получилось записать настройки входа Steam: %s" % e
    if pc.process_running("steam.exe"):
        try:
            subprocess.Popen([exe, "-shutdown"], creationflags=0x08000000)
        except Exception as e:
            return "Не получилось закрыть Steam: %s" % e
        if not _wait_gone(("steam.exe", "steamwebhelper.exe"), 30):
            return "Не получилось закрыть Steam, чтобы сменить аккаунт"
    try:
        subprocess.Popen([exe], creationflags=0x08000000)
    except Exception as e:
        return "Не получилось запустить Steam: %s" % e
    if not _wait_login(60):
        return "Не дождался входа в аккаунт %s. Возможно, нужен код Steam Guard" % label
    pc.wait_window(*WINDOWED["steam"][:2], timeout=15)
    return "Вошёл в аккаунт %s" % label


# ======================= Telegram =======================
def tg_send(contact, text):
    """Sends a message from the user's own Telegram Desktop. contact: @username, a name,
    or empty / "избранное" for Saved Messages."""
    if not text.strip():
        return "Не понял, что отправить"
    ok, err = ensure_app("telegram", 15)
    if not ok:
        return err
    c = contact.strip()
    low = c.lower()
    user = c.lstrip("@")
    if low in ("мне", "себе", "избранное", "избранные", "saved", "saved messages", ""):
        pc.press("ctrl+k")
        time.sleep(0.6)
        pc.type_text("Избранное")
        time.sleep(1.0)
        pc.press("enter")
    elif re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", user):
        os.startfile("tg://resolve?domain=" + user)
        time.sleep(2.0)
    else:
        pc.press("ctrl+k")  # quick switcher of Telegram Desktop
        time.sleep(0.6)
        pc.type_text(c)
        time.sleep(1.2)
        pc.press("enter")
    time.sleep(0.8)
    pc.wait_window(*WINDOWED["telegram"][:2], timeout=5)
    pc.type_text(text)
    time.sleep(0.2)
    pc.press("enter")
    return "Отправил сообщение %s" % (("контакту " + c) if c and low not in ("мне", "себе") else "в избранное")
