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
from PIL import Image, ImageTk

from gui.logic import SequenceManager


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
                "delay",
                "find coordinate",
                "reset coordinate",
                "balance depan",
                "balance kiri",
                "balance depan kiri",
                "ambil kubus",
                "taruh kubus"
            ],
            width=18
        )
        self.entry_step_name.set("local odometry")
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
            inputs_frame, values=["Waktu (s)", "Jarak (px)", "Sudut (°)", "Sensor Garis"],
            state="readonly", width=10
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
    def _build_status_frame(self, parent):
        frame = ttk.LabelFrame(parent, text=" 🏃 Sequence Execution Monitor ")
        frame.pack(fill="x", padx=10, pady=5)
        
        self.lbl_mon_status = ttk.Label(frame, text="💤 SYSTEM IDLE", font=("Segoe UI", 11, "bold"), foreground="#ffffff")
        self.lbl_mon_status.pack(side="left", padx=15, pady=5)
        
        self.lbl_mon_step = ttk.Label(frame, text="Gerakan: -", font=("Segoe UI", 10, "bold"), foreground="#ffffff")
        self.lbl_mon_step.pack(side="left", expand=True, fill="x", padx=15, pady=5)
        
        self.lbl_mon_limit = ttk.Label(frame, text="Progress: -", font=("Segoe UI", 10, "bold"), foreground="#ffffff")
        self.lbl_mon_limit.pack(side="right", padx=15, pady=5)
    def _build_selector_frame(self, parent):
        frame = ttk.LabelFrame(parent, text=" Pilih Variabel Kombinasi Gerakan ")
        frame.pack(fill="x", padx=5, pady=5)

        # Row 1: Dropdown selection + Add button
        row1 = ttk.Frame(frame)
        row1.pack(fill="x", padx=5, pady=2)
        ttk.Label(row1, text="Kombinasi:").pack(side="left", padx=5, pady=2)
        
        self.var_combo = tk.StringVar()
        self.dropdown_kombinasi = ttk.Combobox(
            row1, textvariable=self.var_combo,
            values=list(self.manager.kombinasi_gerakan.keys()),
            state="readonly", width=25
        )
        self.dropdown_kombinasi.pack(side="left", padx=5, pady=2)
        if self.manager.kombinasi_gerakan:
            self.dropdown_kombinasi.current(0)

        ttk.Button(row1, text="➕ Tambah ke Urutan", command=self._add_to_queue).pack(side="left", padx=5)

        # Row 2: Preset actions
        row2 = ttk.Frame(frame)
        row2.pack(fill="x", padx=5, pady=2)
        
        ttk.Button(row2, text="✏️ Edit Preset",       command=self._load_preset_to_draft).pack(side="left", padx=5)
        ttk.Button(row2, text="🗑️ Hapus Preset",      command=self._delete_preset).pack(side="left", padx=5)
        ttk.Button(row2, text="🔄 Reload JSON",        command=self._reload_presets).pack(side="left", padx=5)

    def _build_telemetry_frame(self, parent):
        frame = ttk.LabelFrame(parent, text=" 📡 Live Telemetry & Odometry Dashboard ")
        frame.pack(fill="x", padx=5, pady=5)

        def _card(label_text, value_text, fg):
            card = ttk.Frame(frame, relief="groove", padding=10)
            card.pack(side="left", expand=True, fill="both", padx=5, pady=5)
            ttk.Label(card, text=label_text, font=("Segoe UI", 9, "bold"), foreground="#a29bb5").pack()
            lbl = ttk.Label(card, text=value_text, font=("Segoe UI", 16, "bold"), foreground=fg)
            lbl.pack(pady=2)
            return lbl

        self.lbl_tele_x = _card("KOORDINAT X",        "0.0 cm",  "#ffffff")
        self.lbl_tele_y = _card("KOORDINAT Y",        "0.0 cm",  "#ffffff")
        self.lbl_tele_w = _card("ARAH HADAP (HEADING)", "0°",    "#ffffff")
        self.lbl_tele_d = _card("JARAK TEMPUH",       "0.00 m",  "#ffffff")

        # Card 5: Line Sensors
        card_sensor = ttk.Frame(frame, relief="groove", padding=10)
        card_sensor.pack(side="left", expand=True, fill="both", padx=5, pady=5)
        ttk.Label(card_sensor, text="SENSOR GARIS", font=("Segoe UI", 9, "bold"), foreground="#a29bb5").pack()
        
        sensor_box = ttk.Frame(card_sensor)
        sensor_box.pack(pady=4)
        
        self.lbl_sensor_l = ttk.Label(sensor_box, text="⬤ L", font=("Segoe UI", 12, "bold"), foreground="#888888")
        self.lbl_sensor_l.pack(side="left", padx=10)
        
        self.lbl_sensor_r = ttk.Label(sensor_box, text="⬤ R", font=("Segoe UI", 12, "bold"), foreground="#888888")
        self.lbl_sensor_r.pack(side="left", padx=10)

        # Card 6: Storage Kubus (counter + 8 slot warna)
        card_storage = ttk.Frame(frame, relief="groove", padding=10)
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

    def _on_storage_slot_click(self, slot_idx):
        mon = self.manager.active_step_info
        if mon.get("status") == "RUNNING":
            return  # Jangan izinkan edit saat sequence berjalan

        # Dapatkan list warna saat ini, pad dengan "-" sampai 8 slot
        current_colors = list(self.manager.storage_colors)
        while len(current_colors) < 8:
            current_colors.append("-")
        
        # Logic siklus warna: "-" -> "R" -> "G" -> "B" -> "-"
        cycle = ["-", "R", "G", "B"]
        current = current_colors[slot_idx]
        if current not in cycle:
            current = "-"
        
        next_idx = (cycle.index(current) + 1) % len(cycle)
        current_colors[slot_idx] = cycle[next_idx]
        
        # Perbarui state GUI secara instan
        self.manager.storage_colors = current_colors
        self.manager.storage_count = sum(1 for c in current_colors if c != "-")
        
        # Kirim perintah update storage ke simulator
        self.manager.set_storage_manual(current_colors)

    def _reset_storage(self):
        empty_colors = ["-"] * 8
        self.manager.storage_colors = empty_colors
        self.manager.storage_count = 0
        self.manager.send_command("RESET_STORAGE")

    def _build_queue_panels(self, parent):
        paned = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        paned.pack(fill="both", expand=True, padx=5, pady=5)

        # Kiri: antrean kombinasi
        frame_kiri = ttk.LabelFrame(paned, text=" Urutan Antrean Kombinasi ")
        paned.add(frame_kiri, weight=1)

        # Button frame at the bottom of frame_kiri
        kiri_btn_frame = ttk.Frame(frame_kiri)
        kiri_btn_frame.pack(side="bottom", fill="x", padx=5, pady=5)
        
        ttk.Button(kiri_btn_frame, text="➖ Hapus Pilihan", command=self._delete_selected_macro).pack(side="left", padx=2, expand=True, fill="x")
        ttk.Button(kiri_btn_frame, text="🗑 Clear Semua", command=self._clear_sequence).pack(side="right", padx=2, expand=True, fill="x")

        self.tree_kiri = ttk.Treeview(
            frame_kiri, columns=("no", "kombinasi"), show="headings"
        )
        self.tree_kiri.heading("no",         text="No")
        self.tree_kiri.heading("kombinasi",  text="Nama Variabel Kombinasi")
        self.tree_kiri.column("no",          width=40,  anchor="center")
        self.tree_kiri.column("kombinasi",   width=180, anchor="w")
        self.tree_kiri.pack(fill="both", expand=True, padx=5, pady=5)
        self.tree_kiri.bind("<<TreeviewSelect>>", self._on_kiri_select)

        # Kanan: detail langkah
        frame_kanan = ttk.LabelFrame(paned, text=" Detail Isi Gerakan ")
        paned.add(frame_kanan, weight=2)

        # Button frame at the bottom of frame_kanan
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

            self.lbl_tele_x.config(text=f"{y_cm:+.1f} cm")
            self.lbl_tele_y.config(text=f"{x_cm:+.1f} cm")
            self.lbl_tele_w.config(text=f"{deg:.0f}°")
            self.lbl_tele_d.config(text=f"{dist:.2f} m")
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
        else:
            for lbl in (self.lbl_tele_x, self.lbl_tele_y,
                        self.lbl_tele_w, self.lbl_tele_d):
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
        
        if status == "RUNNING":
            self.lbl_mon_status.config(text="🏃 EXECUTING", foreground="#ffffff")
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
            self.lbl_mon_status.config(text="💤 SYSTEM IDLE", foreground="#ffffff")
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

    def _reload_presets(self):
        self.manager.load_presets()
        self.dropdown_kombinasi["values"] = list(self.manager.kombinasi_gerakan.keys())
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
            self._refresh_tree_kiri()

    def _delete_selected_macro(self):
        sel = self.tree_kiri.selection()
        if not sel:
            messagebox.showwarning("Peringatan", "Pilih kombinasi di daftar kiri!")
            return
        no = int(self.tree_kiri.item(sel[0], "values")[0])
        del self.macro_sequence_queue[no - 1]
        self._refresh_tree_kiri()
        for item in self.tree_kanan.get_children():
            self.tree_kanan.delete(item)

    def _clear_sequence(self):
        self.macro_sequence_queue.clear()
        self._refresh_tree_kiri()
        for item in self.tree_kanan.get_children():
            self.tree_kanan.delete(item)

    def _start_execution(self):
        if not self.manager.pygame_socket:
            messagebox.showerror("Error", "Tidak terhubung ke Pygame!")
            return
        if not self.macro_sequence_queue:
            messagebox.showwarning("Peringatan", "Antrean kosong!")
            return
        t = threading.Thread(target=self.manager.execute_sequence,
                             args=(self.macro_sequence_queue, 0, 0))
        t.daemon = True
        t.start()

    def _start_execution_from(self):
        if not self.manager.pygame_socket:
            messagebox.showerror("Error", "Tidak terhubung ke Pygame!")
            return
        if not self.macro_sequence_queue:
            messagebox.showwarning("Peringatan", "Antrean kosong!")
            return
        
        # Cari kombinasi terpilih di tree_kiri
        sel_kiri = self.tree_kiri.selection()
        if not sel_kiri:
            messagebox.showwarning("Peringatan", "Pilih salah satu kombinasi di antrean terlebih dahulu!")
            return
        start_combo_idx = self.tree_kiri.index(sel_kiri[0])
        
        # Cari langkah terpilih di tree_kanan (opsional, default ke langkah 0)
        sel_kanan = self.tree_kanan.selection()
        start_step_idx = 0
        if sel_kanan:
            step_no = int(self.tree_kanan.item(sel_kanan[0], "values")[0])
            start_step_idx = step_no - 1

        t = threading.Thread(target=self.manager.execute_sequence,
                             args=(self.macro_sequence_queue, start_combo_idx, start_step_idx))
        t.daemon = True
        t.start()

    # ------------------------------------------------------------------
    # Helpers: Tree View
    # ------------------------------------------------------------------

    def _refresh_tree_kiri(self):
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




