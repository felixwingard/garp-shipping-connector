"""Enhetlig tema och styling för tray-fönster."""

import tkinter as tk
from tkinter import ttk


# Färgpalett — diskret, professionell
COLORS = {
    "bg": "#f8fafc",
    "card_bg": "#ffffff",
    "text": "#1e293b",
    "text_muted": "#64748b",
    "border": "#e2e8f0",
    "accent": "#0f172a",
    "success": "#16a34a",
    "error": "#dc2626",
    "font_family": "Segoe UI" if __import__("platform").system() == "Windows" else "SF Pro Display",
}

# Alternativ: systemfont
def _system_font():
    import platform
    if platform.system() == "Windows":
        return "Segoe UI"
    if platform.system() == "Darwin":
        return "Helvetica Neue"
    return "Helvetica"


def apply_theme(root: tk.Tk):
    """Applicerar tema på root och alla ttk-widgets."""
    style = ttk.Style(root)
    font = _system_font()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    # Generella inställningar
    style.configure(
        ".",
        background=COLORS["bg"],
        foreground=COLORS["text"],
        font=(font, 10),
        padding=4,
    )

    # LabelFrame — card-stil
    style.configure(
        "TLabelframe",
        background=COLORS["card_bg"],
        bordercolor=COLORS["border"],
        relief="flat",
    )
    style.configure(
        "TLabelframe.Label",
        background=COLORS["card_bg"],
        foreground=COLORS["accent"],
        font=(font, 10, "bold"),
    )
    style.map("TLabelframe", background=[("", COLORS["card_bg"])])

    # Knappar
    style.configure(
        "TButton",
        font=(font, 10),
        padding=(16, 8),
        background=COLORS["accent"],
        foreground="white",
    )
    style.map(
        "TButton",
        background=[("active", "#334155"), ("pressed", "#0f172a")],
        foreground=[("active", "white")],
    )

    # Secondary-knapp (Avbryt)
    style.configure(
        "Secondary.TButton",
        font=(font, 10),
        padding=(16, 8),
        background=COLORS["card_bg"],
        foreground=COLORS["text"],
    )
    style.map(
        "Secondary.TButton",
        background=[("active", COLORS["border"])],
    )

    # Entry
    style.configure(
        "TEntry",
        fieldbackground="white",
        padding=8,
        insertcolor=COLORS["text"],
    )

    # Combobox
    style.configure(
        "TCombobox",
        fieldbackground="white",
        padding=6,
    )

    # Treeview
    style.configure(
        "Treeview",
        background="white",
        foreground=COLORS["text"],
        fieldbackground="white",
        rowheight=28,
        font=(font, 10),
    )
    style.configure(
        "Treeview.Heading",
        font=(font, 10, "bold"),
        foreground=COLORS["text_muted"],
    )
    style.map("Treeview", background=[("selected", "#f1f5f9")], foreground=[("selected", COLORS["text"])])

    root.configure(bg=COLORS["bg"])
