import fnmatch
import os
import re
import shutil
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


# Backup names recognized by the application.
BACKUP_RE = re.compile(
    r"(^|[._ ()\-])(bak|backup|copy|old)([._ ()\-]|$)|(~$)|(\.bak$)",
    re.IGNORECASE,
)


class FileBrowserApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("WJ File Browser and Backup Sorter")
        self.geometry("1100x680")
        self.minsize(820, 500)

        self.window4 = None
        self.text11z = None
        self.message4 = None

        self.root_folder = tk.StringVar(value=os.getcwd())
        self.wildcard = tk.StringVar(value="*")
        self.folder_filter = tk.StringVar(value="")
        self.sort_mode = tk.StringVar(value="Modified: newest first")
        self.backups_only = tk.BooleanVar(value=False)
        self.include_folders = tk.BooleanVar(value=False)
        self.status_text = tk.StringVar(value="Ready")

        self.all_items = []
        self.visible_items = []
        # Full paths excluded by Ctrl/Shift multi-selection.
        self.excluded_files = set()
        # Folder paths excluded as complete branches.
        self.excluded_folders = set()

        self._build_style()
        self._build_ui()
        self.scan_files()

    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("Treeview", rowheight=25)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Info.TLabel", foreground="#555555")

    def _build_ui(self):
        header = ttk.Frame(self, padding=(12, 10))
        header.pack(fill=tk.X)

        ttk.Label(header, text="File Browser and Backup Sorter", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Button(header, text="Working Data File", command=self.open_window_4).pack(side=tk.RIGHT)

        folder_frame = ttk.LabelFrame(self, text="Search location", padding=10)
        folder_frame.pack(fill=tk.X, padx=12, pady=(0, 8))

        ttk.Entry(folder_frame, textvariable=self.root_folder).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(folder_frame, text="Browse...", command=self.choose_folder).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(folder_frame, text="Scan", command=self.scan_files).pack(side=tk.LEFT, padx=(8, 0))

        filters = ttk.LabelFrame(self, text="Search and sort", padding=10)
        filters.pack(fill=tk.X, padx=12, pady=(0, 8))

        ttk.Label(filters, text="Wildcard:").grid(row=0, column=0, sticky="w")
        wildcard_entry = ttk.Entry(filters, textvariable=self.wildcard, width=24)
        wildcard_entry.grid(row=1, column=0, padx=(0, 10), sticky="ew")
        wildcard_entry.bind("<Return>", lambda _event: self.apply_filters())

        ttk.Label(filters, text="Folder/path contains:").grid(row=0, column=1, sticky="w")
        folder_entry = ttk.Entry(filters, textvariable=self.folder_filter, width=28)
        folder_entry.grid(row=1, column=1, padx=(0, 10), sticky="ew")
        folder_entry.bind("<Return>", lambda _event: self.apply_filters())

        ttk.Label(filters, text="Sort:").grid(row=0, column=2, sticky="w")
        sort_box = ttk.Combobox(
            filters,
            textvariable=self.sort_mode,
            state="readonly",
            values=(
                "Modified: newest first",
                "Modified: oldest first",
                "Name: A-Z",
                "Name: Z-A",
                "Size: largest first",
                "Size: smallest first",
                "Folder: A-Z",
            ),
            width=25,
        )
        sort_box.grid(row=1, column=2, padx=(0, 10), sticky="ew")
        sort_box.bind("<<ComboboxSelected>>", lambda _event: self.apply_filters())

        options = ttk.Frame(filters)
        options.grid(row=0, column=3, rowspan=2, sticky="w")
        ttk.Checkbutton(
            options,
            text="Backups only",
            variable=self.backups_only,
            command=self.apply_filters,
        ).pack(anchor="w")
        ttk.Checkbutton(
            options,
            text="Include folders",
            variable=self.include_folders,
            command=self.scan_files,
        ).pack(anchor="w")

        ttk.Button(filters, text="Search", command=self.apply_filters).grid(row=1, column=4, padx=(8, 0))
        ttk.Button(filters, text="Reset", command=self.reset_filters).grid(row=1, column=5, padx=(8, 0))

        filters.columnconfigure(0, weight=1)
        filters.columnconfigure(1, weight=1)
        filters.columnconfigure(2, weight=1)

        ttk.Label(
            self,
            text="Wildcard examples:  *.py     backup*     data_??.json     *reader*",
            style="Info.TLabel",
        ).pack(fill=tk.X, padx=16, pady=(0, 6))

        table_frame = ttk.Frame(self)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=12)

        columns = ("name", "folder", "size", "modified", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")

        self.tree.heading("name", text="Name", command=lambda: self.set_sort("Name: A-Z"))
        self.tree.heading("folder", text="Folder", command=lambda: self.set_sort("Folder: A-Z"))
        self.tree.heading("size", text="Size", command=lambda: self.set_sort("Size: largest first"))
        self.tree.heading("modified", text="Modified", command=lambda: self.set_sort("Modified: newest first"))
        self.tree.heading("status", text="Status")

        self.tree.column("name", width=260, minwidth=140)
        self.tree.column("folder", width=420, minwidth=180)
        self.tree.column("size", width=90, anchor=tk.E)
        self.tree.column("modified", width=145, anchor=tk.CENTER)
        self.tree.column("status", width=80, anchor=tk.CENTER)

        y_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        self.tree.tag_configure("backup", background="#fff1c9")
        self.tree.bind("<Double-1>", self.open_selected)
        self.tree.bind("<Button-3>", self.show_context_menu)

        self.context_menu = tk.Menu(self, tearoff=False)
        self.context_menu.add_command(label="Open", command=self.open_selected)
        self.context_menu.add_command(label="Open containing folder", command=self.open_containing_folder)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Exclude selected file(s)", command=self.exclude_selected_files)
        self.context_menu.add_command(label="Exclude selected folder(s)", command=self.exclude_selected_folders)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Move selected backups...", command=self.move_selected_backups)

        bottom = ttk.Frame(self, padding=12)
        bottom.pack(fill=tk.X)
        ttk.Label(bottom, textvariable=self.status_text).pack(side=tk.LEFT)
        ttk.Button(bottom, text="Move selected backups...", command=self.move_selected_backups).pack(side=tk.RIGHT)
        ttk.Button(bottom, text="Clear exclusions", command=self.clear_exclusions).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(bottom, text="Exclude folder(s)", command=self.exclude_selected_folders).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(bottom, text="Exclude file(s)", command=self.exclude_selected_files).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(bottom, text="Refresh", command=self.scan_files).pack(side=tk.RIGHT, padx=(0, 8))

    def choose_folder(self):
        selected = filedialog.askdirectory(initialdir=self.root_folder.get() or os.getcwd())
        if selected:
            self.root_folder.set(selected)
            self.scan_files()

    def scan_files(self):
        root_text = self.root_folder.get().strip()
        root = Path(root_text).expanduser()

        if not root.is_dir():
            messagebox.showerror("Folder not found", f"The folder does not exist:\n{root}")
            return

        self.status_text.set("Scanning folders...")
        self.update_idletasks()
        items = []
        errors = 0

        def on_walk_error(_error):
            nonlocal errors
            errors += 1

        try:
            for current_folder, folder_names, file_names in os.walk(root, onerror=on_walk_error):
                current_path = Path(current_folder)

                if self.include_folders.get():
                    for folder_name in folder_names:
                        full_path = current_path / folder_name
                        items.append(self.make_item(full_path, root, is_folder=True))

                for filename in file_names:
                    full_path = current_path / filename
                    try:
                        items.append(self.make_item(full_path, root, is_folder=False))
                    except (OSError, PermissionError):
                        errors += 1
        except (OSError, PermissionError) as exc:
            messagebox.showerror("Scan error", str(exc))
            return

        self.all_items = items
        self.apply_filters()
        suffix = f"; {errors} inaccessible item(s) skipped" if errors else ""
        self.status_text.set(f"Indexed {len(items):,} item(s){suffix}")

    @staticmethod
    def make_item(full_path, root, is_folder=False):
        stat = full_path.stat()
        relative = full_path.relative_to(root)
        folder = str(relative.parent) if str(relative.parent) != "." else "."
        item = {
            "name": full_path.name,
            "folder": folder,
            "full_path": str(full_path),
            "size": 0 if is_folder else stat.st_size,
            "modified": stat.st_mtime,
            "is_folder": is_folder,
        }
        item["is_backup"] = FileBrowserApp.is_backup(item)
        return item

    @staticmethod
    def is_backup(item):
        name = item["name"]
        folder = item["folder"].replace("\\", "/")
        backup_folder = any(part.lower() in {"backup", "backups", "old", "archive"} for part in folder.split("/"))
        return bool(BACKUP_RE.search(name)) or backup_folder

    def apply_filters(self):
        patterns_text = self.wildcard.get().strip() or "*"
        # Semicolons allow multiple wildcard expressions, for example: *.py;*.json
        patterns = [item.strip() for item in patterns_text.split(";") if item.strip()]
        folder_text = self.folder_filter.get().strip().lower().replace("/", os.sep)

        visible = []
        for item in self.all_items:
            full_path = os.path.normcase(os.path.abspath(item["full_path"]))
            if full_path in self.excluded_files:
                continue
            if any(self.path_is_inside(full_path, folder) for folder in self.excluded_folders):
                continue
            if not any(fnmatch.fnmatch(item["name"].lower(), pattern.lower()) for pattern in patterns):
                continue
            if folder_text and folder_text not in item["folder"].lower():
                continue
            if self.backups_only.get() and not item["is_backup"]:
                continue
            visible.append(item)

        mode = self.sort_mode.get()
        if mode == "Name: A-Z":
            visible.sort(key=lambda x: (x["name"].lower(), x["folder"].lower()))
        elif mode == "Name: Z-A":
            visible.sort(key=lambda x: (x["name"].lower(), x["folder"].lower()), reverse=True)
        elif mode == "Size: largest first":
            visible.sort(key=lambda x: x["size"], reverse=True)
        elif mode == "Size: smallest first":
            visible.sort(key=lambda x: x["size"])
        elif mode == "Modified: oldest first":
            visible.sort(key=lambda x: x["modified"])
        elif mode == "Folder: A-Z":
            visible.sort(key=lambda x: (x["folder"].lower(), x["name"].lower()))
        else:
            visible.sort(key=lambda x: x["modified"], reverse=True)

        self.visible_items = visible
        self.populate_tree()

    def populate_tree(self):
        self.tree.delete(*self.tree.get_children())

        for index, item in enumerate(self.visible_items):
            modified = datetime.fromtimestamp(item["modified"]).strftime("%Y-%m-%d %H:%M")
            size = "<DIR>" if item["is_folder"] else self.format_size(item["size"])
            status = "BACKUP" if item["is_backup"] else ""
            tags = ("backup",) if item["is_backup"] else ()
            self.tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(item["name"], item["folder"], size, modified, status),
                tags=tags,
            )

        backup_count = sum(1 for item in self.visible_items if item["is_backup"])
        exclusion_count = len(self.excluded_files) + len(self.excluded_folders)
        self.status_text.set(
            f"Showing {len(self.visible_items):,} of {len(self.all_items):,} item(s); "
            f"{backup_count:,} possible backup(s); {exclusion_count:,} exclusion(s)"
        )

    @staticmethod
    def format_size(size):
        units = ("B", "KB", "MB", "GB", "TB")
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024

    def reset_filters(self):
        self.wildcard.set("*")
        self.folder_filter.set("")
        self.backups_only.set(False)
        self.sort_mode.set("Modified: newest first")
        self.apply_filters()

    def set_sort(self, mode):
        self.sort_mode.set(mode)
        self.apply_filters()

    def selected_items(self):
        selected = []
        for iid in self.tree.selection():
            try:
                selected.append(self.visible_items[int(iid)])
            except (ValueError, IndexError):
                pass
        return selected


    @staticmethod
    def path_is_inside(candidate, folder):
        """Return True when candidate is the folder itself or is below it."""
        try:
            return os.path.commonpath([candidate, folder]) == folder
        except ValueError:
            # Different Windows drives have no common path.
            return False

    def exclude_selected_files(self):
        """Exclude one or many selected files from the current search results."""
        selected = [item for item in self.selected_items() if not item["is_folder"]]
        if not selected:
            messagebox.showinfo(
                "No files selected",
                "Select one or more files first. Hold Ctrl to select separate files, or Shift for a range.",
            )
            return

        for item in selected:
            normalized = os.path.normcase(os.path.abspath(item["full_path"]))
            self.excluded_files.add(normalized)
        self.apply_filters()

    def exclude_selected_folders(self):
        """Exclude complete folders using selected folder rows or selected files' containing folders."""
        selected = self.selected_items()
        if not selected:
            messagebox.showinfo(
                "No items selected",
                "Select one or more items first. Hold Ctrl to select several folders or files.",
            )
            return

        folders = set()
        for item in selected:
            source = Path(item["full_path"])
            folder = source if item["is_folder"] else source.parent
            folders.add(os.path.normcase(os.path.abspath(str(folder))))

        preview = "\n".join(sorted(folders)[:10])
        if len(folders) > 10:
            preview += f"\n...and {len(folders) - 10} more"
        if not messagebox.askyesno(
            "Exclude folders",
            f"Exclude every file in these folder branches from search results?\n\n{preview}",
        ):
            return

        self.excluded_folders.update(folders)
        # Folder exclusions make individual exclusions beneath them redundant.
        self.excluded_files = {
            filename for filename in self.excluded_files
            if not any(self.path_is_inside(filename, folder) for folder in folders)
        }
        self.apply_filters()

    def clear_exclusions(self):
        """Restore all excluded files and folders to future search results."""
        if not self.excluded_files and not self.excluded_folders:
            messagebox.showinfo("Exclusions", "There are no excluded files or folders.")
            return
        if messagebox.askyesno("Clear exclusions", "Show all excluded files and folders again?"):
            self.excluded_files.clear()
            self.excluded_folders.clear()
            self.apply_filters()

    def show_context_menu(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def open_selected(self, _event=None):
        items = self.selected_items()
        if not items:
            return
        target = items[0]["full_path"]
        try:
            os.startfile(target)  # Windows
        except AttributeError:
            messagebox.showinfo("Open", f"Selected path:\n{target}")
        except OSError as exc:
            messagebox.showerror("Open error", str(exc))

    def open_containing_folder(self):
        items = self.selected_items()
        if not items:
            return
        target = items[0]["full_path"]
        try:
            if os.name == "nt" and not items[0]["is_folder"]:
                os.system(f'explorer /select,"{target}"')
            elif os.name == "nt":
                os.startfile(target)
            else:
                messagebox.showinfo("Folder", str(Path(target).parent))
        except OSError as exc:
            messagebox.showerror("Folder error", str(exc))

    def move_selected_backups(self):
        selected = [item for item in self.selected_items() if item["is_backup"] and not item["is_folder"]]
        if not selected:
            messagebox.showinfo("No backups selected", "Select one or more files marked BACKUP first.")
            return

        destination = filedialog.askdirectory(title="Choose a folder for the selected backups")
        if not destination:
            return

        names = "\n".join(item["name"] for item in selected[:12])
        if len(selected) > 12:
            names += f"\n...and {len(selected) - 12} more"

        confirmed = messagebox.askyesno(
            "Move backup files",
            f"Move {len(selected)} selected backup file(s) to:\n{destination}\n\n{names}",
        )
        if not confirmed:
            return

        moved = 0
        skipped = 0
        for item in selected:
            source = Path(item["full_path"])
            target = Path(destination) / source.name
            if target.exists():
                skipped += 1
                continue
            try:
                shutil.move(str(source), str(target))
                moved += 1
            except OSError:
                skipped += 1

        messagebox.showinfo("Backup move complete", f"Moved: {moved}\nSkipped: {skipped}")
        self.scan_files()

    # Adapted from the user's original open_window_4 snippet.
    def open_window_4(self):
        if self.window4 is not None and self.window4.winfo_exists():
            self.window4.withdraw()
            self.window4.deiconify()
            self.window4.lift()
        else:
            self.wjWindow4()

    # Adapted from the user's original getfiles5 snippet.
    def getfiles5(self):
        working_name = self.text11z.get().strip() if self.text11z else ""
        current_folder = Path(self.root_folder.get().strip() or os.getcwd())

        try:
            files = sorted(os.listdir(current_folder), key=str.lower)
        except OSError as exc:
            messagebox.showerror("Directory error", str(exc), parent=self.window4)
            return

        if working_name:
            matches = [name for name in files if fnmatch.fnmatch(name.lower(), working_name.lower())]
        else:
            matches = files

        self.message4.config(state=tk.NORMAL)
        self.message4.delete("1.0", tk.END)
        self.message4.insert(tk.END, "\n".join(matches))
        if matches:
            self.message4.insert(tk.END, "\n")
        self.message4.config(state=tk.DISABLED)

    # Adapted from the user's original wjWindow4 snippet.
    def wjWindow4(self):
        self.window4 = tk.Toplevel(self)
        self.window4.title("WJ-From The Directory")
        self.window4.geometry("520x430")
        self.window4.minsize(400, 300)
        self.window4.transient(self)

        frame = ttk.Frame(self.window4, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Working Data File:", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Include the extension. Wildcards are accepted, such as *.py.").pack(anchor="w", pady=(2, 8))

        some_file = tk.StringVar(value="*")
        self.text11z = ttk.Entry(frame, textvariable=some_file)
        self.text11z.pack(fill=tk.X)
        self.text11z.bind("<Return>", lambda _event: self.getfiles5())

        ttk.Button(frame, text="List files", command=self.getfiles5).pack(anchor="e", pady=8)

        message_frame = ttk.Frame(frame)
        message_frame.pack(fill=tk.BOTH, expand=True)
        self.message4 = tk.Text(message_frame, wrap=tk.NONE, state=tk.DISABLED, font=("Consolas", 10))
        scroll_y = ttk.Scrollbar(message_frame, orient=tk.VERTICAL, command=self.message4.yview)
        scroll_x = ttk.Scrollbar(message_frame, orient=tk.HORIZONTAL, command=self.message4.xview)
        self.message4.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        self.message4.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        message_frame.rowconfigure(0, weight=1)
        message_frame.columnconfigure(0, weight=1)

        self.getfiles5()


if __name__ == "__main__":
    app = FileBrowserApp()
    app.mainloop()
