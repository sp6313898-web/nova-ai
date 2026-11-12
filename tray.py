from .config import resource_path


def start_tray(app):
    try:
        import pystray
        from PIL import Image
        img = Image.open(resource_path("assets/icon.ico"))
    except Exception:
        return None
    menu = pystray.Menu(
        pystray.MenuItem("Открыть", lambda i, it: app.root.after(0, app.show), default=True),
        pystray.MenuItem("Тихий режим", lambda i, it: app.root.after(0, app.toggle_quiet),
                         checked=lambda it: bool(app.cfg["quiet"])),
        pystray.MenuItem("Выход", lambda i, it: app.root.after(0, app.quit)))
    icon = pystray.Icon("Nova", img, "Nova", menu)
    try:
        icon.run_detached()
    except Exception:
        return None
    return icon
