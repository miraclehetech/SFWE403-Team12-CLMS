"""Widgets and helpers shared by every tab."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..errors import CLMSError

PAD = {"padx": 6, "pady": 3}


def run(widget: tk.Misc, action, *args, success: str | None = None, **kwargs):
    """Call a service function; show expected errors in a dialog instead of crashing.

    Returns the function's result, or ``None`` when it failed.
    """
    try:
        result = action(*args, **kwargs)
    except CLMSError as exc:
        messagebox.showerror("Cannot continue", str(exc), parent=widget.winfo_toplevel())
        return None
    if success:
        set_status(widget, success)
    return result


def set_status(widget: tk.Misc, text: str) -> None:
    app = widget.winfo_toplevel()
    if hasattr(app, "status"):
        app.status.set(text)


class Form(ttk.Frame):
    """A two-column label/field grid.

    ``spec`` is a list of ``(key, label, kind, options)`` where kind is
    ``"entry"``, ``"combo"`` (read-only drop-down) or ``"readonly"``.
    """

    def __init__(self, master, spec, columns: int = 1, width: int = 32):
        super().__init__(master)
        self.vars: dict[str, tk.StringVar] = {}
        self.widgets: dict[str, ttk.Widget] = {}
        for index, (key, label, kind, *rest) in enumerate(spec):
            options = rest[0] if rest else ()
            row, col = divmod(index, columns)
            ttk.Label(self, text=label + ":").grid(row=row, column=col * 2, sticky="e", **PAD)
            var = tk.StringVar()
            if kind == "combo":
                w = ttk.Combobox(self, textvariable=var, values=list(options), state="readonly", width=width - 3)
            else:
                w = ttk.Entry(self, textvariable=var, width=width)
                if kind == "readonly":
                    w.state(["readonly"])
            w.grid(row=row, column=col * 2 + 1, sticky="we", **PAD)
            self.vars[key], self.widgets[key] = var, w
        for c in range(columns):
            self.columnconfigure(c * 2 + 1, weight=1)

    def get(self) -> dict[str, str]:
        return {k: var.get().strip() for k, var in self.vars.items()}

    def set(self, values: dict) -> None:
        for k, val in values.items():
            if k in self.vars:
                self.vars[k].set("" if val is None else str(val))

    def clear(self) -> None:
        for var in self.vars.values():
            var.set("")

    def set_enabled(self, enabled: bool) -> None:
        for key, w in self.widgets.items():
            if isinstance(w, ttk.Combobox):
                w.state(["!disabled", "readonly"] if enabled else ["disabled"])
            else:
                w.state(["!readonly"] if enabled else ["readonly"])


class Table(ttk.Frame):
    """A Treeview with a vertical scrollbar. ``columns`` is ``[(key, heading, width), ...]``."""

    def __init__(self, master, columns, height: int = 10):
        super().__init__(master)
        keys = [c[0] for c in columns]
        self.tree = ttk.Treeview(self, columns=keys, show="headings", height=height, selectmode="browse")
        for key, heading, width in columns:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, stretch=True, anchor="w")
        bar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def fill(self, rows) -> None:
        """``rows`` is an iterable of ``(iid, values)``."""
        self.tree.delete(*self.tree.get_children())
        for iid, values in rows:
            self.tree.insert("", "end", iid=str(iid), values=[("" if x is None else x) for x in values])

    def selected(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def bind_select(self, callback) -> None:
        self.tree.bind("<<TreeviewSelect>>", lambda _e: callback(self.selected()))


class FormDialog(tk.Toplevel):
    """Modal dialog that shows a :class:`Form` and returns its values (or ``None`` on cancel)."""

    def __init__(self, parent, title: str, spec, initial: dict | None = None, intro: str = ""):
        super().__init__(parent)
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.result: dict | None = None
        if intro:
            ttk.Label(self, text=intro, wraplength=380, justify="left").pack(anchor="w", padx=10, pady=(10, 0))
        self.form = Form(self, spec)
        self.form.pack(fill="both", expand=True, padx=8, pady=8)
        if initial:
            self.form.set(initial)
        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="OK", command=self._ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.wait_visibility()
        self.grab_set()

    def _ok(self):
        self.result = self.form.get()
        self.destroy()

    @classmethod
    def ask(cls, parent, title, spec, initial=None, intro="") -> dict | None:
        dlg = cls(parent, title, spec, initial, intro)
        parent.wait_window(dlg)
        return dlg.result
