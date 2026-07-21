"""
gui/app.py
==========
Bertanggung jawab atas:
- Seluruh tampilan UI Tkinter (SequenceGUI)
- Event handler tombol dan tabel
- Update widget dari data telemetri (via after())

Tidak ada kode socket, eksekusi sekuens, atau logika robot di sini.
Semua logika dilimpahkan ke gui.logic.SequenceManager.
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import math
import os
import socket
import base64
import numpy as np
import cv2
from PIL import Image, ImageTk

from gui.logic import SequenceManager

class CameraWindow(tk.Toplevel):
    def __init__(self, master, on_close):
        super().__init__(master)
        self.title("Live Camera FPV & HSV Calibration")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.on_close = on_close
        
        self.running = True
        
        # Default HSV Ranges (OpenCV format)
        self.hsv_ranges = {
            "RED": {"h": [0, 10], "s": [100, 255], "v": [100, 255]},
            "GREEN": {"h": [40, 80], "s": [100, 255], "v": [100, 255]},
            "BLUE": {"h": [100, 140], "s": [100, 255], "v": [100, 255]}
        }
        
        try:
            import json
            with open("hsv_calibration.json", "r") as f:
                loaded = json.load(f)
                # Soft update to prevent key errors
                for k, v in loaded.items():
                    if k in self.hsv_ranges:
                        self.hsv_ranges[k].update(v)
        except Exception:
            pass
            
        
        self._build_ui()
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(2.0)
        try:
            self.sock.connect(('127.0.0.1', 5006))
        except Exception as e:
            print("Gagal connect ke Camera Server", e)
        
        self.thread = threading.Thread(target=self._recv_loop, daemon=True)
        self.thread.start()

    def _build_ui(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Left: Video
        left = ttk.Frame(main_frame)
        left.pack(side="left", fill="both", expand=True)
        
        self.lbl_video = ttk.Label(left, text="No Signal", background="black", foreground="white", anchor="center")
        self.lbl_video.pack(fill="both", expand=True)
        
        self.lbl_video.bind("<ButtonPress-1>", self._on_mouse_press)
        self.lbl_video.bind("<B1-Motion>", self._on_mouse_drag)
        self.lbl_video.bind("<ButtonRelease-1>", self._on_mouse_release)
        
        self.drag_start = None
        self.drag_end = None
        self.selection_box = (90, 90, 110, 110)
        
        self.lbl_result = ttk.Label(left, text="DETECTED: -", font=("Segoe UI", 14, "bold"))
        self.lbl_result.pack(pady=5)
        
        # Right: Sliders
        right = ttk.Frame(main_frame)
        right.pack(side="right", fill="y", padx=10)
        
        def _add_sliders(parent, color_name):
            f = ttk.LabelFrame(parent, text=color_name)
            f.pack(fill="x", pady=5)
            
            vars_dict = {}
            for channel in ["h", "s", "v"]:
                row = ttk.Frame(f)
                row.pack(fill="x")
                ttk.Label(row, text=channel.upper(), width=2).pack(side="left")
                
                v_min = tk.IntVar(value=self.hsv_ranges[color_name][channel][0])
                v_max = tk.IntVar(value=self.hsv_ranges[color_name][channel][1])
                vars_dict[channel] = (v_min, v_max)
                
                max_val = 179 if channel == "h" else 255
                
                # We use command to update values in real-time while sliding
                def make_cmd(c=color_name, ch=channel, vmin=v_min, vmax=v_max):
                    def cmd(val):
                        self.hsv_ranges[c][ch] = [vmin.get(), vmax.get()]
                        try:
                            import json
                            with open("hsv_calibration.json", "w") as f:
                                json.dump(self.hsv_ranges, f)
                        except:
                            pass
                    return cmd

                s_min = ttk.Scale(row, from_=0, to=max_val, variable=v_min, orient="horizontal", length=80, command=make_cmd())
                s_min.pack(side="left", padx=2)
                s_max = ttk.Scale(row, from_=0, to=max_val, variable=v_max, orient="horizontal", length=80, command=make_cmd())
                s_max.pack(side="left", padx=2)
                
            btn = ttk.Button(f, text=f"Auto Sample", command=lambda c=color_name, vd=vars_dict: self._auto_calibrate(c, vd))
            btn.pack(fill="x", padx=5, pady=5)
                
        _add_sliders(right, "RED")
        _add_sliders(right, "GREEN")
        _add_sliders(right, "BLUE")
        
    def _recv_loop(self):
        buffer = ""
        while self.running:
            try:
                data = self.sock.recv(16384).decode('ascii')
                if not data:
                    raise Exception("Disconnected")
                buffer += data
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line:
                        self._process_frame(line)
            except socket.timeout:
                continue
            except Exception as e:
                # Coba reconnect
                try: self.sock.close()
                except: pass
                
                self.lbl_video.after(0, lambda: self.lbl_video.config(image='', text="No Signal"))
                self.lbl_result.after(0, lambda: self.lbl_result.config(text="DETECTED: -"))
                
                import time
                time.sleep(1.0)
                
                if not self.running:
                    break
                    
                try:
                    self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.sock.settimeout(2.0)
                    self.sock.connect(('127.0.0.1', 5006))
                    buffer = ""
                except:
                    pass
                
    def _process_frame(self, b64_str):
        try:
            img_data = base64.b64decode(b64_str)
            np_arr = np.frombuffer(img_data, np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR) # BGR
            if img is None:
                return
            
            # Resize internal for faster processing (optional, already 200x200)
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            
            # Simpan sample untuk auto calibration dari selection_box
            h_img, w_img = img.shape[:2]
            x1, y1, x2, y2 = self.selection_box
            x1_s = max(0, min(w_img - 2, x1))
            y1_s = max(0, min(h_img - 2, y1))
            x2_s = max(x1_s + 2, min(w_img, x2))
            y2_s = max(y1_s + 2, min(h_img, y2))
            self.current_hsv_sample = hsv[y1_s:y2_s, x1_s:x2_s].copy()
            
            detected = "-"
            detected_color = (0, 0, 0)
            
            detected_list = []
            
            for cname, ranges in self.hsv_ranges.items():
                # Allow wrap-around for RED Hue (e.g. 170-10)
                h_min, h_max = ranges["h"]
                s_min, s_max = ranges["s"]
                v_min, v_max = ranges["v"]
                
                if h_min > h_max:
                    # Red wrap-around
                    lower1 = np.array([h_min, s_min, v_min])
                    upper1 = np.array([179, s_max, v_max])
                    mask1 = cv2.inRange(hsv, lower1, upper1)
                    
                    lower2 = np.array([0, s_min, v_min])
                    upper2 = np.array([h_max, s_max, v_max])
                    mask2 = cv2.inRange(hsv, lower2, upper2)
                    mask = cv2.bitwise_or(mask1, mask2)
                else:
                    lower = np.array([h_min, s_min, v_min])
                    upper = np.array([h_max, s_max, v_max])
                    mask = cv2.inRange(hsv, lower, upper)
                
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for cnt in contours:
                    area = cv2.contourArea(cnt)
                    if area > 100:
                        rect = cv2.boundingRect(cnt)
                        if cname == "RED": color = (0, 0, 255)
                        elif cname == "GREEN": color = (0, 255, 0)
                        else: color = (255, 0, 0)
                        
                        x, y, w, h = rect
                        cv2.rectangle(img, (x, y), (x+w, y+h), color, 2)
                        cv2.putText(img, cname, (x, y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                        if cname not in detected_list:
                            detected_list.append(cname)
                            
            detected = ", ".join(detected_list) if detected_list else "-"
                
            # Gambar crosshair/box target untuk auto sampling
            cv2.rectangle(img, (x1, y1), (x2, y2), (255, 255, 255), 1)
                
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(img_rgb)
            # Make it bigger for the UI
            pil_img = pil_img.resize((300, 300), Image.NEAREST)
            self.tk_img = ImageTk.PhotoImage(image=pil_img)
            
            self.lbl_video.after(0, self._update_image, detected)
        except Exception as e:
            pass
            
    def _update_image(self, detected):
        try:
            if hasattr(self, 'tk_img'):
                self.lbl_video.config(image=self.tk_img)
            self.lbl_result.config(text=f"DETECTED: {detected}")
        except Exception:
            pass
            
    def _on_mouse_press(self, event):
        self.drag_start = (event.x, event.y)
        self.drag_end = (event.x, event.y)

    def _on_mouse_drag(self, event):
        self.drag_end = (event.x, event.y)
        self._update_selection_box()

    def _on_mouse_release(self, event):
        self.drag_end = (event.x, event.y)
        self._update_selection_box()
        self.drag_start = None
        self.drag_end = None
        
    def _update_selection_box(self):
        if self.drag_start and self.drag_end:
            lw = self.lbl_video.winfo_width()
            lh = self.lbl_video.winfo_height()
            
            img_x = (lw - 300) // 2
            img_y = (lh - 300) // 2
            
            x1_ui = self.drag_start[0] - img_x
            y1_ui = self.drag_start[1] - img_y
            x2_ui = self.drag_end[0] - img_x
            y2_ui = self.drag_end[1] - img_y
            
            x1 = int(min(x1_ui, x2_ui) * 200 / 300)
            y1 = int(min(y1_ui, y2_ui) * 200 / 300)
            x2 = int(max(x1_ui, x2_ui) * 200 / 300)
            y2 = int(max(y1_ui, y2_ui) * 200 / 300)
            
            x1 = max(0, min(198, x1))
            y1 = max(0, min(198, y1))
            x2 = max(x1+2, min(200, x2))
            y2 = max(y1+2, min(200, y2))
            
            self.selection_box = (x1, y1, x2, y2)

    def _auto_calibrate(self, color_name, vars_dict):
        if getattr(self, 'current_hsv_sample', None) is None:
            return
            
        sample = self.current_hsv_sample
        h_vals = sample[:,:,0].flatten()
        s_vals = sample[:,:,1].flatten()
        v_vals = sample[:,:,2].flatten()
        
        s_min = max(0, int(np.percentile(s_vals, 5)) - 30)
        s_max = min(255, int(np.percentile(s_vals, 95)) + 30)
        v_min = max(0, int(np.percentile(v_vals, 5)) - 30)
        v_max = min(255, int(np.percentile(v_vals, 95)) + 30)
        
        if np.max(h_vals) - np.min(h_vals) > 90:
            high_vals = h_vals[h_vals > 90]
            low_vals = h_vals[h_vals <= 90]
            h_min = max(0, int(np.percentile(high_vals, 5)) - 10) if len(high_vals) > 0 else 0
            h_max = min(179, int(np.percentile(low_vals, 95)) + 10) if len(low_vals) > 0 else 179
        else:
            h_min = max(0, int(np.percentile(h_vals, 5)) - 10)
            h_max = min(179, int(np.percentile(h_vals, 95)) + 10)
            
        vars_dict["h"][0].set(h_min)
        vars_dict["h"][1].set(h_max)
        vars_dict["s"][0].set(s_min)
        vars_dict["s"][1].set(s_max)
        vars_dict["v"][0].set(v_min)
        vars_dict["v"][1].set(v_max)
        
        self.hsv_ranges[color_name]["h"] = [h_min, h_max]
        self.hsv_ranges[color_name]["s"] = [s_min, s_max]
        self.hsv_ranges[color_name]["v"] = [v_min, v_max]
        
        try:
            import json
            with open("hsv_calibration.json", "w") as f:
                json.dump(self.hsv_ranges, f)
        except Exception:
            pass

    def _on_close(self):
        self.running = False
        try:
            self.sock.close()
        except:
            pass
        self.on_close()
        self.destroy()

class SequenceGUI:
    """
    Tampilan utama GUI pengontrol robot dengan tema dominant color Elysia (Dark Space & Pink).

    Berinteraksi dengan simulator melalui self.manager (SequenceManager).
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Robot Movement Sequence System - Controller GUI")
        self.root.geometry("1300x680")

        # Inisialisasi manajer logika & komunikasi
        self.manager = SequenceManager(self)

        # ------------------------------------------------------------------
        # Setup Tema Monokrom (Tanpa Background Image)
        # ------------------------------------------------------------------
        self.bg_label = None

        # ------------------------------------------------------------------
        # Terapkan Warna Dominan Monokrom
        # ------------------------------------------------------------------
        BG_MAIN = "#121212"     # Dark gray/black
        BG_CARD = "#1e1e1e"     # Card Panel Dark Gray
        BG_INPUT = "#2d2d2d"    # Input fields
        TEXT_LIGHT = "#ffffff"  # White text
        PINK = "#cccccc"        # Light gray for accents
        CYAN = "#aaaaaa"        # Mid gray
        
        style = ttk.Style()
        style.theme_use("clam")
        
        # Window & Frame
        self.root.configure(background=BG_MAIN)
        style.configure("TFrame", background=BG_CARD)
        
        # LabelFrame (Panel Card)
        style.configure("TLabelframe", background=BG_CARD, bordercolor=BG_INPUT, lightcolor=BG_INPUT, darkcolor=BG_INPUT)
        style.configure("TLabelframe.Label", background=BG_CARD, foreground=PINK, font=("Segoe UI", 11, "bold"))
        
        # Label & Text
        style.configure("TLabel", background=BG_CARD, foreground=TEXT_LIGHT, font=("Segoe UI", 10))
        style.configure("Header.TLabel", background=BG_CARD, foreground=CYAN, font=("Segoe UI", 12, "bold"))
        
        # Input fields (Entry, Spinbox, Combobox)
        style.configure("TEntry", fieldbackground=BG_INPUT, foreground=TEXT_LIGHT, insertcolor=TEXT_LIGHT)
        style.configure("TSpinbox", fieldbackground=BG_INPUT, foreground=TEXT_LIGHT, arrowcolor=TEXT_LIGHT)
        style.configure("TCombobox", fieldbackground=BG_INPUT, foreground=TEXT_LIGHT, arrowcolor=TEXT_LIGHT)
        style.map("TCombobox", fieldbackground=[("readonly", BG_INPUT)], selectbackground=[("readonly", "#444444")])
        
        # Tables (Treeview)
        style.configure("Treeview", background=BG_INPUT, fieldbackground=BG_INPUT, foreground=TEXT_LIGHT, rowheight=24)
        style.configure("Treeview.Heading", background="#333333", foreground=TEXT_LIGHT, font=("Segoe UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#555555")])
        
        # Buttons
        style.configure("TButton", background="#333333", foreground=TEXT_LIGHT, font=("Segoe UI", 10, "bold"), padding=6)
        style.map("TButton",
                  background=[("active", "#555555"), ("disabled", "#111111")],
                  foreground=[("active", TEXT_LIGHT), ("disabled", "#666666")])
                  
        # Accent/Action Buttons
        style.configure("Accent.TButton", background=PINK, foreground=BG_MAIN, font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton",
                  background=[("active", "#eeeeee")],
                  foreground=[("active", BG_MAIN)])
                  
        style.configure("Stop.TButton", background="#444444", foreground=TEXT_LIGHT, font=("Segoe UI", 10, "bold"))
        style.map("Stop.TButton",
                  background=[("active", "#666666")],
                  foreground=[("active", TEXT_LIGHT)])

        # State UI
        self.draft_steps         = []
        self.macro_sequence_queue = []
        self.editing_draft_index  = None

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.manager.start_connection()
        self._poll_telemetry()

    # ------------------------------------------------------------------
    # Konstruksi UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        # Gunakan background label sebagai parent agar layout melayang di atas gambar
        parent = self.bg_label if (self.bg_label is not None) else self.root

        # Sisi Kiri & Sisi Kanan langsung di-pack ke parent
        self._build_left_panel(parent)
        self._build_right_panel(parent)

        # (Status bar dipindahkan ke panel kiri)

    # ---- Panel Kiri --------------------------------------------------

    def _build_left_panel(self, parent):
        self.left_panel = ttk.Frame(parent)
        self.left_panel.pack(side="left", fill="both", padx=15, pady=15)

        self._build_creator_frame(self.left_panel)
        self._build_notes_frame(self.left_panel)
        self._build_stand_indicator_frame(self.left_panel)
        
        self.lbl_status = ttk.Label(
            self.left_panel, text="Status: Menghubungkan ke Pygame...",
            anchor="w", foreground="#aaaaaa"
        )
        self.lbl_status.pack(side="bottom", fill="x", pady=(5,0))

    def _build_creator_frame(self, parent):
        """Frame pembuat kombinasi kustom."""
        frame = ttk.LabelFrame(parent, text=" 🛠️ Buat Kombinasi Kustom ")
        frame.pack(side="top", fill="both", expand=True, padx=10, pady=10, ipady=5)
        ttk.Label(frame, text="Nama Kombinasi:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.entry_combo_name = ttk.Entry(frame, width=20)
        self.entry_combo_name.insert(0, "Kombinasi_Kustom")
        self.entry_combo_name.grid(row=0, column=1, sticky="w", padx=5, pady=5)

        # Sub-frame for compact inputs
        inputs_frame = ttk.Frame(frame)
        inputs_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=5, pady=5)

        # Row 0: Nama Gerakan
        ttk.Label(inputs_frame, text="Nama:").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        self.entry_step_name = ttk.Combobox(
            inputs_frame, values=[
                "local odometry",
                "global odometry",
                "pwm",
                "rotasi",
                "delay",
                "find coordinate",
                "reset coordinate",
                "balance depan",
                "balance kiri",
                "balance depan kiri",
                "ambil kubus",
                "taruh kubus",
                "scan stand",
                "scan almari",
                "scan target",
                "apakah diambil?",
                "apakah ditaruh?",
                "apakah full?"
            ],
            width=18
        )
        self.entry_step_name.set("delay")
        self.entry_step_name.grid(row=0, column=1, columnspan=5, sticky="ew", padx=2, pady=2)

        # Row 1: Vx, Vy, Vw side-by-side
        ttk.Label(inputs_frame, text="Vx:").grid(row=1, column=0, sticky="w", padx=2, pady=2)
        self.spin_vx = ttk.Spinbox(inputs_frame, from_=-20, to=20, width=5)
        self.spin_vx.set(10)
        self.spin_vx.grid(row=1, column=1, sticky="w", padx=2, pady=2)

        ttk.Label(inputs_frame, text="Vy:").grid(row=1, column=2, sticky="w", padx=2, pady=2)
        self.spin_vy = ttk.Spinbox(inputs_frame, from_=-20, to=20, width=5)
        self.spin_vy.set(0)
        self.spin_vy.grid(row=1, column=3, sticky="w", padx=2, pady=2)

        ttk.Label(inputs_frame, text="Vw:").grid(row=1, column=4, sticky="w", padx=2, pady=2)
        self.spin_vw = ttk.Spinbox(inputs_frame, from_=-15, to=15, width=5)
        self.spin_vw.grid(row=1, column=5, sticky="w", padx=2, pady=2)

        # Row 2: Limit Type, Limit Val
        ttk.Label(inputs_frame, text="Limit:").grid(row=2, column=0, sticky="w", padx=2, pady=2)
        self.combo_limit_type = ttk.Combobox(
            inputs_frame, values=["Waktu (s)", "Jarak (px)", "Sudut (°)", "Sensor Garis", "Sensor Jarak Depan (mm)", "Sensor Jarak Kiri (mm)"],
            state="readonly", width=19
        )
        self.combo_limit_type.current(0)
        self.combo_limit_type.grid(row=2, column=1, columnspan=2, sticky="ew", padx=2, pady=2)

        ttk.Label(inputs_frame, text="Nilai:").grid(row=2, column=3, sticky="w", padx=2, pady=2)
        self.entry_limit_val = ttk.Entry(inputs_frame, width=6)
        self.entry_limit_val.insert(0, "2.0")
        self.entry_limit_val.grid(row=2, column=4, columnspan=2, sticky="ew", padx=2, pady=2)

        # Row 3: Keterangan
        ttk.Label(inputs_frame, text="Ket:").grid(row=3, column=0, sticky="w", padx=2, pady=2)
        self.entry_step_desc = ttk.Entry(inputs_frame, width=15)
        self.entry_step_desc.grid(row=3, column=1, columnspan=5, sticky="ew", padx=2, pady=2)

        btn_add_frame = ttk.Frame(frame)
        btn_add_frame.grid(row=2, column=0, columnspan=2, pady=5, padx=5, sticky="ew")

        self.btn_add_step = ttk.Button(
            btn_add_frame, text="➕ Tambah Langkah", command=self._add_step_to_draft
        )
        self.btn_add_step.pack(side="left", fill="x", expand=True, padx=2)

        self.btn_cancel_edit = ttk.Button(
            btn_add_frame, text="❌ Batal Edit", command=self._cancel_edit_step, state="disabled"
        )
        self.btn_cancel_edit.pack(side="right", fill="x", expand=True, padx=2)

        ttk.Label(frame, text="Draft Gerakan Saat Ini:").grid(
            row=3, column=0, columnspan=2, sticky="w", padx=5)

        self.tree_draft = ttk.Treeview(
            frame, columns=("nama", "vx_vy", "limit", "keterangan"),
            show="headings", height=3
        )
        self.tree_draft.heading("nama",       text="Nama")
        self.tree_draft.heading("vx_vy",      text="Vx/Vy/Vw")
        self.tree_draft.heading("limit",      text="Limit")
        self.tree_draft.heading("keterangan", text="Keterangan")
        self.tree_draft.column("nama",       width=70)
        self.tree_draft.column("vx_vy",      width=70, anchor="center")
        self.tree_draft.column("limit",      width=70, anchor="center")
        self.tree_draft.column("keterangan", width=90, anchor="w")
        self.tree_draft.grid(row=4, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")
        self.tree_draft.bind("<Double-1>", self._on_draft_double_click)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=5, column=0, columnspan=2, pady=5, sticky="ew")

        ttk.Button(btn_row, text="✏️ Edit",
                   command=self._load_step_for_editing).pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(btn_row, text="📋 Copy",
                   command=self._copy_draft_step).pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(btn_row, text="📥 Insert",
                   command=self._insert_step_to_draft).pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(btn_row, text="➖ Hapus",
                   command=self._delete_draft_step).pack(side="left",  fill="x", expand=True, padx=2)
        ttk.Button(btn_row, text="🗑️ Clear",
                   command=self._clear_draft).pack(side="right", fill="x", expand=True, padx=2)

        ttk.Button(frame, text="💾 Simpan Preset Kombinasi",
                   command=self._save_draft).grid(
            row=6, column=0, columnspan=2, pady=5, padx=5, sticky="ew")

    def _build_notes_frame(self, parent):
        """Frame catatan/memo pengguna yang tersimpan otomatis."""
        frame = ttk.LabelFrame(parent, text=" 📝 Catatan / Notes (Auto-Save) ")
        frame.pack(side="top", fill="both", expand=True, padx=10, pady=10)

        # Gunakan Text widget dengan background gelap agar matching dengan tema dashboard
        self.txt_notes = tk.Text(frame, height=3, font=("Consolas", 10),
                                  bg="#221f2d", fg="#ffffff", insertbackground="white",
                                  relief="flat", padx=8, pady=8)
        self.txt_notes.pack(fill="both", expand=True, padx=5, pady=5)

        # Load notes dari file jika ada
        try:
            import os
            if os.path.exists("notes.txt"):
                with open("notes.txt", "r", encoding="utf-8") as f:
                    content = f.read()
                self.txt_notes.insert("1.0", content)
        except Exception:
            pass

        # Simpan setiap kali ada perubahan ketikan key-release
        self.txt_notes.bind("<KeyRelease>", self._save_notes)

    def _save_notes(self, event=None):
        try:
            content = self.txt_notes.get("1.0", tk.END)
            # Selalu tulis ke notes.txt
            with open("notes.txt", "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass

    # ---- Panel Kanan -------------------------------------------------

    def _build_right_panel(self, parent):
        self.right_panel = ttk.Frame(parent)
        self.right_panel.pack(side="right", fill="both", expand=True, padx=15, pady=15)

        self._build_selector_frame(self.right_panel)
        self._build_telemetry_frame(self.right_panel)
        self._build_status_frame(self.right_panel)
        self._build_queue_panels(self.right_panel)
    def _build_stand_indicator_frame(self, parent):
        self.stand_labels = {}
        self.target_labels = {}
        
        # --- Frame P (Ruangan) ---
        frame_p = ttk.LabelFrame(parent, text=" 📍 Stand Memory (Ruangan P) ")
        frame_p.pack(fill="x", padx=10, pady=5)
        
        groups_p = ["P1", "P2", "P3"]
        
        ttk.Label(frame_p, text="", width=4).grid(row=0, column=0, padx=2, pady=2)
        for c, s in enumerate(["S1", "S2", "S3"]):
            ttk.Label(frame_p, text=s, font=("Segoe UI", 8, "bold")).grid(row=0, column=c+1, padx=2, pady=2, sticky="ew")
            
        for r, g in enumerate(groups_p):
            ttk.Label(frame_p, text=g, font=("Segoe UI", 8, "bold")).grid(row=r+1, column=0, padx=2, pady=2, sticky="e")
            for c, s in enumerate(["S1", "S2", "S3"]):
                label_key = f"{g} {s}"
                lbl = ttk.Label(frame_p, text=" EMPTY ", background="#444444", foreground="#ffffff", font=("Segoe UI", 7, "bold"), anchor="center")
                lbl.bind("<Button-1>", lambda event, k=label_key: self._on_stand_click(k))
                lbl.grid(row=r+1, column=c+1, padx=2, pady=2, sticky="nsew")
                self.stand_labels[label_key] = lbl
                
        for c in range(1, 4):
            frame_p.columnconfigure(c, weight=1)

        # --- Frame A (Gudang Memory) ---
        frame_a = ttk.LabelFrame(parent, text=" 📦 Stand Memory (Gudang A) ")
        frame_a.pack(fill="x", padx=10, pady=5)
        
        groups_a = ["A1", "A2"]
        
        ttk.Label(frame_a, text="", width=4).grid(row=0, column=0, padx=2, pady=2)
        for c, s in enumerate(["S1", "S2", "S3"]):
            ttk.Label(frame_a, text=s, font=("Segoe UI", 8, "bold")).grid(row=0, column=c+1, padx=2, pady=2, sticky="ew")
            
        for r, g in enumerate(groups_a):
            ttk.Label(frame_a, text=g, font=("Segoe UI", 8, "bold")).grid(row=r+1, column=0, padx=2, pady=2, sticky="e")
            for c, s in enumerate(["S1", "S2", "S3"]):
                label_key = f"{g} {s}"
                lbl = ttk.Label(frame_a, text=" EMPTY ", background="#444444", foreground="#ffffff", font=("Segoe UI", 7, "bold"), anchor="center")
                lbl.bind("<Button-1>", lambda event, k=label_key: self._on_stand_click(k))
                lbl.grid(row=r+1, column=c+1, padx=2, pady=2, sticky="nsew")
                self.stand_labels[label_key] = lbl
                
        for c in range(1, 4):
            frame_a.columnconfigure(c, weight=1)

        # --- Frame Target Almari (Gudang A Target) ---
        frame_target = ttk.LabelFrame(parent, text=" 🎯 Target Almari (Gudang A) ")
        frame_target.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(frame_target, text="", width=4).grid(row=0, column=0, padx=2, pady=2)
        for c, s in enumerate(["S1", "S2", "S3"]):
            ttk.Label(frame_target, text=s, font=("Segoe UI", 8, "bold")).grid(row=0, column=c+1, padx=2, pady=2, sticky="ew")
            
        for r, g in enumerate(groups_a):
            ttk.Label(frame_target, text=g, font=("Segoe UI", 8, "bold")).grid(row=r+1, column=0, padx=2, pady=2, sticky="e")
            for c, s in enumerate(["S1", "S2", "S3"]):
                label_key = f"{g} {s}"
                lbl = ttk.Label(frame_target, text=" EMPTY ", background="#444444", foreground="#ffffff", font=("Segoe UI", 7, "bold"), anchor="center")
                lbl.bind("<Button-1>", lambda event, k=label_key: self._on_target_click(k))
                lbl.grid(row=r+1, column=c+1, padx=2, pady=2, sticky="nsew")
                self.target_labels[label_key] = lbl
                
        for c in range(1, 4):
            frame_target.columnconfigure(c, weight=1)

    def _on_stand_click(self, label_key):
        colors = ["EMPTY", "RED", "GREEN", "BLUE"]
        current = self.manager.stand_memory.get(label_key, "EMPTY")
        idx = colors.index(current) if current in colors else 0
        next_color = colors[(idx + 1) % len(colors)]
        self.manager.stand_memory[label_key] = next_color
        
        lbl = self.stand_labels[label_key]
        if next_color == "RED":
            lbl.config(background="#ff3333", text=" RED ")
        elif next_color == "GREEN":
            lbl.config(background="#33cc33", text=" GRN ")
        elif next_color == "BLUE":
            lbl.config(background="#3388ff", text=" BLU ")
        else:
            lbl.config(background="#444444", text=" EMPTY ")

    def _on_target_click(self, label_key):
        colors = ["EMPTY", "RED", "GREEN", "BLUE"]
        current = self.manager.target_memory.get(label_key, "EMPTY")
        idx = colors.index(current) if current in colors else 0
        next_color = colors[(idx + 1) % len(colors)]
        self.manager.target_memory[label_key] = next_color
        
        lbl = self.target_labels[label_key]
        if next_color == "RED":
            lbl.config(background="#ff3333", text=" RED ")
        elif next_color == "GREEN":
            lbl.config(background="#33cc33", text=" GRN ")
        elif next_color == "BLUE":
            lbl.config(background="#3388ff", text=" BLU ")
        else:
            lbl.config(background="#444444", text=" EMPTY ")
                
        # Make columns expandable
        for c in range(1, 4):
            frame.columnconfigure(c, weight=1)

    def _build_status_frame(self, parent):
        frame = ttk.LabelFrame(parent, text=" 🏃 Monitor Eksekusi Sekuens (3-Level Hierarchy) ")
        frame.pack(fill="x", padx=10, pady=5)
        
        row = ttk.Frame(frame)
        row.pack(fill="x", padx=5, pady=4)

        # 1. Status Execution Badge
        self.lbl_mon_status = ttk.Label(row, text="💤 SYSTEM IDLE", font=("Segoe UI", 10, "bold"), background="#333333", foreground="#ffffff", padding=(8, 4))
        self.lbl_mon_status.pack(side="left", padx=5)

        # 2. Indikator Urutan Kombinasi Badge (Level 1)
        self.lbl_mon_urutan = ttk.Label(row, text="🚀 Urutan: -", font=("Segoe UI", 10, "bold"), background="#4a2c7a", foreground="#ffffff", padding=(8, 4))
        self.lbl_mon_urutan.pack(side="left", padx=5)

        # 3. Indikator Kombinasi & Gerakan (Level 2 & 3)
        self.lbl_mon_step = ttk.Label(row, text="Gerakan: -", font=("Segoe UI", 10, "bold"), foreground="#ffffff")
        self.lbl_mon_step.pack(side="left", expand=True, fill="x", padx=10)
        
        # 4. Indikator Limit & Progres
        self.lbl_mon_limit = ttk.Label(row, text="Progress: -", font=("Segoe UI", 10, "bold"), foreground="#ffffff")
        self.lbl_mon_limit.pack(side="right", padx=5)
    def _build_selector_frame(self, parent):
        frame = ttk.LabelFrame(parent, text=" 🗂️ Manajemen Hierarki: Urutan Kombinasi -> Kombinasi -> Gerakan ")
        frame.pack(fill="x", padx=5, pady=5)

        # --- Row 1: Level 1 - Urutan Kombinasi ---
        row1 = ttk.Frame(frame)
        row1.pack(fill="x", padx=5, pady=2)
        ttk.Label(row1, text="Urutan Kombinasi:", font=("Segoe UI", 9, "bold")).pack(side="left", padx=5, pady=2)
        
        self.var_urutan = tk.StringVar()
        self.dropdown_urutan = ttk.Combobox(
            row1, textvariable=self.var_urutan,
            values=list(self.manager.urutan_kombinasi.keys()) if hasattr(self.manager, 'urutan_kombinasi') else [],
            state="readonly", width=22
        )
        self.dropdown_urutan.pack(side="left", padx=5, pady=2)
        self.dropdown_urutan.bind("<<ComboboxSelected>>", self._on_urutan_selected)
        
        ttk.Button(row1, text="➕ Urutan Baru",   command=self._new_urutan).pack(side="left", padx=3)
        ttk.Button(row1, text="💾 Simpan Urutan", command=self._save_current_urutan).pack(side="left", padx=3)
        ttk.Button(row1, text="🗑️ Hapus Urutan",  command=self._delete_urutan).pack(side="left", padx=3)

        # --- Row 2: Level 2 - Kombinasi Gerakan ---
        row2 = ttk.Frame(frame)
        row2.pack(fill="x", padx=5, pady=2)
        ttk.Label(row2, text="Pilih Kombinasi:", font=("Segoe UI", 9, "bold")).pack(side="left", padx=5, pady=2)
        
        self.var_combo = tk.StringVar()
        self.dropdown_kombinasi = ttk.Combobox(
            row2, textvariable=self.var_combo,
            values=list(self.manager.kombinasi_gerakan.keys()),
            state="readonly", width=22
        )
        self.dropdown_kombinasi.pack(side="left", padx=5, pady=2)
        
        ttk.Button(row2, text="➕ Tambah ke Urutan", command=self._add_to_queue).pack(side="left", padx=3)
        ttk.Button(row2, text="✏️ Edit Kombinasi",   command=self._load_preset_to_draft).pack(side="left", padx=3)
        ttk.Button(row2, text="🗑️ Hapus Kombinasi",  command=self._delete_preset).pack(side="left", padx=3)
        ttk.Button(row2, text="🔄 Reload JSON",       command=self._reload_presets).pack(side="left", padx=3)

        if hasattr(self.manager, 'urutan_kombinasi') and self.manager.urutan_kombinasi:
            self.dropdown_urutan.current(0)
            if hasattr(self, 'tree_kiri'):
                self._on_urutan_selected(None)
        if self.manager.kombinasi_gerakan:
            self.dropdown_kombinasi.current(0)

    def _build_telemetry_frame(self, parent):
        frame = ttk.LabelFrame(parent, text=" 📡 Live Telemetry & Odometry Dashboard ")
        frame.pack(fill="x", padx=5, pady=5)

        row1 = ttk.Frame(frame)
        row1.pack(fill="x")
        
        def _card(parent_frame, label_text, value_text, fg):
            card = ttk.Frame(parent_frame, relief="groove", padding=10)
            card.pack(side="left", expand=True, fill="both", padx=5, pady=5)
            ttk.Label(card, text=label_text, font=("Segoe UI", 9, "bold"), foreground="#a29bb5").pack()
            lbl = ttk.Label(card, text=value_text, font=("Segoe UI", 16, "bold"), foreground=fg)
            lbl.pack(pady=2)
            return lbl

        self.lbl_tele_x = _card(row1, "KOORDINAT X",        "0.0 cm",  "#ffffff")
        self.lbl_tele_y = _card(row1, "KOORDINAT Y",        "0.0 cm",  "#ffffff")
        self.lbl_tele_w = _card(row1, "ARAH HADAP (HEADING)", "0°",    "#ffffff")
        self.lbl_tele_d = _card(row1, "JARAK TEMPUH",       "0.00 m",  "#ffffff")

        row2 = ttk.Frame(frame)
        row2.pack(fill="x")
        
        self.lbl_tele_dx = _card(row2, "TEMP. X (STEP)", "0.0 mm", "#aaffaa")
        self.lbl_tele_dy = _card(row2, "TEMP. Y (STEP)", "0.0 mm", "#aaffaa")
        self.lbl_tele_dw = _card(row2, "TEMP. W (STEP)", "0.0°",     "#aaffaa")

        row3 = ttk.Frame(frame)
        row3.pack(fill="x")

        # Card: Camera
        card_camera = ttk.Frame(row3, relief="groove", padding=10)
        card_camera.pack(side="left", expand=True, fill="both", padx=5, pady=5)
        ttk.Label(card_camera, text="VISION CAMERA", font=("Segoe UI", 9, "bold"), foreground="#a29bb5").pack()
        
        self.btn_camera = ttk.Button(card_camera, text="📷 Buka Kamera", command=self._toggle_camera)
        self.btn_camera.pack(pady=10)
        self.camera_window = None

        # Card 5: Line Sensors
        card_sensor = ttk.Frame(row3, relief="groove", padding=10)
        card_sensor.pack(side="left", expand=True, fill="both", padx=5, pady=5)
        ttk.Label(card_sensor, text="SENSOR GARIS", font=("Segoe UI", 9, "bold"), foreground="#a29bb5").pack()
        
        sensor_box = ttk.Frame(card_sensor)
        sensor_box.pack(pady=4)
        
        self.lbl_sensor_l = ttk.Label(sensor_box, text="⬤ L", font=("Segoe UI", 12, "bold"), foreground="#888888")
        self.lbl_sensor_l.pack(side="left", padx=10)
        
        self.lbl_sensor_r = ttk.Label(sensor_box, text="⬤ R", font=("Segoe UI", 12, "bold"), foreground="#888888")
        self.lbl_sensor_r.pack(side="left", padx=10)

        # Card 6: Storage Kubus (counter + 8 slot warna)
        card_storage = ttk.Frame(row3, relief="groove", padding=10)
        card_storage.pack(side="left", expand=True, fill="both", padx=5, pady=5)
        ttk.Label(card_storage, text="STORAGE KUBUS", font=("Segoe UI", 9, "bold"), foreground="#a29bb5").pack()
        
        self.lbl_storage_count = ttk.Label(card_storage, text="0 / 8", font=("Segoe UI", 14, "bold"), foreground="#ffffff")
        self.lbl_storage_count.pack(pady=1)
        
        slots_box = ttk.Frame(card_storage)
        slots_box.pack(pady=2)
        
        btn_reset_st = ttk.Button(card_storage, text="🗑 Reset Storage", command=self._reset_storage)
        btn_reset_st.pack(pady=3)
        
        self.lbl_storage_slots = []
        for i in range(8):
            char_num = chr(0x2776 + i)
            slot_lbl = ttk.Label(slots_box, text=char_num, font=("Segoe UI", 12, "bold"), foreground="#333333", cursor="hand2")
            slot_lbl.pack(side="left", padx=1)
            slot_lbl.bind("<Button-1>", lambda e, idx=i: self._on_storage_slot_click(idx))
            self.lbl_storage_slots.append(slot_lbl)

    def _toggle_camera(self):
        if self.camera_window is None or not self.camera_window.winfo_exists():
            self.camera_window = CameraWindow(self.root, self._on_camera_close)
            self.btn_camera.config(text="📷 Tutup Kamera")
        else:
            self.camera_window._on_close()

    def open_camera(self):
        if self.camera_window is None or not self.camera_window.winfo_exists():
            self._toggle_camera()
            
    def close_camera(self):
        if self.camera_window is not None and self.camera_window.winfo_exists():
            self._toggle_camera()

    def _on_camera_close(self):
        self.camera_window = None
        self.btn_camera.config(text="📷 Buka Kamera")

    def _toggle_storage_slot(self, slot_idx):
        current_colors = list(self.manager.storage_colors)
        while len(current_colors) < 8:
            current_colors.append("-")
        
        cycle = ["-", "R", "G", "B"]
        current = current_colors[slot_idx]
        if current not in cycle:
            current = "-"
        
        next_idx = (cycle.index(current) + 1) % len(cycle)
        current_colors[slot_idx] = cycle[next_idx]
        
        self.manager.storage_colors = current_colors
        self.manager.storage_count = sum(1 for c in current_colors if c != "-")
        self.manager.set_storage_manual(current_colors)

    def _reset_storage(self):
        empty_colors = ["-"] * 8
        self.manager.storage_colors = empty_colors
        self.manager.storage_count = 0
        self.manager.send_command("RESET_STORAGE")

    def _build_queue_panels(self, parent):
        paned = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        paned.pack(fill="both", expand=True, padx=5, pady=5)

        # --- 1. Paling Kiri: Level 1 - Daftar Urutan Kombinasi ---
        frame_urutan = ttk.LabelFrame(paned, text=" 📋 Daftar Urutan Kombinasi (Level 1) ")
        paned.add(frame_urutan, weight=1)

        urutan_btn_frame = ttk.Frame(frame_urutan)
        urutan_btn_frame.pack(side="bottom", fill="x", padx=5, pady=5)
        ttk.Button(urutan_btn_frame, text="➕ Baru", command=self._new_urutan).pack(side="left", padx=2, expand=True, fill="x")
        ttk.Button(urutan_btn_frame, text="📌 Insert", command=self._insert_urutan).pack(side="left", padx=2, expand=True, fill="x")
        ttk.Button(urutan_btn_frame, text="📋 Copy", command=self._copy_urutan).pack(side="left", padx=2, expand=True, fill="x")
        ttk.Button(urutan_btn_frame, text="🗑 Hapus", command=self._delete_urutan).pack(side="right", padx=2, expand=True, fill="x")

        self.tree_urutan = ttk.Treeview(
            frame_urutan, columns=("no", "urutan"), show="headings"
        )
        self.tree_urutan.heading("no",     text="No")
        self.tree_urutan.heading("urutan", text="Nama Urutan Kombinasi")
        self.tree_urutan.column("no",     width=35, anchor="center")
        self.tree_urutan.column("urutan", width=140, anchor="w")
        self.tree_urutan.pack(fill="both", expand=True, padx=5, pady=5)
        self.tree_urutan.bind("<<TreeviewSelect>>", self._on_urutan_tree_select)

        # --- 2. Tengah: Level 2 - Urutan Antrean Kombinasi ---
        frame_kiri = ttk.LabelFrame(paned, text=" 📦 Urutan Antrean Kombinasi (Level 2) ")
        paned.add(frame_kiri, weight=1)

        kiri_btn_frame = ttk.Frame(frame_kiri)
        kiri_btn_frame.pack(side="bottom", fill="x", padx=5, pady=5)
        ttk.Button(kiri_btn_frame, text="📌 Insert", command=self._insert_to_queue).pack(side="left", padx=2, expand=True, fill="x")
        ttk.Button(kiri_btn_frame, text="📋 Copy", command=self._copy_kombinasi_queue).pack(side="left", padx=2, expand=True, fill="x")
        ttk.Button(kiri_btn_frame, text="➖ Hapus", command=self._delete_selected_macro).pack(side="left", padx=2, expand=True, fill="x")
        ttk.Button(kiri_btn_frame, text="🗑 Clear", command=self._clear_sequence).pack(side="right", padx=2, expand=True, fill="x")

        self.tree_kiri = ttk.Treeview(
            frame_kiri, columns=("no", "kombinasi"), show="headings"
        )
        self.tree_kiri.heading("no",         text="No")
        self.tree_kiri.heading("kombinasi",  text="Nama Variabel Kombinasi")
        self.tree_kiri.column("no",          width=35,  anchor="center")
        self.tree_kiri.column("kombinasi",   width=140, anchor="w")
        self.tree_kiri.pack(fill="both", expand=True, padx=5, pady=5)
        self.tree_kiri.bind("<<TreeviewSelect>>", self._on_kiri_select)

        # --- 3. Paling Kanan: Level 3 - Detail Isi Gerakan ---
        frame_kanan = ttk.LabelFrame(paned, text=" ⚙️ Detail Isi Gerakan (Level 3) ")
        paned.add(frame_kanan, weight=2)

        kanan_btn_frame = ttk.Frame(frame_kanan)
        kanan_btn_frame.pack(side="bottom", fill="x", padx=5, pady=5)

        ttk.Button(kanan_btn_frame, text="🔄 Reset Robot", command=self.manager.reset_robot_position).pack(side="left", padx=2)
        ttk.Button(kanan_btn_frame, text="🛑 Stop Sekuens", command=self.manager.stop_execution).pack(side="left", padx=2)
        
        self.btn_run_from = ttk.Button(kanan_btn_frame, text="⏭️ Mulai dari Pilihan", command=self._start_execution_from)
        self.btn_run_from.pack(side="right", padx=2)
        
        self.btn_run = ttk.Button(kanan_btn_frame, text="▶ Jalankan Semua Sekuens", command=self._start_execution)
        self.btn_run.pack(side="right", padx=2)

        cols = ("step", "nama", "vx", "vy", "vw", "limit_type", "limit_val", "keterangan")
        self.tree_kanan = ttk.Treeview(frame_kanan, columns=cols, show="headings")
        for col, txt, w in [
            ("step",       "Step",        40),
            ("nama",       "Nama Gerakan",100),
            ("vx",         "Vx",          50),
            ("vy",         "Vy",          50),
            ("vw",         "Vw",          50),
            ("limit_type", "Tipe Limit",  90),
            ("limit_val",  "Nilai Limit", 70),
            ("keterangan", "Keterangan",  110),
        ]:
            self.tree_kanan.heading(col, text=txt)
            self.tree_kanan.column(col, width=w,
                                   anchor="center" if col != "nama" else "w")
        self.tree_kanan.pack(fill="both", expand=True, padx=5, pady=5)

        self._refresh_tree_urutan()


    # ------------------------------------------------------------------
    # Polling Telemetri (dipanggil via after())
    # ------------------------------------------------------------------
    def _poll_telemetry(self):
        if self.manager.pygame_socket:
            pos  = self.manager.robot_pos
            x_cm = pos["x"] / 10.0
            y_cm = pos["y"] / 10.0
            deg  = math.degrees(-pos["angle"]) % 360.0
            dist = pos.get("dist", 0.0) / 1000.0

            self.lbl_tele_x.config(text=f"{x_cm:+.1f} cm")
            self.lbl_tele_y.config(text=f"{y_cm:+.1f} cm")
            self.lbl_tele_w.config(text=f"{deg:.0f}°")
            self.lbl_tele_d.config(text=f"{dist:.2f} m")

            # Use local accumulated distance for the current step
            step_info = self.manager.active_step_info
            
            dx_mm = step_info.get("temp_x", 0.0)
            dy_mm = step_info.get("temp_y", 0.0)
            dw_deg = step_info.get("temp_w", 0.0)

            self.lbl_tele_dx.config(text=f"{dx_mm:+.1f} mm")
            self.lbl_tele_dy.config(text=f"{dy_mm:+.1f} mm")
            self.lbl_tele_dw.config(text=f"{dw_deg:+.1f}°")

            self.lbl_status.config(text="Status: Terhubung ke Pygame | Telemetri terupdate.")

            # Update line sensor indicators
            sensors = self.manager.line_sensors
            self.lbl_sensor_l.config(foreground="#00ff00" if sensors.get("left", 0) else "#555555")
            self.lbl_sensor_r.config(foreground="#00ff00" if sensors.get("right", 0) else "#555555")

            # Update storage counter dan slot indicators
            s_count = self.manager.storage_count
            s_colors = self.manager.storage_colors
            self.lbl_storage_count.config(text=f"{s_count} / 8")
            color_map = {"R": "#ff3333", "G": "#33cc33", "B": "#3388ff"}
            for i, slot_lbl in enumerate(self.lbl_storage_slots):
                if i < len(s_colors) and s_colors[i] in color_map:
                    slot_lbl.config(foreground=color_map[s_colors[i]])
                else:
                    slot_lbl.config(foreground="#333333")
                    
            # Update Stand Memory Indicator
            if hasattr(self, 'stand_labels'):
                for label_key, lbl in self.stand_labels.items():
                    color = self.manager.stand_memory.get(label_key, "EMPTY")
                    if color == "RED":
                        lbl.config(background="#ff3333", text=" RED ")
                    elif color == "GREEN":
                        lbl.config(background="#33cc33", text=" GRN ")
                    elif color == "BLUE":
                        lbl.config(background="#3388ff", text=" BLU ")
                    else:
                        lbl.config(background="#444444", text=" EMPTY ")

            # Update Target Memory Indicator
            if hasattr(self, 'target_labels'):
                for label_key, lbl in self.target_labels.items():
                    color = self.manager.target_memory.get(label_key, "EMPTY")
                    if color == "RED":
                        lbl.config(background="#ff3333", text=" RED ")
                    elif color == "GREEN":
                        lbl.config(background="#33cc33", text=" GRN ")
                    elif color == "BLUE":
                        lbl.config(background="#3388ff", text=" BLU ")
                    else:
                        lbl.config(background="#444444", text=" EMPTY ")
        else:
            for lbl in (self.lbl_tele_x, self.lbl_tele_y,
                        self.lbl_tele_w, self.lbl_tele_d,
                        self.lbl_tele_dx, self.lbl_tele_dy, self.lbl_tele_dw):
                lbl.config(text="---")
            self.lbl_sensor_l.config(foreground="#555555")
            self.lbl_sensor_r.config(foreground="#555555")
            self.lbl_storage_count.config(text="- / 8")
            for slot_lbl in self.lbl_storage_slots:
                slot_lbl.config(foreground="#333333")
            self.lbl_status.config(
                text="Status: Terputus dari Pygame. Jalankan simul_jalan.py...")

        # Update monitor status running sekuens
        mon = self.manager.active_step_info
        status = mon.get("status", "IDLE")
        kombinasi = mon.get("kombinasi", "-")
        nama = mon.get("nama", "-")
        ltype = mon.get("limit_type", "-")
        lval = mon.get("limit_val", 0.0)
        cval = mon.get("current_val", 0.0)
        q_idx = mon.get("q_idx", 0)
        q_tot = mon.get("q_total", 0)
        s_idx = mon.get("step_idx", 0)
        s_tot = mon.get("step_total", 0)
        
        urutan_name = mon.get("urutan_name", self.var_urutan.get() if hasattr(self, 'var_urutan') else "-")
        if not urutan_name or urutan_name == "-":
            urutan_name = self.var_urutan.get() if hasattr(self, 'var_urutan') else "-"

        if hasattr(self, 'lbl_mon_urutan'):
            self.lbl_mon_urutan.config(text=f"🚀 Urutan: {urutan_name}")

        if status == "RUNNING":
            self.lbl_mon_status.config(text="🏃 EXECUTING", background="#28a745", foreground="#ffffff")
            self.lbl_mon_step.config(
                text=f"Kombinasi ({q_idx}/{q_tot}): {kombinasi} ➔ Gerakan ({s_idx}/{s_tot}): {nama}"
            )
            
            # Format teks progres berdasarkan tipe limit
            if "Waktu" in ltype:
                self.lbl_mon_limit.config(text=f"Limit: {cval:.1f}s / {lval:.1f}s")
            elif "Jarak" in ltype:
                self.lbl_mon_limit.config(text=f"Limit: {int(cval)} / {int(lval)} px")
            elif "Sudut" in ltype:
                self.lbl_mon_limit.config(text=f"Limit: {cval:.1f}° / {lval:.1f}°")
            elif "Navigasi" in ltype:
                self.lbl_mon_limit.config(text=f"Nav: {int(cval)} mm ke target")
            elif "Sensor" in ltype or "Garis" in ltype:
                state_str = "AKTIF" if cval > 0.5 else "Mencari..."
                self.lbl_mon_limit.config(text=f"Garis: {state_str}")
            elif "Ambil" in ltype or "Kubus" in ltype and "Taruh" not in ltype:
                state_str = "Selesai ✓" if cval >= 1.0 else "Mengambil..."
                self.lbl_mon_limit.config(text=f"Grab: {state_str} ({self.manager.storage_count}/8)")
            elif "Taruh" in ltype or "Drop" in ltype:
                state_str = "Selesai ✓" if cval >= 1.0 else "Menaruh..."
                self.lbl_mon_limit.config(text=f"Drop: {state_str} ({self.manager.storage_count}/8)")
            else:
                self.lbl_mon_limit.config(text=f"Progress: {cval:.1f} / {lval:.1f}")
        else:
            self.lbl_mon_status.config(text="💤 SYSTEM IDLE", background="#333333", foreground="#ffffff")
            self.lbl_mon_step.config(text="Gerakan: -")
            self.lbl_mon_limit.config(text="Progress: -")
        self.root.after(100, self._poll_telemetry)
    # ------------------------------------------------------------------
    # Antarmuka Balik untuk SequenceManager (dipanggil dari thread lain)
    # ------------------------------------------------------------------

    def set_run_button_state(self, state):
        def _update():
            self.btn_run.config(state=state)
            self.btn_run_from.config(state=state)
        self.root.after(0, _update)

    def highlight_row(self, index):
        self.root.after(0, self._highlight_kiri_row, index)

    def update_detail_view(self, nama_kombinasi):
        self.root.after(0, self._update_tree_kanan, nama_kombinasi)

    def show_error(self, msg):
        self.root.after(0, lambda: messagebox.showerror("Error", msg))

    def set_status_text(self, text):
        self.root.after(0, lambda: self.lbl_status.config(text=text))

    # ------------------------------------------------------------------
    # Event Handlers: Draft
    # ------------------------------------------------------------------

    def _add_step_to_draft(self):
        try:
            nama  = self.entry_step_name.get()
            vx    = float(self.spin_vx.get())
            vy    = float(self.spin_vy.get())
            vw_s  = self.spin_vw.get().strip()
            vw    = float(vw_s) if vw_s else None
            ltype = self.combo_limit_type.get()
            lval  = float(self.entry_limit_val.get())
            desc  = self.entry_step_desc.get().strip()
        except ValueError:
            messagebox.showerror("Error", "Vx, Vy, Vw (jika diisi), dan Nilai Limit harus angka!")
            return

        step_data = {
            "nama": nama, "vx": vx, "vy": vy, "vw": vw, 
            "limit_type": ltype, "limit_val": lval, "keterangan": desc
        }

        if self.editing_draft_index is not None:
            # Update langkah yang sedang diedit
            idx = self.editing_draft_index
            if 0 <= idx < len(self.draft_steps):
                self.draft_steps[idx] = step_data
            self.editing_draft_index = None
            self.btn_add_step.config(text="➕ Tambah Langkah")
            self.btn_cancel_edit.config(state="disabled")
        else:
            # Tambah langkah baru
            self.draft_steps.append(step_data)

        self._refresh_draft_tree()
        self.entry_step_name.set("local odometry")
        self.entry_step_desc.delete(0, tk.END)

    def _insert_step_to_draft(self):
        sel = self.tree_draft.selection()
        if not sel:
            messagebox.showwarning("Peringatan", "Pilih langkah di draft sebagai posisi insert (langkah baru akan disisipkan sebelum pilihan)!")
            return
            
        try:
            nama  = self.entry_step_name.get()
            vx    = float(self.spin_vx.get())
            vy    = float(self.spin_vy.get())
            vw_s  = self.spin_vw.get().strip()
            vw    = float(vw_s) if vw_s else None
            ltype = self.combo_limit_type.get()
            lval  = float(self.entry_limit_val.get())
            desc  = self.entry_step_desc.get().strip()
        except ValueError:
            messagebox.showerror("Error", "Vx, Vy, Vw (jika diisi), dan Nilai Limit harus angka!")
            return

        step_data = {
            "nama": nama, "vx": vx, "vy": vy, "vw": vw, 
            "limit_type": ltype, "limit_val": lval, "keterangan": desc
        }

        idx = self.tree_draft.index(sel[0])
        self.draft_steps.insert(idx, step_data)
        
        if self.editing_draft_index is not None and self.editing_draft_index >= idx:
            self.editing_draft_index += 1

        self._refresh_draft_tree()
        self.entry_step_name.set("local odometry")
        self.entry_step_desc.delete(0, tk.END)

    def _delete_draft_step(self):
        sel = self.tree_draft.selection()
        if not sel:
            messagebox.showwarning("Peringatan", "Pilih langkah di draft terlebih dahulu!")
            return
        idx = self.tree_draft.index(sel[0])
        del self.draft_steps[idx]
        
        # Reset edit jika yang dihapus sedang diedit
        if self.editing_draft_index == idx:
            self._cancel_edit_step()
        elif self.editing_draft_index is not None and self.editing_draft_index > idx:
            self.editing_draft_index -= 1

        self._refresh_draft_tree()
        self.entry_step_name.set("local odometry")

    def _clear_draft(self):
        self.draft_steps.clear()
        self._cancel_edit_step()
        self._refresh_draft_tree()
        self.entry_step_name.set("local odometry")
        self.entry_step_desc.delete(0, tk.END)

    def _refresh_draft_tree(self):
        for item in self.tree_draft.get_children():
            self.tree_draft.delete(item)
        for s in self.draft_steps:
            vw_val = "-" if s.get("vw") is None else str(int(s["vw"]))
            unit   = s["limit_type"].split()[1] if len(s["limit_type"].split()) > 1 else s["limit_type"]
            desc_val = s.get("keterangan", "")
            if not desc_val:
                desc_val = "-"
            self.tree_draft.insert("", "end", values=(
                s["nama"],
                f"{int(s['vx'])}/{int(s['vy'])}/{vw_val}",
                f"{s['limit_val']} {unit}",
                desc_val,
            ))

    def _load_step_for_editing(self):
        sel = self.tree_draft.selection()
        if not sel:
            messagebox.showwarning("Peringatan", "Pilih langkah di draft terlebih dahulu!")
            return
        idx = self.tree_draft.index(sel[0])
        self._load_step_index_for_editing(idx)

    def _load_step_index_for_editing(self, idx):
        if idx < 0 or idx >= len(self.draft_steps):
            return
        step = self.draft_steps[idx]
        self.editing_draft_index = idx

        # Isi field input
        self.entry_step_name.set(step["nama"])
        
        self.spin_vx.set(step["vx"])
        self.spin_vy.set(step["vy"])
        
        self.spin_vw.delete(0, tk.END)
        if step.get("vw") is not None:
            self.spin_vw.insert(0, str(int(step["vw"])))
            
        self.combo_limit_type.set(step["limit_type"])
        self.entry_limit_val.delete(0, tk.END)
        self.entry_limit_val.insert(0, str(step["limit_val"]))
        
        self.entry_step_desc.delete(0, tk.END)
        self.entry_step_desc.insert(0, step.get("keterangan", ""))

        # Atur tombol
        self.btn_add_step.config(text="💾 Update Langkah")
        self.btn_cancel_edit.config(state="normal")

    def _cancel_edit_step(self):
        self.editing_draft_index = None
        self.btn_add_step.config(text="➕ Tambah Langkah")
        self.btn_cancel_edit.config(state="disabled")
        
        # Reset field input
        self.entry_step_name.set("local odometry")
        self.spin_vx.set(10)
        self.spin_vy.set(0)
        self.spin_vw.delete(0, tk.END)
        self.combo_limit_type.current(0)
        self.entry_limit_val.delete(0, tk.END)
        self.entry_limit_val.insert(0, "2.0")
        self.entry_step_desc.delete(0, tk.END)

    def _on_draft_double_click(self, event):
        sel = self.tree_draft.selection()
        if sel:
            idx = self.tree_draft.index(sel[0])
            self._load_step_index_for_editing(idx)

    # ------------------------------------------------------------------
    # Event Handlers: Preset
    # ------------------------------------------------------------------

    def _save_draft(self):
        name = self.entry_combo_name.get().strip()
        if not name:
            messagebox.showwarning("Peringatan", "Nama kombinasi tidak boleh kosong!")
            return
        if not self.draft_steps:
            messagebox.showwarning("Peringatan", "Draft masih kosong!")
            return
        self.manager.kombinasi_gerakan[name] = list(self.draft_steps)
        self.manager.save_presets()
        self.dropdown_kombinasi["values"] = list(self.manager.kombinasi_gerakan.keys())
        self.dropdown_kombinasi.set(name)
        self.draft_steps.clear()
        self._refresh_draft_tree()
        self.entry_step_name.set("local odometry")
        self._update_tree_kanan(name)
        messagebox.showinfo("Sukses", f"Kombinasi '{name}' disimpan ke presets.json!")

    def _load_preset_to_draft(self):
        nama = self.var_combo.get()
        if nama in self.manager.kombinasi_gerakan:
            self.entry_combo_name.delete(0, tk.END)
            self.entry_combo_name.insert(0, nama)
            self.draft_steps = [dict(s) for s in self.manager.kombinasi_gerakan[nama]]
            self._refresh_draft_tree()
            self.entry_step_name.delete(0, tk.END)
            self.entry_step_name.insert(0, f"Langkah {len(self.draft_steps) + 1}")
            self.lbl_status.config(text=f"Status: Preset '{nama}' dimuat ke Draft.")

    def _delete_preset(self):
        nama = self.var_combo.get()
        if not nama:
            return
        if nama in self.manager.default_presets:
            messagebox.showwarning("Peringatan", f"Preset default '{nama}' tidak boleh dihapus!")
            return
        if messagebox.askyesno("Konfirmasi", f"Hapus preset '{nama}' secara permanen?"):
            del self.manager.kombinasi_gerakan[nama]
            self.manager.save_presets()
            self.dropdown_kombinasi["values"] = list(self.manager.kombinasi_gerakan.keys())
            if self.manager.kombinasi_gerakan:
                self.dropdown_kombinasi.current(0)
            else:
                self.dropdown_kombinasi.set("")
            self.lbl_status.config(text=f"Status: Preset '{nama}' dihapus.")

    def _sync_active_urutan(self):
        if hasattr(self, 'var_urutan'):
            selected_urutan = self.var_urutan.get()
            if selected_urutan:
                self.manager.urutan_kombinasi[selected_urutan] = list(self.macro_sequence_queue)
                self.manager.save_presets()
                self._refresh_tree_urutan()

    def _on_urutan_selected(self, event=None):
        selected_urutan = self.var_urutan.get()
        if selected_urutan in self.manager.urutan_kombinasi:
            self.macro_sequence_queue = list(self.manager.urutan_kombinasi[selected_urutan])
            self._refresh_tree_kiri()
            
            # Auto-update Level 3 (tree_kanan) dengan langkah dari kombinasi pertama
            if self.macro_sequence_queue:
                first_combo = self.macro_sequence_queue[0]
                self._update_tree_kanan(first_combo)
                if hasattr(self, 'tree_kiri'):
                    children = self.tree_kiri.get_children()
                    if children:
                        self.tree_kiri.selection_set(children[0])
            else:
                if hasattr(self, 'tree_kanan'):
                    for item in self.tree_kanan.get_children():
                        self.tree_kanan.delete(item)

    def _new_urutan(self):
        from tkinter import simpledialog
        nama = simpledialog.askstring("Urutan Kombinasi Baru", "Masukkan nama Urutan Kombinasi (Level 1):", parent=self.root)
        if nama and nama.strip():
            nama = nama.strip()
            self.manager.urutan_kombinasi[nama] = list(self.macro_sequence_queue)
            self.manager.save_presets()
            self.dropdown_urutan["values"] = list(self.manager.urutan_kombinasi.keys())
            self.var_urutan.set(nama)
            self._on_urutan_selected(None)
            self._refresh_tree_urutan()
            messagebox.showinfo("Sukses", f"Urutan Kombinasi '{nama}' berhasil dibuat!")

    def _insert_urutan(self):
        from tkinter import simpledialog
        sel = self.tree_urutan.selection() if hasattr(self, 'tree_urutan') else None
        sel_idx = len(self.manager.urutan_kombinasi)
        if sel:
            sel_idx = self.tree_urutan.index(sel[0])

        nama = simpledialog.askstring("Sisipkan Urutan Kombinasi", "Masukkan nama Urutan Kombinasi baru:", parent=self.root)
        if nama and nama.strip():
            nama = nama.strip()
            old_items = list(self.manager.urutan_kombinasi.items())
            new_dict = {}
            inserted = False
            for i, (k, v) in enumerate(old_items):
                if i == sel_idx:
                    new_dict[nama] = []
                    inserted = True
                new_dict[k] = v
            if not inserted:
                new_dict[nama] = []
            
            self.manager.urutan_kombinasi = new_dict
            self.manager.save_presets()
            self.dropdown_urutan["values"] = list(self.manager.urutan_kombinasi.keys())
            self.var_urutan.set(nama)
            self._on_urutan_selected(None)
            self._refresh_tree_urutan()
            messagebox.showinfo("Sukses", f"Urutan Kombinasi '{nama}' berhasil disisipkan di posisi #{sel_idx + 1}!")

    def _save_current_urutan(self):
        selected_urutan = self.var_urutan.get()
        if not selected_urutan:
            self._new_urutan()
            return
        self.manager.urutan_kombinasi[selected_urutan] = list(self.macro_sequence_queue)
        self.manager.save_presets()
        self._refresh_tree_urutan()
        messagebox.showinfo("Sukses", f"Urutan Kombinasi '{selected_urutan}' berhasil disimpan ke presets.json!")

    def _delete_urutan(self):
        selected = self.var_urutan.get()
        if not selected:
            return
        if messagebox.askyesno("Konfirmasi Hapus", f"Apakah Anda yakin ingin menghapus Urutan Kombinasi '{selected}'?"):
            if selected in self.manager.urutan_kombinasi:
                del self.manager.urutan_kombinasi[selected]
                self.manager.save_presets()
                self.dropdown_urutan["values"] = list(self.manager.urutan_kombinasi.keys())
                if self.manager.urutan_kombinasi:
                    self.dropdown_urutan.current(0)
                    self._on_urutan_selected(None)
                else:
                    self.dropdown_urutan.set("")
                    self.macro_sequence_queue.clear()
                    self._refresh_tree_kiri()
                self._refresh_tree_urutan()

    def _reload_presets(self):
        self.manager.load_presets()
        self.dropdown_urutan["values"] = list(self.manager.urutan_kombinasi.keys())
        self.dropdown_kombinasi["values"] = list(self.manager.kombinasi_gerakan.keys())
        self._refresh_tree_urutan()
        
        if self.manager.urutan_kombinasi:
            self.dropdown_urutan.current(0)
            self._on_urutan_selected(None)
        else:
            self.dropdown_urutan.set("")

        if self.manager.kombinasi_gerakan:
            self.dropdown_kombinasi.current(0)
            self._update_tree_kanan(self.var_combo.get())
        else:
            self.dropdown_kombinasi.set("")
            for item in self.tree_kanan.get_children():
                self.tree_kanan.delete(item)
        self.lbl_status.config(text="Status: Preset dimuat ulang dari presets.json!")
        messagebox.showinfo("Sukses", "Preset berhasil dimuat ulang dari presets.json!")

    # ------------------------------------------------------------------
    # Event Handlers: Antrean Makro
    # ------------------------------------------------------------------

    def _add_to_queue(self):
        nama = self.var_combo.get()
        if nama in self.manager.kombinasi_gerakan:
            self.macro_sequence_queue.append(nama)
            self._sync_active_urutan()
            self._refresh_tree_kiri()
            self._update_tree_kanan(nama)

    def _insert_to_queue(self):
        nama = self.var_combo.get()
        if not nama or nama not in self.manager.kombinasi_gerakan:
            messagebox.showwarning("Peringatan", "Pilih kombinasi gerakan dari library terlebih dahulu!")
            return
        
        sel = self.tree_kiri.selection() if hasattr(self, 'tree_kiri') else None
        if sel:
            idx = self.tree_kiri.index(sel[0])
            self.macro_sequence_queue.insert(idx, nama)
        else:
            self.macro_sequence_queue.append(nama)
            
        self._sync_active_urutan()
        self._refresh_tree_kiri()
        self._update_tree_kanan(nama)

    def _copy_urutan(self):
        from tkinter import simpledialog
        nama_asal = self.var_urutan.get()
        if not nama_asal or nama_asal not in self.manager.urutan_kombinasi:
            messagebox.showwarning("Peringatan", "Pilih Urutan Kombinasi di Level 1 yang ingin di-copy!")
            return
        
        nama_baru = simpledialog.askstring("Copy Urutan Kombinasi", f"Masukkan nama Urutan Kombinasi baru (salinan dari '{nama_asal}'):", 
                                           initialvalue=f"{nama_asal}_copy", parent=self.root)
        if nama_baru and nama_baru.strip():
            nama_baru = nama_baru.strip()
            queue_copy = list(self.manager.urutan_kombinasi[nama_asal])
            self.manager.urutan_kombinasi[nama_baru] = queue_copy
            self.manager.save_presets()
            self.dropdown_urutan["values"] = list(self.manager.urutan_kombinasi.keys())
            self.var_urutan.set(nama_baru)
            self._on_urutan_selected(None)
            self._refresh_tree_urutan()
            messagebox.showinfo("Sukses", f"Urutan Kombinasi '{nama_asal}' berhasil di-copy menjadi '{nama_baru}'!")

    def _copy_preset_kombinasi(self):
        from tkinter import simpledialog
        nama_asal = self.var_combo.get()
        if not nama_asal or nama_asal not in self.manager.kombinasi_gerakan:
            messagebox.showwarning("Peringatan", "Pilih kombinasi dari library yang ingin di-copy!")
            return
        
        nama_baru = simpledialog.askstring("Copy Preset Kombinasi", f"Masukkan nama kombinasi baru (salinan dari '{nama_asal}'):", 
                                           initialvalue=f"{nama_asal}_copy", parent=self.root)
        if nama_baru and nama_baru.strip():
            nama_baru = nama_baru.strip()
            steps_copy = [dict(g) for g in self.manager.kombinasi_gerakan[nama_asal]]
            self.manager.kombinasi_gerakan[nama_baru] = steps_copy
            self.manager.save_presets()
            self.dropdown_kombinasi["values"] = list(self.manager.kombinasi_gerakan.keys())
            self.var_combo.set(nama_baru)
            self._update_tree_kanan(nama_baru)
            messagebox.showinfo("Sukses", f"Preset Kombinasi '{nama_asal}' berhasil di-copy menjadi '{nama_baru}'!")

    def _copy_kombinasi_queue(self):
        sel = self.tree_kiri.selection()
        if not sel:
            messagebox.showwarning("Peringatan", "Pilih kombinasi di daftar antrean (Level 2) yang ingin di-copy!")
            return
        idx = self.tree_kiri.index(sel[0])
        item_nama = self.macro_sequence_queue[idx]
        self.macro_sequence_queue.insert(idx + 1, item_nama)
        self._sync_active_urutan()
        self._refresh_tree_kiri()
        children = self.tree_kiri.get_children()
        if idx + 1 < len(children):
            self.tree_kiri.selection_set(children[idx + 1])

    def _copy_draft_step(self):
        sel = self.tree_draft.selection() if hasattr(self, 'tree_draft') else None
        if not sel:
            messagebox.showwarning("Peringatan", "Pilih langkah di daftar draft yang ingin di-copy!")
            return
        idx = self.tree_draft.index(sel[0])
        step_to_copy = dict(self.draft_steps[idx])
        self.draft_steps.insert(idx + 1, step_to_copy)
        self._refresh_tree_draft()
        children = self.tree_draft.get_children()
        if idx + 1 < len(children):
            self.tree_draft.selection_set(children[idx + 1])

    def _delete_selected_macro(self):
        sel = self.tree_kiri.selection()
        if not sel:
            messagebox.showwarning("Peringatan", "Pilih kombinasi di daftar antrean!")
            return
        no = int(self.tree_kiri.item(sel[0], "values")[0])
        del self.macro_sequence_queue[no - 1]
        self._sync_active_urutan()
        self._refresh_tree_kiri()
        if self.macro_sequence_queue:
            self._update_tree_kanan(self.macro_sequence_queue[0])
        else:
            for item in self.tree_kanan.get_children():
                self.tree_kanan.delete(item)

    def _clear_sequence(self):
        self.macro_sequence_queue.clear()
        self._sync_active_urutan()
        self._refresh_tree_kiri()
        for item in self.tree_kanan.get_children():
            self.tree_kanan.delete(item)

    def _select_urutan_in_ui(self, urutan_name):
        if hasattr(self, 'var_urutan'):
            self.var_urutan.set(urutan_name)
            self._on_urutan_selected(None)
            self._refresh_tree_urutan()

    def _start_execution(self):
        if not self.manager.pygame_socket:
            messagebox.showerror("Error", "Tidak terhubung ke Pygame!")
            return
        if not self.manager.urutan_kombinasi:
            messagebox.showwarning("Peringatan", "Daftar Urutan Kombinasi kosong!")
            return

        # Start from the first Urutan Kombinasi in Level 1
        t = threading.Thread(target=self.manager.execute_full_hierarchy,
                             args=(0, 0, 0))
        t.daemon = True
        t.start()

    def _start_execution_from(self):
        if not self.manager.pygame_socket:
            messagebox.showerror("Error", "Tidak terhubung ke Pygame!")
            return
        if not self.manager.urutan_kombinasi:
            messagebox.showwarning("Peringatan", "Daftar Urutan Kombinasi kosong!")
            return

        # 1. Cari urutan terpilih di tree_urutan
        sel_urutan = self.tree_urutan.selection() if hasattr(self, 'tree_urutan') else None
        start_urutan_idx = 0
        if sel_urutan:
            start_urutan_idx = self.tree_urutan.index(sel_urutan[0])
        else:
            selected_urutan = self.var_urutan.get()
            urutan_keys = list(self.manager.urutan_kombinasi.keys())
            if selected_urutan in urutan_keys:
                start_urutan_idx = urutan_keys.index(selected_urutan)

        # 2. Cari kombinasi terpilih di tree_kiri
        sel_kiri = self.tree_kiri.selection() if hasattr(self, 'tree_kiri') else None
        start_combo_idx = 0
        if sel_kiri:
            start_combo_idx = self.tree_kiri.index(sel_kiri[0])

        # 3. Cari langkah terpilih di tree_kanan
        sel_kanan = self.tree_kanan.selection() if hasattr(self, 'tree_kanan') else None
        start_step_idx = 0
        if sel_kanan:
            step_no = int(self.tree_kanan.item(sel_kanan[0], "values")[0])
            start_step_idx = step_no - 1

        t = threading.Thread(target=self.manager.execute_full_hierarchy,
                             args=(start_urutan_idx, start_combo_idx, start_step_idx))
        t.daemon = True
        t.start()

    # ------------------------------------------------------------------
    # Helpers: Tree View
    # ------------------------------------------------------------------

    def _refresh_tree_urutan(self):
        if not hasattr(self, 'tree_urutan'):
            return
        for item in self.tree_urutan.get_children():
            self.tree_urutan.delete(item)
        if hasattr(self.manager, 'urutan_kombinasi'):
            current_active = self.var_urutan.get() if hasattr(self, 'var_urutan') else ""
            for i, nama in enumerate(self.manager.urutan_kombinasi.keys(), 1):
                item_id = self.tree_urutan.insert("", "end", values=(i, nama))
                if nama == current_active:
                    self.tree_urutan.selection_set(item_id)

    def _on_urutan_tree_select(self, event):
        sel = self.tree_urutan.selection()
        if sel:
            nama_urutan = self.tree_urutan.item(sel[0], "values")[1]
            if hasattr(self, 'var_urutan'):
                self.var_urutan.set(nama_urutan)
            self._on_urutan_selected(None)

    def _refresh_tree_kiri(self):
        if not hasattr(self, 'tree_kiri'):
            return
        for item in self.tree_kiri.get_children():
            self.tree_kiri.delete(item)
        for i, nama in enumerate(self.macro_sequence_queue, 1):
            self.tree_kiri.insert("", "end", values=(i, nama))

    def _on_kiri_select(self, event):
        sel = self.tree_kiri.selection()
        if sel:
            nama = self.tree_kiri.item(sel[0], "values")[1]
            self._update_tree_kanan(nama)

    def _update_tree_kanan(self, nama_kombinasi):
        for item in self.tree_kanan.get_children():
            self.tree_kanan.delete(item)
        if nama_kombinasi in self.manager.kombinasi_gerakan:
            for idx, g in enumerate(self.manager.kombinasi_gerakan[nama_kombinasi], 1):
                vw_val = "-" if g.get("vw") is None else int(g["vw"])
                desc_val = g.get("keterangan", "")
                if not desc_val:
                    desc_val = "-"
                self.tree_kanan.insert("", "end", values=(
                    idx, g["nama"], int(g["vx"]), int(g["vy"]), vw_val,
                    g["limit_type"], g["limit_val"], desc_val,
                ))

    def _highlight_kiri_row(self, index):
        children = self.tree_kiri.get_children()
        if index < len(children):
            self.tree_kiri.selection_set(children[index])
            self.tree_kiri.see(children[index])
    # ------------------------------------------------------------------
    # Penutupan & Latar Belakang
    # ------------------------------------------------------------------

    def _on_closing(self):
        if self.manager.pygame_socket:
            self.manager.pygame_socket.close()
        self.root.destroy()
        os._exit(0)




