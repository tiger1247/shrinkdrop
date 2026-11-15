"""ShrinkDrop: convert iPhone HEIC photos to JPG and shrink photos and videos. Windows 10/11.

    pythonw main.py [files...]          open the window with these files queued
    pythonw main.py --go [files...]     ...and start right away (right-click menu, Send To, Share)
    python  main.py --uninstall [--quiet]
"""
import os
import queue
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import core  # noqa: E402

PORT = 47613
AUTH = b"ShrinkDrop-local"


# ---- single instance ---------------------------------------------------------
def forward_to_running(paths, go):
    from multiprocessing.connection import Client
    try:
        with Client(("127.0.0.1", PORT), authkey=AUTH) as c:
            c.send({"paths": paths, "go": go})
        return True
    except (OSError, EOFError, ValueError):
        return False
    except Exception:
        return False


def listen(callback):
    from multiprocessing.connection import Listener
    try:
        lst = Listener(("127.0.0.1", PORT), authkey=AUTH)
    except OSError:
        return None

    def loop():
        while True:
            try:
                with lst.accept() as c:
                    callback(c.recv())
            except Exception:
                time.sleep(0.2)

    threading.Thread(target=loop, daemon=True).start()
    return lst


# ---- UI ----------------------------------------------------------------------
SIZE_CHOICES = [("Original size", 0), ("4K (3840 px)", 3840), ("Large (2048 px)", 2048),
                ("Medium (1600 px)", 1600), ("Small (1024 px)", 1024)]
QUALITY_CHOICES = [("Best", 92), ("High", 85), ("Smaller file", 72)]
MB_CHOICES = ["8", "10", "16", "25", "50", "100", "200"]
RES_CHOICES = [("Up to 1080p", 1080), ("Up to 720p", 720), ("Up to 480p", 480), ("Keep resolution", 0)]


