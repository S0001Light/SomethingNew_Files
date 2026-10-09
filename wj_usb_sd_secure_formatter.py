import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

TITLE = "WritersJumbler USB / microSD Secure Formatter"
NO_WINDOW = 0x08000000
CLUSTERS = {
    "Default": None, "4 KB": 4096, "8 KB": 8192, "16 KB": 16384,
    "32 KB": 32768, "64 KB": 65536, "128 KB": 131072,
    "256 KB": 262144, "512 KB": 524288, "1024 KB": 1048576,
}


def admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate():
    args = subprocess.list2cmdline(sys.argv)
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, None, 1)
    if result <= 32:
        raise OSError("Administrator permission was refused.")


def removable_volumes():
    ps = r'''
$items = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=2" | ForEach-Object {
 [PSCustomObject]@{Drive=$_.DeviceID; Label=$_.VolumeName; Size=[UInt64]$_.Size; FS=$_.FileSystem}
}
@($items) | ConvertTo-Json -Compress
'''
    p = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, creationflags=NO_WINDOW
    )
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or "Could not detect removable drives.")
    if not p.stdout.strip():
        return []
    data = json.loads(p.stdout)
    return [data] if isinstance(data, dict) else data


def size_text(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(TITLE)
        self.geometry("760x650")
        self.minsize(700, 580)
        self.configure(bg="#101722")
        self.protocol("WM_DELETE_WINDOW", self.close_app)

        self.items = {}
        self.q = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker = None
        self.active_process = None

        self.drive = tk.StringVar()
        self.fs = tk.StringVar(value="exFAT")
        self.label = tk.StringVar(value="WJ_MEDIA")
        self.cluster = tk.StringVar(value="Default")
        self.random_passes = tk.IntVar(value=1)
        self.final_zero = tk.BooleanVar(value=True)
        self.confirm = tk.StringVar()
        self.status = tk.StringVar(value="Ready")

        self.make_style()
        self.make_ui()
        self.after(100, self.poll)
        self.refresh()

    def make_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame", background="#101722")
        s.configure("Card.TFrame", background="#192536")
        s.configure("TLabel", background="#101722", foreground="#eaf2ff", font=("Segoe UI", 10))
        s.configure("Card.TLabel", background="#192536", foreground="#eaf2ff", font=("Segoe UI", 10))
        s.configure("Title.TLabel", background="#101722", foreground="#62dafc", font=("Segoe UI Semibold", 20))
        s.configure("Warning.TLabel", background="#192536", foreground="#ffcf67", font=("Segoe UI Semibold", 10))
        s.configure("TButton", padding=8, font=("Segoe UI Semibold", 10))
        s.configure("Danger.TButton", background="#c63d50", foreground="white", padding=10)
        s.map("Danger.TButton", background=[("active", "#e04d61"), ("disabled", "#69444c")])
        s.configure("TCheckbutton", background="#192536", foreground="#eaf2ff")
        s.map("TCheckbutton", background=[("active", "#192536")])

    def make_ui(self):
        root = ttk.Frame(self, padding=20)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="USB / microSD Secure Formatter", style="Title.TLabel").pack(anchor="w")
        ttk.Label(root, text="Zero pass, 0 to 7 random-data passes, then an optional final zero pass.").pack(anchor="w", pady=(2, 14))

        card = ttk.Frame(root, style="Card.TFrame", padding=18)
        card.pack(fill="x")
        card.columnconfigure(1, weight=1)

        self.drive_box = ttk.Combobox(card, textvariable=self.drive, state="readonly")
        self.row(card, 0, "Removable volume", self.drive_box)
        ttk.Button(card, text="Refresh", command=self.refresh).grid(row=0, column=2, padx=(8, 0))
        self.row(card, 1, "File system", ttk.Combobox(card, textvariable=self.fs, values=("exFAT", "FAT32", "NTFS"), state="readonly"))
        self.row(card, 2, "Volume label", ttk.Entry(card, textvariable=self.label))
        self.row(card, 3, "Allocation unit", ttk.Combobox(card, textvariable=self.cluster, values=list(CLUSTERS), state="readonly"))
        self.row(card, 4, "Random passes", ttk.Spinbox(card, from_=0, to=7, textvariable=self.random_passes, state="readonly", width=8))
        ttk.Checkbutton(card, text="Finish with another complete zero pass", variable=self.final_zero).grid(row=5, column=1, sticky="w", pady=8)

        ttk.Separator(card).grid(row=6, column=0, columnspan=3, sticky="ew", pady=12)
        ttk.Label(card, text="WARNING: THIS PERMANENTLY ERASES THE SELECTED VOLUME.", style="Warning.TLabel").grid(row=7, column=0, columnspan=3, sticky="w")
        ttk.Label(card, text="Type FORMAT X: using the selected drive letter:", style="Card.TLabel").grid(row=8, column=0, columnspan=3, sticky="w", pady=(8, 4))
        ttk.Entry(card, textvariable=self.confirm).grid(row=9, column=0, columnspan=3, sticky="ew")

        buttons = ttk.Frame(root, padding=(0, 14, 0, 8))
        buttons.pack(fill="x")
        self.start_btn = ttk.Button(buttons, text="ERASE AND FORMAT", style="Danger.TButton", command=self.start)
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(buttons, text="Cancel", state="disabled", command=self.cancel)
        self.cancel_btn.pack(side="left", padx=8)
        ttk.Label(buttons, textvariable=self.status).pack(side="right")

        self.bar = ttk.Progressbar(root, mode="indeterminate")
        self.bar.pack(fill="x", pady=(0, 10))
        self.log = tk.Text(root, bg="#0b111a", fg="#cce7ff", insertbackground="white",
                           font=("Consolas", 9), relief="flat", wrap="word", height=14)
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")

    def row(self, parent, n, text, widget):
        ttk.Label(parent, text=text, style="Card.TLabel").grid(row=n, column=0, sticky="w", padx=(0, 14), pady=7)
        widget.grid(row=n, column=1, sticky="ew", pady=7)

    def write_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def refresh(self):
        try:
            self.items.clear()
            names = []
            for v in removable_volumes():
                name = f"{v['Drive']}   {v.get('Label') or '(no label)'}   {size_text(v.get('Size'))}   {v.get('FS') or 'unformatted'}"
                names.append(name)
                self.items[name] = v
            self.drive_box["values"] = names
            self.drive.set(names[0] if names else "")
            self.status.set(f"Found {len(names)} removable volume(s)." if names else "No removable volume found.")
        except Exception as e:
            messagebox.showerror(TITLE, str(e))

    def selected_letter(self):
        item = self.items.get(self.drive.get())
        return item.get("Drive") if item else None

    def command(self, letter, passes):
        cmd = ["format.com", letter, f"/FS:{self.fs.get()}", "/X", f"/P:{passes}"]
        label = self.label.get().strip()[:32]
        cmd.append(f"/V:{label}" if label else "/V:")
        cluster = CLUSTERS[self.cluster.get()]
        if cluster:
            cmd.append(f"/A:{cluster}")
        return cmd

    def start(self):
        letter = self.selected_letter()
        if not letter:
            messagebox.showwarning(TITLE, "Select a removable volume.")
            return
        expected = f"FORMAT {letter}".upper()
        if self.confirm.get().strip().upper() != expected:
            messagebox.showwarning(TITLE, f"Type exactly: {expected}")
            return
        passes = int(self.random_passes.get())
        if not 0 <= passes <= 7:
            messagebox.showwarning(TITLE, "Choose between 0 and 7 random passes.")
            return
        if not messagebox.askyesno(TITLE, f"Permanently erase {letter}?\n\nThis cannot be undone.", icon="warning"):
            return
        self.cancel_event.clear()
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.bar.start(12)
        self.status.set("Working. Do not remove the device.")
        self.worker = threading.Thread(target=self.work, args=(letter, passes), daemon=True)
        self.worker.start()

    def run_format(self, cmd, heading):
        self.q.put(("log", "\n" + heading))
        self.q.put(("log", "Command: " + subprocess.list2cmdline(cmd)))
        self.active_process = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", creationflags=NO_WINDOW, bufsize=1
        )
        try:
            self.active_process.stdin.write("Y\n" * 8)
            self.active_process.stdin.flush()
            self.active_process.stdin.close()
        except Exception:
            pass
        for line in iter(self.active_process.stdout.readline, ""):
            self.q.put(("log", line.rstrip()))
            if self.cancel_event.is_set():
                self.active_process.terminate()
                break
        code = self.active_process.wait()
        self.active_process = None
        if self.cancel_event.is_set():
            raise RuntimeError("Cancelled. The volume may need to be formatted again.")
        if code:
            raise RuntimeError(f"Windows format exited with code {code}.")

    def work(self, letter, passes):
        try:
            self.run_format(self.command(letter, passes), f"Stage 1: zeros plus {passes} random pass(es)")
            if self.final_zero.get():
                self.run_format(self.command(letter, 0), "Stage 2: final zero pass")
            self.q.put(("done", f"Formatting completed on {letter}."))
        except Exception as e:
            self.q.put(("error", str(e)))

    def cancel(self):
        if messagebox.askyesno(TITLE, "Stop now? The volume may be left unusable until reformatted.", icon="warning"):
            self.cancel_event.set()
            if self.active_process:
                try:
                    self.active_process.terminate()
                except Exception:
                    pass
            self.status.set("Stopping...")

    def finish(self, text):
        self.bar.stop()
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.status.set(text)
        self.confirm.set("")

    def poll(self):
        try:
            while True:
                kind, text = self.q.get_nowait()
                if kind == "log":
                    self.write_log(text)
                elif kind == "done":
                    self.finish(text)
                    messagebox.showinfo(TITLE, text)
                    self.refresh()
                elif kind == "error":
                    self.finish("Failed or cancelled.")
                    self.write_log("ERROR: " + text)
                    messagebox.showerror(TITLE, text)
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def close_app(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning(TITLE, "Wait for the operation to finish or cancel it first.")
        else:
            self.destroy()


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("This application requires Windows.")
    if not admin():
        try:
            elevate()
        except Exception as e:
            messagebox.showerror(TITLE, str(e))
        raise SystemExit
    App().mainloop()
