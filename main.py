import os
import sys
import traceback


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Nova.Agent.1")
    except Exception:
        pass
    try:
        from nova.ui import App
        App().run()
    except Exception:
        from nova.config import data_dir
        msg = traceback.format_exc()
        try:
            with open(os.path.join(data_dir(), "crash.log"), "w", encoding="utf-8") as f:
                f.write(msg)
        except Exception:
            pass
        try:
            import tkinter
            from tkinter import messagebox
            r = tkinter.Tk()
            r.withdraw()
            messagebox.showerror("Nova", msg[-800:])
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
