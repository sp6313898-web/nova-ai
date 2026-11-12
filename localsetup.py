import os
import re
import zipfile

from .config import data_dir

UA = {"User-Agent": "NovaAgent/1.0"}
API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"

# (label, huggingface repo, vision)
MODELS = [
    ("Qwen2.5 1.5B - быстрая, около 1 ГБ (для старых ПК)", "bartowski/Qwen2.5-1.5B-Instruct-GGUF", False),
    ("Llama 3.2 1B - самая лёгкая, около 0.8 ГБ", "bartowski/Llama-3.2-1B-Instruct-GGUF", False),
    ("Gemma 3 1B - хороший русский, около 0.8 ГБ", "ggml-org/gemma-3-1b-it-GGUF", False),
    ("Qwen2.5 3B - умнее, около 2 ГБ", "bartowski/Qwen2.5-3B-Instruct-GGUF", False),
    ("SmolVLM 500M - VISION, лёгкая, около 0.8 ГБ", "ggml-org/SmolVLM-500M-Instruct-GGUF", True),
    ("Gemma 3 4B - VISION, умная, около 3.5 ГБ", "ggml-org/gemma-3-4b-it-GGUF", True),
]


def _base():
    d = data_dir()
    try:
        d.encode("ascii")
        return d
    except UnicodeEncodeError:
        # llama.cpp can fail on non-ASCII Windows user names, so use a plain ASCII folder
        for root in (os.environ.get("PUBLIC"), os.environ.get("ProgramData"), "C:\\"):
            if root:
                p = os.path.join(root, "NovaAgent")
                try:
                    os.makedirs(p, exist_ok=True)
                    return p
                except Exception:
                    continue
    return d


def llama_dir():
    p = os.path.join(_base(), "llama")
    os.makedirs(p, exist_ok=True)
    return p


def models_dir():
    p = os.path.join(_base(), "models")
    os.makedirs(p, exist_ok=True)
    return p


def find_model():
    best = ""
    for f in sorted(os.listdir(models_dir())):
        if f.lower().endswith(".gguf") and "mmproj" not in f.lower():
            best = os.path.join(models_dir(), f)
    return best


def find_server():
    for root, _, files in os.walk(llama_dir()):
        if "llama-server.exe" in files:
            return os.path.join(root, "llama-server.exe")
    return ""


def _feature(n):
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(n))
    except Exception:
        return True


def download(url, dest, prog, label):
    import requests
    tmp = dest + ".part"
    with requests.get(url, stream=True, headers=UA, timeout=(15, 60), allow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(tmp, "wb") as f:
            for ch in r.iter_content(256 * 1024):
                f.write(ch)
                done += len(ch)
                prog(done, total, "%s: %.1f / %.1f МБ" % (label, done / 1048576.0, total / 1048576.0))
    os.replace(tmp, dest)
    return dest


def install_llama(prog):
    import requests
    srv = find_server()
    if srv:
        return srv
    prog(0, 0, "Ищу последнюю версию llama.cpp")
    r = requests.get(API, headers=UA, timeout=20)
    r.raise_for_status()
    names = {a["name"]: a["browser_download_url"] for a in r.json().get("assets", [])
             if a["name"].endswith(".zip") and "cudart" not in a["name"]}
    order = []
    if not _feature(40):  # no AVX2: prefer legacy builds if the release still has them
        order.append(r"bin-win-avx-x64\.zip$" if _feature(39) else r"bin-win-noavx-x64\.zip$")
    order += [r"bin-win-cpu-x64\.zip$", r"bin-win-avx2-x64\.zip$", r"bin-win-avx-x64\.zip$",
              r"bin-win-noavx-x64\.zip$"]
    name = url = None
    for pat in order:
        for n, u in names.items():
            if re.search(pat, n):
                name, url = n, u
                break
        if name:
            break
    if not name:
        raise RuntimeError("В последнем релизе llama.cpp нет Windows CPU архива. Скачайте вручную.")
    z = os.path.join(llama_dir(), name)
    download(url, z, prog, "llama.cpp")
    prog(1, 1, "Распаковка")
    with zipfile.ZipFile(z) as zf:
        zf.extractall(llama_dir())
    os.remove(z)
    srv = find_server()
    if not srv:
        raise RuntimeError("В архиве нет llama-server.exe")
    return srv


def _pick(files, prefs, mm):
    names = [f["path"] for f in files if f.get("type") == "file" and f["path"].lower().endswith(".gguf")
             and "-of-" not in f["path"].lower()]
    cand = [n for n in names if ("mmproj" in n.lower()) == mm]
    for p in prefs:
        for n in cand:
            if p in n.lower():
                return n
    return cand[0] if cand else None


def install_model(idx, prog):
    import requests
    label, repo, vision = MODELS[idx]
    prog(0, 0, "Ищу файлы модели")
    r = requests.get("https://huggingface.co/api/models/%s/tree/main" % repo, headers=UA, timeout=20)
    r.raise_for_status()
    files = r.json()
    main = _pick(files, ["q4_k_m", "q4_k_s", "q8_0", "f16"], False)
    if not main:
        raise RuntimeError("В репозитории %s нет подходящего .gguf" % repo)
    out = []
    todo = [("Модель", main)]
    if vision:
        mm = _pick(files, ["q8_0", "f16", "bf16"], True)
        if not mm:
            raise RuntimeError("Нет файла mmproj для vision")
        todo.append(("Vision проектор", mm))
    for lab, path in todo:
        dest = os.path.join(models_dir(), os.path.basename(path))
        if not os.path.isfile(dest):
            download("https://huggingface.co/%s/resolve/main/%s" % (repo, path), dest, prog, lab)
        out.append(dest)
    return out[0], (out[1] if len(out) > 1 else "")


VOSK = {"ru": "vosk-model-small-ru-0.22", "en": "vosk-model-small-en-us-0.15"}


def vosk_ready(cfg):
    p = cfg["vosk_path"]
    return bool(p) and os.path.isdir(p) and bool(os.listdir(p))


def install_vosk(lang, prog):
    name = VOSK.get(lang, VOSK["en"])
    dest = os.path.join(models_dir(), "vosk")
    target = os.path.join(dest, name)
    if os.path.isdir(target) and os.listdir(target):
        return target
    os.makedirs(dest, exist_ok=True)
    z = os.path.join(dest, name + ".zip")
    download("https://alphacephei.com/vosk/models/%s.zip" % name, z, prog, "Распознавание речи")
    prog(1, 1, "Распаковка")
    with zipfile.ZipFile(z) as zf:
        zf.extractall(dest)
    os.remove(z)
    if not os.path.isdir(target):
        raise RuntimeError("Не удалось распаковать модель Vosk")
    return target
