"""Tkinter viewer: run as a module or directly as python fieldfox_recording/gui.py."""
from __future__ import annotations

from pathlib import Path
import queue
import threading
from typing import Any, Callable

# IDE Run File and double-click launches do not set the package context.
# Anchor imports to this checkout, independent of the current directory.
if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "fieldfox_recording"

from .parser import FieldFoxRecording, RecordingError
from .spectrogram import load_section, plot_section


class FieldFoxApp:
    def __init__(self, root: Any):
        import tkinter as tk
        from tkinter import ttk
        self.root = root
        self.rec = self.section = self.canvas = self.toolbar = self.figure = None
        self.loaded_options = None
        self.busy = False
        self.results: queue.Queue = queue.Queue()
        root.title("FieldFox recording viewer")
        root.geometry("1180x820")
        root.minsize(980, 720)
        self.path = tk.StringVar()
        self.status = tk.StringVar(value="Select a complete RTAUTOsession folder, then load a section.")
        outer = ttk.Frame(root, padding=10); outer.pack(fill="both", expand=True)
        folder = ttk.Frame(outer); folder.pack(fill="x", pady=(0, 10))
        ttk.Label(folder, text="Session folder").pack(side="left")
        ttk.Entry(folder, textvariable=self.path).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(folder, text="Browse…", command=self.browse).pack(side="left")
        content = ttk.Frame(outer); content.pack(fill="both", expand=True)
        controls = ttk.Frame(content); controls.pack(side="left", fill="y", padx=(0, 12))
        self.plot_frame = ttk.Frame(content); self.plot_frame.pack(side="left", fill="both", expand=True)
        self.values = {}
        fields = [("start", "First sweep (included)", "0"), ("stop", "Stop sweep (excluded; blank=end)", ""),
                  ("step", "Read every Nth sweep", "1"), ("max", "Maximum displayed sweeps", "2000"),
                  ("fmin", "Minimum frequency (MHz)", ""), ("fmax", "Maximum frequency (MHz)", ""),
                  ("slot", "Trace slot (zero-based)", "0"), ("vmin", "Minimum color power (dBm)", "-110"),
                  ("vmax", "Maximum color power (dBm)", "-30")]
        row = 0
        for key, label, default in fields:
            self.values[key] = tk.StringVar(value=default)
            ttk.Label(controls, text=label).grid(row=row, column=0, sticky="w")
            ttk.Entry(controls, textvariable=self.values[key], width=27).grid(row=row+1, column=0, sticky="ew", pady=(0, 5))
            row += 2
        self.cmap = tk.StringVar(value="viridis")
        ttk.Label(controls, text="Color map").grid(row=row, column=0, sticky="w")
        ttk.Combobox(controls, textvariable=self.cmap, values=["viridis", "turbo", "inferno", "plasma", "gray"], state="readonly", width=25).grid(row=row+1, column=0, sticky="ew")
        self.timezone = tk.StringVar(value="EST")
        ttk.Label(controls, text="Assumed instrument clock zone").grid(row=row+2, column=0, sticky="w", pady=(7, 0))
        ttk.Combobox(controls, textvariable=self.timezone, values=["EST", "UTC", "America/New_York", "+00:00", "-05:00"], width=25).grid(row=row+3, column=0, sticky="ew")
        ttk.Label(controls, text="EST = fixed UTC−05:00", foreground="#555555").grid(row=row+4, column=0, sticky="w")
        self.fold = tk.StringVar(value="Ask if ambiguous")
        ttk.Combobox(controls, textvariable=self.fold, values=["Ask if ambiguous", "Earlier occurrence", "Later occurrence"], state="readonly", width=25).grid(row=row+5, column=0, sticky="ew", pady=(4, 6))
        ttk.Button(controls, text="Load / update plot", command=self.load).grid(row=row+6, column=0, sticky="ew", pady=3)
        buttons = ttk.Frame(outer); buttons.pack(fill="x", pady=(10, 5))
        for label, command in [("Export section .mat", self.export_mat), ("Save plot image", self.save_image),
                               ("Export full session CSV", lambda: self.export_full("csv")),
                               ("Export full session NPZ", lambda: self.export_full("npz"))]:
            ttk.Button(buttons, text=label, command=command).pack(side="left", padx=(0, 7))
        ttk.Label(outer, textvariable=self.status, wraplength=1120).pack(fill="x")
        root.after(100, self._poll)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def browse(self) -> None:
        from tkinter import filedialog
        path = filedialog.askdirectory(title="Select the folder containing dSTA00000 and dTRC00000")
        if path:
            self.path.set(path)

    def _selection(self) -> dict:
        v = {key: value.get().strip() for key, value in self.values.items()}
        return dict(start_sweep=int(v["start"]), stop_sweep=int(v["stop"]) if v["stop"] else None,
                    step=int(v["step"]), max_sweeps=int(v["max"]), trace_slot=int(v["slot"]),
                    freq_min_hz=float(v["fmin"])*1e6 if v["fmin"] else None,
                    freq_max_hz=float(v["fmax"])*1e6 if v["fmax"] else None)

    def _plot_options(self) -> dict:
        return dict(vmin=float(self.values["vmin"].get()) if self.values["vmin"].get().strip() else None,
                    vmax=float(self.values["vmax"].get()) if self.values["vmax"].get().strip() else None,
                    cmap=self.cmap.get())

    def _error(self, error: Exception) -> None:
        from tkinter import messagebox
        self.status.set(str(error))
        messagebox.showerror("FieldFox viewer", str(error), parent=self.root)

    def _job(self, work: Callable, done: Callable, message: str) -> None:
        if self.busy:
            self.status.set("Please wait for the current read or export to finish.")
            return
        self.busy = True; self.status.set(message)
        def worker():
            try:
                self.results.put((done, work(), None))
            except Exception as error:
                self.results.put((done, None, error))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self) -> None:
        try:
            done, value, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            try:
                if error is not None:
                    raise error
                done(value)
            except Exception as error:
                self._error(error)
        self.root.after(100, self._poll)

    def load(self) -> None:
        try:
            path = self.path.get().strip()
            if not path:
                raise RecordingError("Select a complete recording session folder.")
            selection, colors = self._selection(), self._plot_options()
        except (ValueError, RecordingError) as error:
            self._error(error); return
        def work():
            rec = FieldFoxRecording.open(path)
            return rec, load_section(rec, **selection)
        def done(result):
            from matplotlib.figure import Figure
            rec, section = result
            figure, _ = plot_section(section, title=rec.path.name,
                                     figure=Figure(figsize=(9, 6), layout="constrained"), **colors)
            self._embed(figure)
            self.rec, self.section = rec, section
            self.loaded_options = (path, selection, colors)
            self.status.set(f"{rec.metadata['application_name']}: {len(rec)} total sweeps. Selected {len(section.sweep_indices)} × {len(section.frequency_hz)} bins, row step {section.effective_step}. MAT export saves this selection.")
        self._job(work, done, "Reading selected sweeps…")

    def _embed(self, figure: Any) -> None:
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        import matplotlib.pyplot as plt
        if self.toolbar is not None:
            self.toolbar.destroy()
        if self.canvas is not None:
            self.canvas.get_tk_widget().destroy()
        if self.figure is not None:
            plt.close(self.figure)
        self.figure = figure
        self.canvas = FigureCanvasTkAgg(figure, master=self.plot_frame)
        self.toolbar = NavigationToolbar2Tk(self.canvas, self.plot_frame, pack_toolbar=False)
        self.toolbar.update(); self.toolbar.pack(side="bottom", fill="x")
        self.canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        self.canvas.draw()

    def _ready(self, *, plot: bool = False) -> bool:
        if self.busy:
            self.status.set("Please wait for the current read or export to finish."); return False
        try:
            if self.section is None:
                raise RecordingError("Load a section first.")
            path, selection, colors = self.loaded_options
            if path != self.path.get().strip() or selection != self._selection() or (plot and colors != self._plot_options()):
                raise RecordingError("Click Load / update plot to apply the changed controls before exporting.")
        except (ValueError, RecordingError) as error:
            self._error(error); return False
        return True

    def export_mat(self) -> None:
        from tkinter import filedialog
        from .matlab import save_section_mat
        if not self._ready(): return
        target = filedialog.asksaveasfilename(title="Export selected spectrum data", defaultextension=".mat", confirmoverwrite=False, filetypes=[("MATLAB data", "*.mat")])
        if not target: return
        zone = self.timezone.get().strip() or None
        fold = {"Ask if ambiguous": None, "Earlier occurrence": 0, "Later occurrence": 1}[self.fold.get()]
        self._job(lambda: save_section_mat(self.rec, self.section, target, source_timezone=zone, dst_fold=fold),
                  lambda _: self.status.set(f"Saved {target}; source clock assumption: {zone or 'unspecified'}."), "Exporting selected data to MATLAB…")

    def save_image(self) -> None:
        from tkinter import filedialog
        from .export import _destination
        if not self._ready(plot=True): return
        target = filedialog.asksaveasfilename(title="Save current plot", defaultextension=".png", confirmoverwrite=False, filetypes=[("PNG image", "*.png"), ("PDF figure", "*.pdf")])
        if not target: return
        try:
            with _destination(self.rec, target) as temporary:
                self.figure.savefig(temporary, format=Path(target).suffix.lstrip(".") or "png", dpi=160)
            self.status.set(f"Saved plot to {target}")
        except Exception as error:
            self._error(error)

    def export_full(self, kind: str) -> None:
        from tkinter import filedialog
        if not self._ready(): return
        target = filedialog.asksaveasfilename(title=f"Export every sweep in the session as {kind.upper()}", defaultextension=f".{kind}", confirmoverwrite=False)
        if target:
            self._job(lambda: getattr(self.rec, f"to_{kind}")(target),
                      lambda _: self.status.set(f"Exported full session to {target}. CSV/NPZ retain the original instrument clock."), "Exporting full session…")

    def close(self) -> None:
        if self.figure is not None:
            import matplotlib.pyplot as plt
            plt.close(self.figure)
        self.root.destroy()


def main() -> int:
    try:
        import tkinter as tk
        root = tk.Tk()
        FieldFoxApp(root)
        root.mainloop()
    except ImportError as error:
        raise RecordingError("GUI needs Tkinter and Matplotlib: install '.[plot]' and a Python build with Tk support.") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
