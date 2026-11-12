import queue
import re
import threading
import time

from .llm import LLM, NO_KEY, PROVIDERS

TAG = re.compile(r"\[\[[^\]]*\]\]")
KEYWORDS = ("объясни", "почему", "сравни", "придумай", "напиши", "подумай", "реши", "посоветуй", "расскажи",
            "explain", "why", "compare", "write", "think", "solve")


def cloud_members(cfg):
    return [p for p in PROVIDERS if p not in NO_KEY and p != "local" and cfg["keys"].get(p)]


def members(cfg):
    avail = cloud_members(cfg)
    sel = [p for p in cfg["council"] if p in avail]
    return sel or avail


def needs_council(text):
    t = text.lower()
    return len(t.split()) >= 12 or any(k in t for k in KEYWORDS)


def _one(cfg, prov, messages, image, out):
    try:
        out[prov] = "".join(LLM(cfg, provider=prov).stream(messages, image)).strip()
    except Exception:
        pass


def gather(cfg, messages, image=None, on_status=None):
    mem = members(cfg)
    out = {}
    ths = [threading.Thread(target=_one, args=(cfg, p, messages, image, out), daemon=True) for p in mem]
    for t in ths:
        t.start()
    t0 = time.time()
    while time.time() - t0 < 15 and len(out) < len(mem):
        if len(out) >= 2 and time.time() - t0 > 5:
            break
        time.sleep(0.05)
    return [(p, t) for p, t in out.items() if t]


def synth_messages(base, cands):
    q = base[-1]["content"]
    drafts = "\n\n".join("[%s]\n%s" % (chr(65 + i), TAG.sub("", t)) for i, (_, t) in enumerate(cands))
    prompt = ("%s\n\nDrafts from other AI assistants:\n%s\n\nUsing the drafts, give the single best final answer. "
              "Fix mistakes, stay concise and easy to say aloud. Use action tags only if the user asked for an "
              "action." % (q, drafts))
    return base[:-1] + [{"role": "user", "content": prompt}]


def race(cfg, messages, image=None):
    mem = members(cfg)
    q = queue.Queue()
    llms = {}

    def run(p):
        l = LLM(cfg, provider=p)
        llms[p] = l
        try:
            for c in l.stream(messages, image):
                q.put((p, c))
            q.put((p, None))
        except Exception as e:
            q.put((p, e))
    for p in mem:
        threading.Thread(target=run, args=(p,), daemon=True).start()
    winner, alive = None, len(mem)
    while alive > 0:
        p, c = q.get()
        if isinstance(c, Exception):
            alive -= 1
            if p == winner:
                raise c
            continue
        if winner is None:
            if c is None:
                alive -= 1
                continue
            winner = p
            for o, l in llms.items():
                if o != p:
                    l.cancel()
        if p != winner:
            continue
        if c is None:
            return
        yield c
    if winner is None:
        raise RuntimeError("Ни одна модель совета не ответила")


def fallback(cfg, primary, messages, image=None):
    order = [None] + [p for p in cloud_members(cfg) if p != cfg["provider"]]
    last = None
    for p in order:
        llm = primary if p is None else LLM(cfg, provider=p)
        got = False
        try:
            for c in llm.stream(messages, image):
                got = True
                yield c
            return
        except Exception as e:
            if got or len(order) == 1:
                raise
            last = e
    raise last
