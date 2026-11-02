"""
WhiteBase Inspector — runtime tester GUI
----------------------------------------
Load / unload bricks, pick a capability, send a JSON payload,
see the response and live brick stats.  No LLM required.

Run:  python whitebase_inspector.py
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading, json, time, sys, os

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from whitebase import WhiteBase

# ── palette ────────────────────────────────────────────────────────────────
BG      = "#0f0f1a"
PANEL   = "#16213e"
CARD    = "#1a2744"
BORDER  = "#2a3a60"
GREEN   = "#00e676"
YELLOW  = "#ffb300"
RED     = "#ff5252"
BLUE    = "#448aff"
TEXT    = "#e0e0e0"
DIM     = "#6677aa"
MONO    = ("Consolas", 10)
UI      = ("Segoe UI", 10)
UI_B    = ("Segoe UI", 10, "bold")
UI_SB   = ("Segoe UI", 9)

# default payloads per capability
DEFAULT_PAYLOADS = {
    "echo":            '{\n  "text": "hello whitebase"\n}',
    "text_generation": '{\n  "text": "hello whitebase"\n}',
    "chat":            '{\n  "prompt": "Say hi in one line.",\n  "history": []\n}',
}


def state_colour(info: dict) -> str:
    if info.get("loaded"):
        return GREEN
    if info.get("health") == "unhealthy":
        return RED
    return YELLOW


class Inspector(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WhiteBase Inspector")
        self.geometry("1060x700")
        self.configure(bg=BG)
        self.resizable(True, True)

        self.wb = WhiteBase()
        self._build_ui()
        self._refresh_bricks()
        self._auto_refresh()

    # ──────────────────────────────────────────────────────────────────────
    # UI layout
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # top header
        hdr = tk.Frame(self, bg=PANEL, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⬡  WhiteBase Inspector", font=("Segoe UI", 13, "bold"),
                 fg=BLUE, bg=PANEL).pack(side="left", padx=14)
        self.runtime_lbl = tk.Label(hdr, text="", font=UI_SB, fg=DIM, bg=PANEL)
        self.runtime_lbl.pack(side="right", padx=14)

        # main body: left panel (bricks) + right panel (tester)
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=8, pady=6)

        self._build_left(body)
        self._build_right(body)

    # ── left: brick list ───────────────────────────────────────────────────

    def _build_left(self, parent):
        lf = tk.Frame(parent, bg=PANEL, width=260)
        lf.pack(side="left", fill="y", padx=(0, 6))
        lf.pack_propagate(False)

        tk.Label(lf, text="INSTALLED BRICKS", font=("Segoe UI", 8, "bold"),
                 fg=DIM, bg=PANEL).pack(anchor="w", padx=10, pady=(10, 2))

        # scrollable brick cards
        canvas = tk.Canvas(lf, bg=PANEL, bd=0, highlightthickness=0)
        sb = ttk.Scrollbar(lf, orient="vertical", command=canvas.yview)
        self.brick_frame = tk.Frame(canvas, bg=PANEL)
        self.brick_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.brick_frame, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=6, pady=4)
        sb.pack(side="right", fill="y")

        # install .wb button
        tk.Button(lf, text="＋ Install .wb…", font=UI, bg=CARD, fg=BLUE,
                  relief="flat", pady=5, command=self._install_wb
                  ).pack(fill="x", padx=8, pady=6)

    # ── right: tester ──────────────────────────────────────────────────────

    def _build_right(self, parent):
        rf = tk.Frame(parent, bg=BG)
        rf.pack(side="left", fill="both", expand=True)

        # capability + controls row
        ctrl = tk.Frame(rf, bg=PANEL, pady=6)
        ctrl.pack(fill="x", pady=(0, 4))

        tk.Label(ctrl, text="Capability:", font=UI, fg=DIM, bg=PANEL).pack(side="left", padx=(10, 4))
        self.cap_var = tk.StringVar()
        self.cap_box = ttk.Combobox(ctrl, textvariable=self.cap_var,
                                    width=22, state="readonly")
        self.cap_box.pack(side="left")
        self.cap_box.bind("<<ComboboxSelected>>", self._on_cap_change)

        tk.Label(ctrl, text="Timeout (s):", font=UI, fg=DIM, bg=PANEL).pack(side="left", padx=(16, 4))
        self.timeout_var = tk.StringVar(value="")
        tk.Entry(ctrl, textvariable=self.timeout_var, width=5,
                 bg=CARD, fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=MONO).pack(side="left")

        self.run_btn = tk.Button(ctrl, text="▶  Run Request", font=UI_B,
                                 bg=GREEN, fg=BG, relief="flat", padx=14, pady=4,
                                 activebackground="#00c853",
                                 command=self._run_request)
        self.run_btn.pack(side="right", padx=10)

        self.status_lbl = tk.Label(ctrl, text="", font=UI_SB, fg=DIM, bg=PANEL)
        self.status_lbl.pack(side="right", padx=4)

        # payload + response panes
        panes = tk.PanedWindow(rf, orient="horizontal", bg=BG,
                               sashwidth=6, sashrelief="flat")
        panes.pack(fill="both", expand=True)

        # payload
        pl = tk.Frame(panes, bg=BG)
        tk.Label(pl, text="PAYLOAD  (JSON)", font=("Segoe UI", 8, "bold"),
                 fg=DIM, bg=BG).pack(anchor="w", padx=4, pady=(2, 1))
        self.payload_box = tk.Text(pl, bg=CARD, fg=TEXT, insertbackground=TEXT,
                                   font=MONO, relief="flat", padx=8, pady=6,
                                   undo=True)
        self.payload_box.pack(fill="both", expand=True)
        panes.add(pl, minsize=200)

        # response
        rl = tk.Frame(panes, bg=BG)
        tk.Label(rl, text="RESPONSE", font=("Segoe UI", 8, "bold"),
                 fg=DIM, bg=BG).pack(anchor="w", padx=4, pady=(2, 1))
        self.response_box = tk.Text(rl, bg=CARD, fg=TEXT, insertbackground=TEXT,
                                    font=MONO, relief="flat", padx=8, pady=6,
                                    state="disabled")
        self.response_box.tag_config("ok",  foreground=GREEN)
        self.response_box.tag_config("err", foreground=RED)
        self.response_box.tag_config("dim", foreground=DIM)
        self.response_box.pack(fill="both", expand=True)
        panes.add(rl, minsize=200)

        self._set_payload(DEFAULT_PAYLOADS.get("echo", "{}"))

    # ──────────────────────────────────────────────────────────────────────
    # Brick card helpers
    # ──────────────────────────────────────────────────────────────────────

    def _refresh_bricks(self):
        for w in self.brick_frame.winfo_children():
            w.destroy()

        components = self.wb.list_components()
        caps = set()

        for brick_id in components:
            info = self.wb.inspect(brick_id)
            caps.update(info.get("capabilities", []))
            self._make_brick_card(brick_id, info)

        # update capability dropdown
        cap_list = sorted(caps)
        self.cap_box["values"] = cap_list
        if cap_list and not self.cap_var.get():
            self.cap_var.set(cap_list[0])
            self._on_cap_change()

        # runtime summary
        try:
            h = self.wb.health()
            rt = h.get("runtime", {})
            self.runtime_lbl.config(
                text=f"total req: {rt.get('total_requests',0)}  "
                     f"ok: {rt.get('successful_requests',0)}  "
                     f"fail: {rt.get('failed_requests',0)}  "
                     f"avg latency: {rt.get('average_latency',0)*1000:.2f} ms"
            )
        except Exception:
            pass

    def _make_brick_card(self, brick_id: str, info: dict):
        loaded = info.get("loaded", False)
        clr    = state_colour(info)
        state  = info.get("state", "?")

        card = tk.Frame(self.brick_frame, bg=CARD, pady=6, padx=8,
                        highlightbackground=clr, highlightthickness=1)
        card.pack(fill="x", padx=6, pady=3)

        # name + state dot
        top = tk.Frame(card, bg=CARD)
        top.pack(fill="x")
        tk.Label(top, text="●", fg=clr, bg=CARD, font=("Segoe UI", 12)).pack(side="left")
        tk.Label(top, text=info.get("name", brick_id), font=UI_B,
                 fg=TEXT, bg=CARD).pack(side="left", padx=4)
        tk.Label(top, text=info.get("version",""), font=UI_SB,
                 fg=DIM, bg=CARD).pack(side="right")

        # caps + state
        tk.Label(card, text="  ".join(info.get("capabilities", [])),
                 font=UI_SB, fg=BLUE, bg=CARD, anchor="w").pack(fill="x")
        tk.Label(card, text=f"state: {state}   "
                            f"req: {info.get('successful_requests',0)}/{info.get('total_requests', info.get('successful_requests',0)+info.get('failed_requests',0))}   "
                            f"latency: {info.get('average_latency',0)*1000:.2f} ms",
                 font=UI_SB, fg=DIM, bg=CARD, anchor="w").pack(fill="x")

        # load / unload buttons
        btn_row = tk.Frame(card, bg=CARD)
        btn_row.pack(fill="x", pady=(4, 0))

        def _load(bid=brick_id):
            try:
                self.wb.load(bid)
                self._log(f"Loaded: {bid}", "ok")
            except Exception as e:
                self._log(f"Load error: {e}", "err")
            self._refresh_bricks()

        def _unload(bid=brick_id):
            try:
                self.wb.unload(bid)
                self._log(f"Unloaded: {bid}", "dim")
            except Exception as e:
                self._log(f"Unload error: {e}", "err")
            self._refresh_bricks()

        load_state   = "disabled" if loaded else "normal"
        unload_state = "normal" if loaded else "disabled"

        tk.Button(btn_row, text="Load", font=UI_SB, bg=GREEN, fg=BG,
                  relief="flat", padx=8, state=load_state,
                  command=_load).pack(side="left", padx=(0, 4))
        tk.Button(btn_row, text="Unload", font=UI_SB, bg=YELLOW, fg=BG,
                  relief="flat", padx=8, state=unload_state,
                  command=_unload).pack(side="left")

        # inspect button — shows full JSON
        def _inspect(bid=brick_id):
            data = self.wb.inspect(bid)
            self._write_response(json.dumps(data, indent=2, default=str), "ok")

        tk.Button(btn_row, text="Inspect", font=UI_SB, bg=BORDER, fg=TEXT,
                  relief="flat", padx=8, command=_inspect).pack(side="right")

    # ──────────────────────────────────────────────────────────────────────
    # Request execution
    # ──────────────────────────────────────────────────────────────────────

    def _run_request(self):
        cap = self.cap_var.get()
        if not cap:
            messagebox.showwarning("No capability", "Select a capability first.")
            return
        raw = self.payload_box.get("1.0", "end").strip()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as e:
            self._write_response(f"JSON parse error: {e}", "err")
            return

        try:
            timeout = float(self.timeout_var.get())
        except ValueError:
            timeout = None  # blank = no timeout, fast in-process path

        self.run_btn.config(state="disabled", text="⏳ Running…")
        self.status_lbl.config(text="sending…", fg=YELLOW)
        self._write_response("", "dim")

        def _worker():
            t0 = time.perf_counter()
            try:
                result = self.wb.request(cap, payload, timeout=timeout)
                elapsed = (time.perf_counter() - t0) * 1000
                text = json.dumps(result, indent=2, default=str)
                tag  = "ok"
                status = f"✓  {elapsed:.1f} ms"
            except Exception as e:
                elapsed = (time.perf_counter() - t0) * 1000
                text = f"Exception ({type(e).__name__}):\n{e}"
                tag  = "err"
                status = f"✗  {elapsed:.1f} ms"
            self.after(0, lambda: self._on_result(text, tag, status))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_result(self, text, tag, status):
        self._write_response(text, tag)
        self.status_lbl.config(text=status, fg=GREEN if tag == "ok" else RED)
        self.run_btn.config(state="normal", text="▶  Run Request")
        self._refresh_bricks()

    # ──────────────────────────────────────────────────────────────────────
    # Install .wb file
    # ──────────────────────────────────────────────────────────────────────

    def _install_wb(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Select .wb brick", filetypes=[("WhiteBase Brick", "*.wb"), ("All", "*.*")]
        )
        if not path:
            return
        try:
            self.wb.install(path)
            self._log(f"Installed: {os.path.basename(path)}", "ok")
            self._refresh_bricks()
        except Exception as e:
            self._log(f"Install error: {e}", "err")

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────

    def _on_cap_change(self, _e=None):
        cap = self.cap_var.get()
        default = DEFAULT_PAYLOADS.get(cap, '{\n  \n}')
        self._set_payload(default)

    def _set_payload(self, text: str):
        self.payload_box.delete("1.0", "end")
        self.payload_box.insert("1.0", text)

    def _write_response(self, text: str, tag: str):
        self.response_box.config(state="normal")
        self.response_box.delete("1.0", "end")
        self.response_box.insert("1.0", text, tag)
        self.response_box.config(state="disabled")

    def _log(self, msg: str, tag: str):
        self._write_response(msg, tag)

    def _auto_refresh(self):
        """Refresh brick cards every 2 s so stats update live."""
        self._refresh_bricks()
        self.after(2000, self._auto_refresh)


if __name__ == "__main__":
    Inspector().mainloop()

