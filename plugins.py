import glob
import importlib.util
import os

from .config import data_dir

EXAMPLE = '''# Плагин Nova. Положите .py файлы в эту папку, они подхватываются при запуске.
# COMMANDS: список (регулярка, функция). Регулярка проверяется на распознанную фразу (строчными буквами).
# ACTIONS: словарь имя -> функция, ИИ может вызывать их тегом [[имя|аргумент]].
# Функции возвращают текст, который ассистент произнесёт.
import webbrowser


def hello(match, cfg):
    return "Привет из плагина"


def open_site(arg, cfg):
    webbrowser.open("https://" + arg)
    return "Открываю " + arg


COMMANDS = [(r"^скажи привет из плагина$", hello)]
ACTIONS = {"site": open_site}
'''


def plugins_dir():
    p = os.path.join(data_dir(), "plugins")
    os.makedirs(p, exist_ok=True)
    if not glob.glob(os.path.join(p, "*.py")):
        with open(os.path.join(p, "example_plugin.py"), "w", encoding="utf-8") as f:
            f.write(EXAMPLE)
    return p


def load():
    commands, actions = [], {}
    for f in glob.glob(os.path.join(plugins_dir(), "*.py")):
        try:
            spec = importlib.util.spec_from_file_location("nova_plugin_" + os.path.basename(f)[:-3], f)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            commands += list(getattr(m, "COMMANDS", []))
            actions.update(getattr(m, "ACTIONS", {}))
        except Exception:
            continue
    return commands, actions
