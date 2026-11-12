import datetime
import os
import urllib.parse
import webbrowser
import xml.etree.ElementTree as ET

WCODE = {0: "ясно", 1: "малооблачно", 2: "переменная облачность", 3: "пасмурно", 45: "туман", 48: "туман",
         51: "морось", 53: "морось", 55: "морось", 61: "дождь", 63: "дождь", 65: "сильный дождь",
         71: "снег", 73: "снег", 75: "сильный снег", 80: "ливень", 81: "ливень", 82: "сильный ливень",
         95: "гроза", 96: "гроза с градом", 99: "гроза с градом"}


def _geo(city):
    import requests
    if city:
        c = city.strip()
        for name in (c, c[:-1] + "а", c[:-1] + "я", c[:-1], c[:-2]):
            if len(name) < 3:
                continue
            r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                             params={"name": name, "count": 1, "language": "ru"}, timeout=10).json()
            res = (r.get("results") or [None])[0]
            if res:
                return res["latitude"], res["longitude"], res.get("name", city)
        raise RuntimeError("Город не найден")
    j = requests.get("https://ipapi.co/json/", timeout=10).json()
    return j["latitude"], j["longitude"], j.get("city", "")


def weather(city, cfg):
    import requests
    lat, lon, name = _geo(city or cfg.get("city", ""))
    j = requests.get("https://api.open-meteo.com/v1/forecast",
                     params={"latitude": lat, "longitude": lon, "timezone": "auto",
                             "current": "temperature_2m,wind_speed_10m,weather_code"}, timeout=10).json()
    c = j["current"]
    return "%s: %d градусов, %s, ветер %d километров в час" % (
        name or "Сейчас", round(c["temperature_2m"]), WCODE.get(c["weather_code"], "без осадков"),
        round(c["wind_speed_10m"]))


def news(cfg, n=4):
    import requests
    url = ("https://news.google.com/rss?hl=ru&gl=RU&ceid=RU:ru" if cfg["lang"] == "ru"
           else "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en")
    root = ET.fromstring(requests.get(url, timeout=10).content)
    titles = [(i.findtext("title") or "").rsplit(" - ", 1)[0] for i in root.iter("item")][:n]
    return "Новости. " + ". ".join(titles)


def telegram(text, cfg):
    import requests
    tok, chat = cfg.get("tg_token", ""), cfg.get("tg_chat", "")
    if not tok or not chat:
        return "Укажите токен бота и чат в настройках, вкладка Интеграции"
    r = requests.post("https://api.telegram.org/bot%s/sendMessage" % tok, json={"chat_id": chat, "text": text},
                      timeout=15)
    return "Отправил" if r.status_code == 200 else "Телеграм ответил ошибкой %d" % r.status_code


def music(query, cfg):
    q = urllib.parse.quote(query)
    svc = cfg.get("music", "youtube")
    if not query:
        return "Что включить?"
    if svc == "spotify":
        os.startfile("spotify:search:" + q)
    elif svc == "ytmusic":
        webbrowser.open("https://music.youtube.com/search?q=" + q)
    else:
        webbrowser.open("https://www.youtube.com/results?search_query=" + q)
    return "Ищу %s" % query


def calendar(title, ts):
    d = datetime.datetime.fromtimestamp(ts)
    e = d + datetime.timedelta(hours=1)
    f = "%Y%m%dT%H%M%S"
    webbrowser.open("https://calendar.google.com/calendar/render?action=TEMPLATE&text=%s&dates=%s/%s" % (
        urllib.parse.quote(title or "Событие"), d.strftime(f), e.strftime(f)))
    return "Открыл календарь с готовым событием, осталось нажать сохранить"


def mail(subject, body=""):
    webbrowser.open("https://mail.google.com/mail/?view=cm&fs=1&su=%s&body=%s" % (
        urllib.parse.quote(subject), urllib.parse.quote(body)))
    return "Открыл новое письмо"


def ha_call(arg, cfg):
    import requests
    url, tok = cfg.get("ha_url", "").rstrip("/"), cfg.get("ha_token", "")
    if not url or not tok:
        return "Умный дом не настроен, вкладка Интеграции"
    parts = [p.strip() for p in arg.split("|")]
    if len(parts) < 2 or "." not in parts[0]:
        return "Не понял команду для дома"
    dom, svc = parts[0].split(".", 1)
    r = requests.post("%s/api/services/%s/%s" % (url, dom, svc), headers={"Authorization": "Bearer " + tok},
                      json={"entity_id": parts[1]}, timeout=10)
    return "Готово" if r.status_code < 300 else "Дом ответил ошибкой %d" % r.status_code


_ha_cache = [0.0, ""]


def ha_entities(cfg):
    import time
    import requests
    url, tok = cfg.get("ha_url", "").rstrip("/"), cfg.get("ha_token", "")
    if not url or not tok:
        return ""
    if time.time() - _ha_cache[0] < 600:
        return _ha_cache[1]
    try:
        r = requests.get(url + "/api/states", headers={"Authorization": "Bearer " + tok}, timeout=8).json()
        rows = ["%s=%s" % (s["entity_id"], s["attributes"].get("friendly_name", ""))
                for s in r if s["entity_id"].split(".")[0] in ("light", "switch", "climate", "cover",
                                                              "media_player", "scene", "script")][:50]
        _ha_cache[:] = [time.time(), "; ".join(rows)]
    except Exception:
        _ha_cache[0] = time.time()
    return _ha_cache[1]