class App:
    def __init__(self, files, go):
        import tkinter as tk
        from tkinter import ttk
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
            self.root = TkinterDnD.Tk()
            self.dnd = DND_FILES
        except Exception:
            self.root = tk.Tk()
            self.dnd = None
        self.tk, self.ttk = tk, ttk
        self.settings = core.load_settings()
        self.items = {}      # iid -> dict(path, kind, before, after, status, out)
        self.order = []
        self.events = queue.Queue()
        self.worker = None
        self.stop_flag = False
        self.last_out_dir = None

        import storeapi
        self.storeapi = storeapi
        self.lic = storeapi.LicenseWatcher()

        self._build()
        self._apply_settings_to_ui()
        if files:
            self.add_paths(files, go)
        self.root.after(100, self._pump)
        self.root.after(400, self._check_license)
        if os.environ.get("SD_SHOT"):  # testing / store images: "path.png;seconds"
            path, _, secs = os.environ["SD_SHOT"].partition(";")
            self.root.after(int(float(secs or 3) * 1000), lambda: self._shot(path))

    def _shot(self, path):
        from PIL import ImageGrab
        self.root.update()
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        ImageGrab.grab((x, y, x + w, y + h), all_screens=True).save(path)
        if os.environ.get("SD_SHOT_EXIT"):
            self.root.destroy()

    # -- layout ---------------------------------------------------------------
    def _build(self):
        tk, ttk = self.tk, self.ttk
        r = self.root
        r.title(core.APP_NAME)
        self.k = k = max(1.0, r.winfo_fpixels("1i") / 96.0)  # display scaling (1.0 = 100%)
        px = lambda v: int(v * k)  # noqa: E731
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        W, H = min(px(900), int(sw * .9)), min(px(700), int(sh * .88))
        r.geometry(f"{W}x{H}+{(sw - W) // 2}+{max(0, (sh - H) // 2 - px(20))}")
        r.minsize(px(740), px(600))
        try:
            r.iconbitmap(os.path.join(HERE, "app.ico"))
        except Exception:
            pass
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 16))
        style.configure("Sub.TLabel", foreground="#555", font=("Segoe UI", 10))
        style.configure("Big.TButton", font=("Segoe UI Semibold", 11), padding=(18, 6))
        style.configure("Treeview", rowheight=px(24))

        self.banner = tk.Frame(r, bg="#fff4d6")
        self.banner_label = tk.Label(self.banner, bg="#fff4d6", fg="#6b4e00", font=("Segoe UI", 10))
        self.banner_label.pack(side="left", padx=12, pady=6)
        self.banner_btn = ttk.Button(self.banner, text="Buy ShrinkDrop", command=self.storeapi.open_store_page)
        self.banner_btn.pack(side="right", padx=10, pady=4)

        head = ttk.Frame(r, padding=(16, 12, 16, 4))
        head.pack(fill="x")
        ttk.Label(head, text="ShrinkDrop", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="   iPhone HEIC to JPG · shrink photos and videos", style="Sub.TLabel").pack(side="left", pady=(6, 0))

        # drop zone + list
        mid = ttk.Frame(r, padding=(16, 4, 16, 4))
        mid.pack(fill="both", expand=True)
        self.drop = tk.Label(mid, text="Drop photos, videos or folders here", bg="#f3f4f8", fg="#556",
                             font=("Segoe UI", 12), relief="groove", bd=2, height=2, cursor="hand2")
        self.drop.pack(fill="x")
        self.drop.bind("<Button-1>", lambda e: self.pick_files())
        bar = ttk.Frame(mid)
        bar.pack(fill="x", pady=(6, 4))
        ttk.Button(bar, text="Add files…", command=self.pick_files).pack(side="left")
        ttk.Button(bar, text="Add folder…", command=self.pick_folder).pack(side="left", padx=6)
        ttk.Button(bar, text="Clear list", command=self.clear).pack(side="left")
        self.summary = ttk.Label(bar, text="", style="Sub.TLabel")
        self.summary.pack(side="right")

        cols = ("type", "before", "after", "status")
        tv = ttk.Treeview(mid, columns=cols, show="tree headings", selectmode="extended")
        tv.heading("#0", text="File")
        for c, t, w in zip(cols, ("Type", "Before", "After", "Status"), (90, 80, 80, 210)):
            tv.heading(c, text=t)
            tv.column(c, width=px(w), minwidth=px(w * .8), anchor="w" if c == "status" else "center",
                      stretch=c == "status")
        tv.column("#0", width=px(260), stretch=True)
        sb = ttk.Scrollbar(mid, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        tv.bind("<Double-1>", self._open_selected)
        tv.bind("<Delete>", lambda e: self.remove_selected())
        self.tv = tv

        if self.dnd:
            for w in (self.drop, tv, r):
                w.drop_target_register(self.dnd)
                w.dnd_bind("<<Drop>>", self._on_drop)

        # options
        opts = ttk.Frame(r, padding=(16, 6, 16, 0))
        opts.pack(fill="x")
        ph = ttk.LabelFrame(opts, text=" Photos ", padding=10)
        ph.pack(side="left", fill="both", expand=True)
        vi = ttk.LabelFrame(opts, text=" Videos ", padding=10)
        vi.pack(side="left", fill="both", expand=True, padx=(10, 0))

        self.v_format = tk.StringVar()
        ttk.Radiobutton(ph, text="Save as JPG (opens everywhere)", value="jpg", variable=self.v_format,
                        command=self._save).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(ph, text="Keep PNG / WebP format", value="keep", variable=self.v_format,
                        command=self._save).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(ph, text="Size").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.c_size = ttk.Combobox(ph, state="readonly", width=18, values=[a for a, _ in SIZE_CHOICES])
        self.c_size.grid(row=2, column=1, sticky="w", pady=(8, 0), padx=(8, 0))
        ttk.Label(ph, text="Quality").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.c_quality = ttk.Combobox(ph, state="readonly", width=18, values=[a for a, _ in QUALITY_CHOICES])
        self.c_quality.grid(row=3, column=1, sticky="w", pady=(6, 0), padx=(8, 0))

        self.v_vmode = tk.StringVar()
        row = ttk.Frame(vi)
        row.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(row, text="Fit under", value="mb", variable=self.v_vmode, command=self._save).pack(side="left")
        self.c_mb = ttk.Combobox(row, width=5, values=MB_CHOICES)
        self.c_mb.pack(side="left", padx=4)
        ttk.Label(row, text="MB  (email: 25, Discord: 10)").pack(side="left")
        ttk.Radiobutton(vi, text="Good quality, smaller file", value="quality", variable=self.v_vmode,
                        command=self._save).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(vi, text="Resolution").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.c_res = ttk.Combobox(vi, state="readonly", width=18, values=[a for a, _ in RES_CHOICES])
        self.c_res.grid(row=2, column=1, sticky="w", pady=(8, 0), padx=(8, 0))
        for c in (self.c_size, self.c_quality, self.c_res):
            c.bind("<<ComboboxSelected>>", lambda e: self._save())
        self.c_mb.bind("<<ComboboxSelected>>", lambda e: self._save())
        self.c_mb.bind("<FocusOut>", lambda e: self._save())

        save = ttk.Frame(r, padding=(16, 8, 16, 0))
        save.pack(fill="x")
        ttk.Label(save, text="Save to:").pack(side="left")
        self.v_out = tk.StringVar()
        ttk.Radiobutton(save, text="Next to the originals", value="same", variable=self.v_out,
                        command=self._save).pack(side="left", padx=(8, 0))
        ttk.Radiobutton(save, text="Folder:", value="folder", variable=self.v_out,
                        command=self._choose_out_if_needed).pack(side="left", padx=(12, 0))
        self.out_label = ttk.Label(save, text="", style="Sub.TLabel", cursor="hand2")
        self.out_label.pack(side="left", padx=(2, 0))
        self.out_label.bind("<Button-1>", lambda e: self.choose_out())
        self.v_dates = tk.BooleanVar()
        ttk.Checkbutton(save, text="Keep original dates", variable=self.v_dates, command=self._save).pack(side="right")

        foot = ttk.Frame(r, padding=(16, 10, 16, 14))
        foot.pack(fill="x")
        self.progress = ttk.Progressbar(foot, mode="determinate", maximum=1000)
        self.progress.pack(side="left", fill="x", expand=True)
        self.open_btn = ttk.Button(foot, text="Open folder", command=self.open_output)
        self.open_btn.pack(side="left", padx=(10, 0))
        self.go_btn = ttk.Button(foot, text="Shrink", style="Big.TButton", command=self.start)
        self.go_btn.pack(side="left", padx=(10, 0))

        # Bottom panels keep their size; the file list absorbs any shortage of space.
        for w in (mid, opts, save, foot):
            w.pack_forget()
        foot.pack(side="bottom", fill="x")
        save.pack(side="bottom", fill="x")
        opts.pack(side="bottom", fill="x")
        mid.pack(fill="both", expand=True)

        r.protocol("WM_DELETE_WINDOW", self.on_close)

    def _apply_settings_to_ui(self):
        s = self.settings
        self.v_format.set(s["photo_format"])
        self.c_size.set(next((a for a, v in SIZE_CHOICES if v == s["photo_size"]), SIZE_CHOICES[0][0]))
        self.c_quality.set(next((a for a, v in QUALITY_CHOICES if v == s["photo_quality"]), "High"))
        self.v_vmode.set(s["video_mode"])
        self.c_mb.set(str(s["video_mb"]).rstrip("0").rstrip(".") if isinstance(s["video_mb"], float) else str(s["video_mb"]))
        self.c_res.set(next((a for a, v in RES_CHOICES if v == s["video_height"]), RES_CHOICES[0][0]))
        self.v_out.set(s["out_mode"])
        self.v_dates.set(bool(s["keep_dates"]))
        self._show_out()

    def _save(self):
        s = self.settings
        s["photo_format"] = self.v_format.get()
        s["photo_size"] = dict(SIZE_CHOICES).get(self.c_size.get(), 0)
        s["photo_quality"] = dict(QUALITY_CHOICES).get(self.c_quality.get(), 85)
        s["video_mode"] = self.v_vmode.get()
        try:
            mb = float(self.c_mb.get().replace(",", "."))
            s["video_mb"] = max(1.0, min(mb, 4000.0))
        except ValueError:
            self.c_mb.set(str(s["video_mb"]))
        s["video_height"] = dict(RES_CHOICES).get(self.c_res.get(), 1080)
        s["out_mode"] = self.v_out.get()
        s["keep_dates"] = bool(self.v_dates.get())
        try:
            core.save_settings(s)
        except OSError:
            pass
        self._show_out()

    def _show_out(self):
        d = self.settings.get("out_dir")
        self.out_label.configure(text=(d if len(d) < 48 else "…" + d[-46:]) if d else "(choose…)")

    def _choose_out_if_needed(self):
        if not self.settings.get("out_dir"):
            self.choose_out()
        self._save()

    def choose_out(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Save shrunk files to…", mustexist=False)
        if d:
            self.settings["out_dir"] = os.path.normpath(d)
            self.v_out.set("folder")
        elif not self.settings.get("out_dir"):
            self.v_out.set("same")
        self._save()

    # -- adding files -----------------------------------------------------------
    def _on_drop(self, event):
        self.add_paths(self.root.tk.splitlist(event.data))

    def pick_files(self):
        from tkinter import filedialog
        exts = " ".join("*" + e for e in sorted(core.PHOTO_EXT | core.VIDEO_EXT))
        files = filedialog.askopenfilenames(title="Add photos and videos",
                                            filetypes=[("Photos and videos", exts), ("All files", "*.*")])
        if files:
            self.add_paths(files)

    def pick_folder(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Add a folder (including subfolders)")
        if d:
            self.add_paths([d])

    def add_paths(self, paths, go=False):
        known = {it["path"] for it in self.items.values()}
        added = 0
        for p in core.expand(paths):
            if p in known:
                continue
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            kind = core.kind_of(p)
            label = "HEIC→JPG" if os.path.splitext(p)[1].lower() in core.HEIF_EXT else kind.capitalize()
            iid = self.tv.insert("", "end", text=os.path.basename(p),
                                 values=(label, core.human(size), "", "Waiting"))
            self.items[iid] = {"path": p, "kind": kind, "before": size, "after": None, "status": "waiting", "out": None}
            self.order.append(iid)
            added += 1
        if not added and paths:
            self.summary.configure(text="No photos or videos found in what you dropped.")
        self._update_summary()
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass
        if go and added:
            self.start()

    def remove_selected(self):
        if self.worker:
            return
        for iid in self.tv.selection():
            self.tv.delete(iid)
            self.items.pop(iid, None)
            self.order.remove(iid)
        self._update_summary()

    def clear(self):
        if self.worker:
            return
        self.tv.delete(*self.tv.get_children())
        self.items.clear()
        self.order.clear()
        self.progress["value"] = 0
        self._update_summary()

    def _update_summary(self):
        done = [it for it in self.items.values() if it["status"] == "done"]
        if done:
            before = sum(it["before"] for it in done)
            after = sum(it["after"] for it in done)
            pct = (1 - after / before) * 100 if before else 0
            txt = f"{len(done)} done · saved {core.human(max(0, before - after))} ({pct:.0f}% smaller)"
        else:
            n = len(self.items)
            txt = f"{n} file{'s' if n != 1 else ''}" if n else ""
        self.summary.configure(text=txt)

    # -- processing ---------------------------------------------------------------
    def start(self):
        if self.worker:
            self.stop_flag = True
            self.go_btn.configure(text="Stopping…", state="disabled")
            return
        lic = self.lic.refresh(force=True)
        if lic.locked:
            self._show_banner(lic)
            from tkinter import messagebox
            messagebox.showinfo(core.APP_NAME, "Your free trial has ended. Buy ShrinkDrop in the Microsoft Store "
                                               "to keep shrinking files.")
            self.storeapi.open_store_page()
            return
        self._save()
        if self.settings["out_mode"] == "folder" and not self.settings.get("out_dir"):
            self.choose_out()
        todo = [iid for iid in self.order if self.items[iid]["status"] in ("waiting", "error", "stopped")]
        if not todo:
            return
        self.stop_flag = False
        self.go_btn.configure(text="Stop")
        self.progress["value"] = 0
        settings = dict(self.settings)
        self.worker = threading.Thread(target=self._work, args=(todo, settings), daemon=True)
        self.worker.start()

    def _work(self, todo, settings):
        n = len(todo)
        for i, iid in enumerate(todo):
            if self.stop_flag:
                break
            it = self.items.get(iid)
            if not it:
                continue
            self.events.put(("status", iid, "Working…", None))

            def prog(f, i=i, iid=iid):
                self.events.put(("progress", iid, f, (i + f) / n))
            try:
                out = core.process(it["path"], settings, progress=prog, cancel=lambda: self.stop_flag)
                self.events.put(("done", iid, out, (i + 1) / n))
            except core.Cancelled:
                self.events.put(("stopped", iid, None, None))
                break
            except Exception as e:
                traceback.print_exc()
                self.events.put(("error", iid, str(e) or e.__class__.__name__, (i + 1) / n))
        self.events.put(("finished", None, None, None))

    def _pump(self):
        try:
            while True:
                kind, iid, val, total = self.events.get_nowait()
                it = self.items.get(iid) if iid else None
                if kind == "status" and it:
                    self.tv.set(iid, "status", val)
                    self.tv.see(iid)
                elif kind == "progress" and it:
                    self.tv.set(iid, "status", f"Working… {val * 100:.0f}%")
                    self.progress["value"] = total * 1000
                elif kind == "done" and it:
                    it["status"], it["out"] = "done", val
                    try:
                        it["after"] = os.path.getsize(val)
                    except OSError:
                        it["after"] = it["before"]
                    pct = (1 - it["after"] / it["before"]) * 100 if it["before"] else 0
                    self.tv.set(iid, "after", core.human(it["after"]))
                    msg = f"✓ {pct:.0f}% smaller" if pct > 0.5 else "✓ Done"
                    if it["kind"] == "photo" and os.path.splitext(it["path"])[1].lower() in core.HEIF_EXT:
                        msg = "✓ Converted" + (f", {pct:.0f}% smaller" if pct > 0.5 else "")
                    self.tv.set(iid, "status", msg)
                    self.last_out_dir = os.path.dirname(val)
                    self.progress["value"] = total * 1000
                elif kind == "error" and it:
                    it["status"] = "error"
                    self.tv.set(iid, "status", "Couldn't process: " + val[:60])
                    self.progress["value"] = total * 1000
                elif kind == "stopped" and it:
                    it["status"] = "stopped"
                    self.tv.set(iid, "status", "Stopped")
                elif kind == "finished":
                    self.worker = None
                    self.go_btn.configure(text="Shrink", state="normal")
                    for i2 in self.order:
                        if self.items[i2]["status"] == "waiting" and self.stop_flag:
                            self.tv.set(i2, "status", "Waiting")
                    if not self.stop_flag:
                        self.progress["value"] = 1000
                self._update_summary()
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    # -- misc -------------------------------------------------------------------------
    def _open_selected(self, event=None):
        for iid in self.tv.selection():
            it = self.items.get(iid)
            if it:
                target = it["out"] or it["path"]
                os.system(f'explorer /select,"{target}"')
                break

    def open_output(self):
        d = self.last_out_dir
        if not d:
            d = self.settings["out_dir"] if self.settings["out_mode"] == "folder" and self.settings["out_dir"] else None
        if not d and self.order:
            d = os.path.dirname(self.items[self.order[0]]["path"])
        if d and os.path.isdir(d):
            os.startfile(d)

    def _check_license(self):
        lic = self.lic.refresh()
        self._show_banner(lic)
        self.root.after(60_000, self._check_license)

    def _show_banner(self, lic):
        if lic.state == "trial":
            d = lic.days_left
            self.banner_label.configure(text=f"Free trial: {d} day{'s' if d != 1 else ''} left.")
        elif lic.state == "expired":
            self.banner_label.configure(text="Your free trial has ended. Buy ShrinkDrop to keep using it.")
        if lic.state in ("trial", "expired"):
            if not self.banner.winfo_ismapped():
                self.banner.pack(fill="x", before=self.root.winfo_children()[1])
        elif self.banner.winfo_ismapped():
            self.banner.pack_forget()

    def receive(self, msg):
        self.root.after(0, lambda: self.add_paths(msg.get("paths") or [], msg.get("go")))

    def on_close(self):
        if self.worker:
            from tkinter import messagebox
            if not messagebox.askyesno(core.APP_NAME, "Files are still being processed. Stop and close?"):
                return
            self.stop_flag = True
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ---- entry -------------------------------------------------------------------------
def parse_args(argv):
    go, files, flags = False, [], set()
    for a in argv:
        if a in ("-m", "main"):
            continue
        if a == "--go":
            go = True
        elif a.startswith("--"):
            flags.add(a)
        else:
            files.append(a)
    return go, files, flags


def first_run_setup():
    """Direct edition: register the right-click menu and shortcuts once."""
    if core.PACKAGED or not core.DIRECT:
        return
    marker = os.path.join(core.APPDATA_DIR, "installed-" + os.path.normcase(HERE).replace(":", "").replace("\\", "_"))
    if os.path.exists(marker):
        return
    try:
        import wininteg
        wininteg.set_explorer_menu(True)
        wininteg.install_shortcuts()
        os.makedirs(core.APPDATA_DIR, exist_ok=True)
        open(marker, "w").close()
    except Exception:
        traceback.print_exc()


def main():
    go, files, flags = parse_args(sys.argv[1:])
    if "--uninstall" in flags:
        import wininteg
        wininteg.uninstall()
        if "--quiet" not in flags:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "ShrinkDrop's menu entries and shortcuts were removed.", "ShrinkDrop", 0)
        return
    if core.PACKAGED:
        import storeapi
        shared = storeapi.take_share()
        if shared:
            files, go = shared, True
    if forward_to_running(files, go):
        return
    first_run_setup()
    app = App(files, go)
    listener = listen(app.receive)
    try:
        app.run()
    finally:
        if listener:
            listener.close()


if __name__ == "__main__":
    if sys.executable.lower().endswith("pythonw.exe"):
        log = os.path.join(core.APPDATA_DIR, "log.txt")
        try:
            os.makedirs(core.APPDATA_DIR, exist_ok=True)
            sys.stdout = sys.stderr = open(log, "a", encoding="utf-8", buffering=1)
        except OSError:
            pass
    main()
