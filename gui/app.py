#!/usr/bin/env python3
"""
Tkinter front-end for hud_overlay/render_overlay.py and tools/csv_to_vbo.py.

Pick a CSV, pick a HUD style, choose what to export, hit Render -- or switch
to the Export VBO tab to convert the same CSV for a lap-analysis tool. Both
run the existing CLI scripts as a subprocess -- the same thing
scripts/render_video.ps1 does -- and stream their output into this window.
No changes to either script are needed for this to work.
"""

import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from tkinter import BooleanVar, END, StringVar, Tk, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

REPO_ROOT = Path(__file__).resolve().parent.parent
RENDER_SCRIPT = REPO_ROOT / "hud_overlay" / "render_overlay.py"
CONFIGS_DIR = REPO_ROOT / "hud_overlay" / "configs"
VBO_SCRIPT = REPO_ROOT / "tools" / "csv_to_vbo.py"

# Canvas size to default to per style, keyed by config filename stem.
DEFAULT_SIZES = {"vertical_reels": (1080, 1920)}

PROGRESS_RE = re.compile(r"^\s*([\d.]+)\s*s\s*/\s*([\d.]+)\s*s")


def list_configs():
    return sorted(CONFIGS_DIR.glob("*.json"))


class RenderGUI:
    def __init__(self, root):
        self.root = root
        root.title("HUD Overlay Renderer")

        self.csv_path = StringVar()
        self.config_path = StringVar()
        self.config_display = StringVar()
        self._config_by_name = {}
        self.out_path = StringVar()
        self.width = StringVar(value="1920")
        self.height = StringVar(value="1080")
        self.fps = StringVar(value="59.94")
        self.codec = StringVar(value="h264")
        self.crf = StringVar(value="20")
        self.bg_color = StringVar(value="black")
        self.workers = StringVar(value=str(os.cpu_count() or 4))
        self.full_frame = BooleanVar(value=False)
        self.map_enabled = BooleanVar(value=False)
        self.start = StringVar()
        self.duration = StringVar()

        self.proc = None
        self._cancelled = False
        self.log_queue = queue.Queue()

        self.vbo_csv_path = StringVar()
        self.vbo_out_path = StringVar()
        self.vbo_start_utc = StringVar()
        self.vbo_tz_offset = StringVar(value="-6.0")
        self.vbo_proc = None
        self.vbo_log_queue = queue.Queue()

        self._build()

    # ---------------------------------------------------------------- layout

    def _build(self):
        notebook = ttk.Notebook(self.root)
        notebook.grid(row=0, column=0, sticky="nsew")
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        render_tab = ttk.Frame(notebook)
        vbo_tab = ttk.Frame(notebook)
        notebook.add(render_tab, text="Render video")
        notebook.add(vbo_tab, text="Export VBO (lap analysis)")

        self._build_render_tab(render_tab)
        self._build_vbo_tab(vbo_tab)

        self.root.update_idletasks()
        self.root.minsize(self.root.winfo_reqwidth(), self.root.winfo_reqheight())

    def _build_render_tab(self, parent):
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(parent, padding=8)
        frm.grid(row=0, column=0, sticky="nsew")
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        row = 0

        ttk.Label(frm, text="CSV log").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.csv_path, width=52).grid(row=row, column=1, **pad)
        ttk.Button(frm, text="Browse...", command=self._pick_csv).grid(row=row, column=2, **pad)
        row += 1

        ttk.Label(frm, text="Style").grid(row=row, column=0, sticky="w", **pad)
        self._config_by_name = {p.stem: str(p) for p in list_configs()}
        self.config_combo = ttk.Combobox(frm, textvariable=self.config_display, width=49, state="readonly")
        self.config_combo["values"] = list(self._config_by_name.keys())
        self.config_combo.grid(row=row, column=1, sticky="we", **pad)
        self.config_combo.bind("<<ComboboxSelected>>", lambda e: self._on_config_change())
        if self.config_combo["values"]:
            self.config_combo.current(0)
            self._on_config_change()
        row += 1

        ttk.Label(frm, text="Output video").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.out_path, width=52).grid(row=row, column=1, **pad)
        ttk.Button(frm, text="Save as...", command=self._pick_out).grid(row=row, column=2, **pad)
        row += 1

        size_frm = ttk.Frame(frm)
        size_frm.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(size_frm, text="Width").pack(side="left")
        ttk.Entry(size_frm, textvariable=self.width, width=6).pack(side="left", padx=(4, 16))
        ttk.Label(size_frm, text="Height").pack(side="left")
        ttk.Entry(size_frm, textvariable=self.height, width=6).pack(side="left", padx=(4, 16))
        ttk.Label(size_frm, text="FPS").pack(side="left")
        ttk.Entry(size_frm, textvariable=self.fps, width=8).pack(side="left", padx=(4, 0))
        row += 1

        codec_frm = ttk.Frame(frm)
        codec_frm.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(codec_frm, text="Format").pack(side="left")
        ttk.Radiobutton(codec_frm, text="h.264 (.mp4, small, no transparency)", variable=self.codec,
                        value="h264", command=self._on_codec_change).pack(side="left", padx=(4, 16))
        ttk.Radiobutton(codec_frm, text="ProRes 4444 (.mov, transparent, huge)", variable=self.codec,
                        value="prores", command=self._on_codec_change).pack(side="left")
        row += 1

        self.h264_frm = ttk.Frame(frm)
        self.h264_frm.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(self.h264_frm, text="Quality (CRF, lower = better)").pack(side="left")
        ttk.Entry(self.h264_frm, textvariable=self.crf, width=4).pack(side="left", padx=(4, 16))
        ttk.Label(self.h264_frm, text="Background color").pack(side="left")
        ttk.Entry(self.h264_frm, textvariable=self.bg_color, width=10).pack(side="left", padx=(4, 0))
        row += 1

        opts_frm = ttk.Frame(frm)
        opts_frm.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        ttk.Checkbutton(opts_frm, text="Include GPS map clip", variable=self.map_enabled).pack(
            side="left", padx=(0, 16))
        ttk.Checkbutton(opts_frm, text="Full frame (place HUD per config, not just the panel)",
                        variable=self.full_frame).pack(side="left")
        row += 1

        trim_frm = ttk.Frame(frm)
        trim_frm.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(trim_frm, text="Start at (s, blank = beginning)").pack(side="left")
        ttk.Entry(trim_frm, textvariable=self.start, width=8).pack(side="left", padx=(4, 16))
        ttk.Label(trim_frm, text="Duration (s, blank = to end)").pack(side="left")
        ttk.Entry(trim_frm, textvariable=self.duration, width=8).pack(side="left", padx=(4, 16))
        ttk.Label(trim_frm, text="Workers").pack(side="left")
        ttk.Entry(trim_frm, textvariable=self.workers, width=4).pack(side="left", padx=(4, 0))
        row += 1

        btn_frm = ttk.Frame(frm)
        btn_frm.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        self.render_btn = ttk.Button(btn_frm, text="Render", command=self._start_render)
        self.render_btn.pack(side="left")
        self.cancel_btn = ttk.Button(btn_frm, text="Cancel", command=self._cancel_render, state="disabled")
        self.cancel_btn.pack(side="left", padx=(8, 0))
        row += 1

        self.phase_label = ttk.Label(frm, text="Pick a CSV and a style, then Render.")
        self.phase_label.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        row += 1

        self.progress = ttk.Progressbar(frm, length=580, mode="determinate")
        self.progress.grid(row=row, column=0, columnspan=3, **pad)
        row += 1

        self.log = ScrolledText(frm, width=78, height=14, state="disabled")
        self.log.grid(row=row, column=0, columnspan=3, sticky="nsew", **pad)

        frm.grid_rowconfigure(row, weight=1)
        frm.grid_columnconfigure(1, weight=1)

    def _build_vbo_tab(self, parent):
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(parent, padding=8)
        frm.grid(row=0, column=0, sticky="nsew")
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        row = 0

        ttk.Label(frm, text="CSV log").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.vbo_csv_path, width=52).grid(row=row, column=1, **pad)
        ttk.Button(frm, text="Browse...", command=self._pick_vbo_csv).grid(row=row, column=2, **pad)
        row += 1

        ttk.Label(frm, text="Output .vbo").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.vbo_out_path, width=52).grid(row=row, column=1, **pad)
        ttk.Button(frm, text="Save as...", command=self._pick_vbo_out).grid(row=row, column=2, **pad)
        row += 1

        opts_frm = ttk.Frame(frm)
        opts_frm.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(opts_frm, text="Start time, UTC ISO-8601 (blank = guess from filename)").pack(side="left")
        ttk.Entry(opts_frm, textvariable=self.vbo_start_utc, width=22).pack(side="left", padx=(4, 16))
        ttk.Label(opts_frm, text="TZ offset (h)").pack(side="left")
        ttk.Entry(opts_frm, textvariable=self.vbo_tz_offset, width=6).pack(side="left", padx=(4, 0))
        row += 1

        ttk.Label(frm, text="Converts the CSV's GPS track to a RaceLogic .vbo file for lap-analysis\n"
                            "tools (Track Data Analysis, onTrackTools, Trackday Plot, ...). Only needed\n"
                            "if the CSV's own 'time' column isn't absolute and its filename doesn't\n"
                            "encode a wall-clock start time -- the converter will say so if so.",
                  justify="left", foreground="#555").grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        row += 1

        btn_frm = ttk.Frame(frm)
        btn_frm.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        self.vbo_btn = ttk.Button(btn_frm, text="Export VBO", command=self._start_vbo_export)
        self.vbo_btn.pack(side="left")
        row += 1

        self.vbo_phase_label = ttk.Label(frm, text="Pick a CSV, then Export VBO.")
        self.vbo_phase_label.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        row += 1

        self.vbo_log = ScrolledText(frm, width=78, height=14, state="disabled")
        self.vbo_log.grid(row=row, column=0, columnspan=3, sticky="nsew", **pad)

        frm.grid_rowconfigure(row, weight=1)
        frm.grid_columnconfigure(1, weight=1)

    # ---------------------------------------------------------------- actions

    def _pick_csv(self):
        path = filedialog.askopenfilename(title="Pick a recorded CSV log",
                                          filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        self.csv_path.set(path)
        if not self.out_path.get():
            self._suggest_out_path()

    def _pick_out(self):
        ext = ".mp4" if self.codec.get() == "h264" else ".mov"
        initial = self.out_path.get() or ""
        initdir = str(Path(initial).parent) if initial else str(Path(self.csv_path.get()).parent
                                                                 if self.csv_path.get() else REPO_ROOT)
        path = filedialog.asksaveasfilename(title="Save rendered video as", defaultextension=ext,
                                            initialdir=initdir,
                                            filetypes=[("Video", f"*{ext}"), ("All files", "*.*")])
        if path:
            self.out_path.set(path)

    def _suggest_out_path(self):
        csv = Path(self.csv_path.get())
        style = Path(self.config_path.get()).stem if self.config_path.get() else "hud"
        ext = ".mp4" if self.codec.get() == "h264" else ".mov"
        self.out_path.set(str(csv.with_name(f"{csv.stem}_{style}{ext}")))

    def _on_config_change(self):
        name = self.config_display.get()
        self.config_path.set(self._config_by_name.get(name, ""))
        w, h = DEFAULT_SIZES.get(name, (1920, 1080))
        self.width.set(str(w))
        self.height.set(str(h))
        if self.csv_path.get():
            self._suggest_out_path()

    def _on_codec_change(self):
        state = "normal" if self.codec.get() == "h264" else "disabled"
        for child in self.h264_frm.winfo_children():
            child.configure(state=state)
        if self.out_path.get():
            self._suggest_out_path()

    # ---------------------------------------------------------------- render

    def _start_render(self):
        if not self.csv_path.get() or not Path(self.csv_path.get()).is_file():
            messagebox.showerror("Missing CSV", "Pick a CSV log first.")
            return
        if not self.config_path.get():
            messagebox.showerror("Missing style", "Pick a HUD style first.")
            return
        if not self.out_path.get():
            self._suggest_out_path()

        try:
            width, height = int(self.width.get()), int(self.height.get())
            workers = int(self.workers.get())
        except ValueError:
            messagebox.showerror("Bad input", "Width, height and workers must be whole numbers.")
            return

        try:
            temp_config = self._build_temp_config()
        except (OSError, ValueError) as e:
            messagebox.showerror("Bad style file", f"Couldn't read that config: {e}")
            return

        cmd = [sys.executable, str(RENDER_SCRIPT),
               "--csv", self.csv_path.get(), "--config", temp_config, "--out", self.out_path.get(),
               "--width", str(width), "--height", str(height), "--fps", self.fps.get(),
               "--codec", self.codec.get(), "--workers", str(workers)]
        if self.codec.get() == "h264":
            cmd += ["--crf", self.crf.get(), "--bg-color", self.bg_color.get()]
        if self.full_frame.get():
            cmd.append("--full-frame")
        if self.start.get().strip():
            cmd += ["--start", self.start.get().strip()]
        if self.duration.get().strip():
            cmd += ["--duration", self.duration.get().strip()]

        self._cancelled = False
        self.render_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.phase_label.config(text="Starting...")
        self.progress["value"] = 0
        self.log.configure(state="normal")
        self.log.delete("1.0", END)
        self.log.configure(state="disabled")

        threading.Thread(target=self._run_process, args=(cmd, temp_config), daemon=True).start()
        self.root.after(100, self._poll_queue)

    def _build_temp_config(self):
        with open(self.config_path.get()) as f:
            data = json.load(f)
        data.setdefault("map", {})["enabled"] = bool(self.map_enabled.get())
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(data, tmp)
        tmp.close()
        return tmp.name

    def _run_process(self, cmd, temp_config):
        try:
            self.proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT), stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in self.proc.stdout:
                self.log_queue.put(("line", line.rstrip()))
            self.proc.wait()
            self.log_queue.put(("done", self.proc.returncode))
        except OSError as e:
            self.log_queue.put(("error", str(e)))
        finally:
            try:
                os.unlink(temp_config)
            except OSError:
                pass

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "line":
                    self._handle_line(payload)
                elif kind == "done":
                    self._on_finished(payload)
                    return
                elif kind == "error":
                    self._on_error(payload)
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _handle_line(self, line):
        self.log.configure(state="normal")
        self.log.insert(END, line + "\n")
        self.log.see(END)
        self.log.configure(state="disabled")

        if line.startswith("rendering map:"):
            self.phase_label.config(text="Rendering GPS map clip...")
            self.progress["value"] = 0
        elif line.startswith("rendering "):
            self.phase_label.config(text="Rendering HUD clip...")
            self.progress["value"] = 0
        else:
            m = PROGRESS_RE.match(line)
            if m:
                cur, total = float(m.group(1)), float(m.group(2))
                self.progress["value"] = 100 * cur / total if total else 0

    def _on_finished(self, returncode):
        self.render_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        self.proc = None
        if self._cancelled:
            self.phase_label.config(text="Cancelled.")
        elif returncode == 0:
            self.progress["value"] = 100
            self.phase_label.config(text="Done.")
            messagebox.showinfo("Render complete", f"Saved to:\n{self.out_path.get()}")
        else:
            self.phase_label.config(text=f"Failed (exit code {returncode}) -- see the log above.")
            messagebox.showerror("Render failed",
                                 f"render_overlay.py exited with code {returncode}.\nSee the log for details.")

    def _on_error(self, message):
        self.render_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        self.proc = None
        self.phase_label.config(text="Failed to start.")
        messagebox.showerror("Couldn't start render", message)

    def _cancel_render(self):
        if self.proc and self.proc.poll() is None:
            self._cancelled = True
            self.proc.terminate()
            self.phase_label.config(text="Cancelling...")

    # ------------------------------------------------------------ vbo export

    def _pick_vbo_csv(self):
        path = filedialog.askopenfilename(title="Pick a recorded CSV log",
                                          filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        self.vbo_csv_path.set(path)
        if not self.vbo_out_path.get():
            self.vbo_out_path.set(str(Path(path).with_suffix(".vbo")))

    def _pick_vbo_out(self):
        initial = self.vbo_out_path.get() or ""
        initdir = str(Path(initial).parent) if initial else str(Path(self.vbo_csv_path.get()).parent
                                                                 if self.vbo_csv_path.get() else REPO_ROOT)
        path = filedialog.asksaveasfilename(title="Save .vbo as", defaultextension=".vbo",
                                            initialdir=initdir,
                                            filetypes=[("VBO", "*.vbo"), ("All files", "*.*")])
        if path:
            self.vbo_out_path.set(path)

    def _start_vbo_export(self):
        if not self.vbo_csv_path.get() or not Path(self.vbo_csv_path.get()).is_file():
            messagebox.showerror("Missing CSV", "Pick a CSV log first.")
            return
        if not self.vbo_out_path.get():
            self.vbo_out_path.set(str(Path(self.vbo_csv_path.get()).with_suffix(".vbo")))

        try:
            tz_offset = float(self.vbo_tz_offset.get())
        except ValueError:
            messagebox.showerror("Bad input", "TZ offset must be a number.")
            return

        cmd = [sys.executable, str(VBO_SCRIPT),
               "--csv", self.vbo_csv_path.get(), "--out", self.vbo_out_path.get(),
               "--tz-offset", str(tz_offset)]
        if self.vbo_start_utc.get().strip():
            cmd += ["--start-utc", self.vbo_start_utc.get().strip()]

        self.vbo_btn.config(state="disabled")
        self.vbo_phase_label.config(text="Converting...")
        self.vbo_log.configure(state="normal")
        self.vbo_log.delete("1.0", END)
        self.vbo_log.configure(state="disabled")

        threading.Thread(target=self._run_vbo_process, args=(cmd,), daemon=True).start()
        self.root.after(100, self._poll_vbo_queue)

    def _run_vbo_process(self, cmd):
        try:
            self.vbo_proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT), stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in self.vbo_proc.stdout:
                self.vbo_log_queue.put(("line", line.rstrip()))
            self.vbo_proc.wait()
            self.vbo_log_queue.put(("done", self.vbo_proc.returncode))
        except OSError as e:
            self.vbo_log_queue.put(("error", str(e)))

    def _poll_vbo_queue(self):
        try:
            while True:
                kind, payload = self.vbo_log_queue.get_nowait()
                if kind == "line":
                    self.vbo_log.configure(state="normal")
                    self.vbo_log.insert(END, payload + "\n")
                    self.vbo_log.see(END)
                    self.vbo_log.configure(state="disabled")
                elif kind == "done":
                    self._on_vbo_finished(payload)
                    return
                elif kind == "error":
                    self._on_vbo_error(payload)
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._poll_vbo_queue)

    def _on_vbo_finished(self, returncode):
        self.vbo_btn.config(state="normal")
        self.vbo_proc = None
        if returncode == 0:
            self.vbo_phase_label.config(text="Done.")
            messagebox.showinfo("Export complete", f"Saved to:\n{self.vbo_out_path.get()}")
        else:
            self.vbo_phase_label.config(text=f"Failed (exit code {returncode}) -- see the log above.")
            messagebox.showerror("Export failed",
                                 f"csv_to_vbo.py exited with code {returncode}.\nSee the log for details.")

    def _on_vbo_error(self, message):
        self.vbo_btn.config(state="normal")
        self.vbo_proc = None
        self.vbo_phase_label.config(text="Failed to start.")
        messagebox.showerror("Couldn't start export", message)


def main():
    root = Tk()
    RenderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
