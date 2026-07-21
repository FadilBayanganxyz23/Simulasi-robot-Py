"""
gui/logic.py
============
Bertanggung jawab atas:
- Koneksi socket ke simulator Pygame (SequenceManager)
- Penerimaan data telemetri (listen_to_pygame)
- Eksekusi sekuens gerakan (execute_sequence)
- Manajemen preset kombinasi gerakan (load/save presets.json)

Tidak ada kode UI Tkinter di sini.
"""

import socket
import threading
import time
import math
import json
import os


class SequenceManager:
    """
    Mengelola komunikasi dengan simulator Pygame dan eksekusi sekuens gerakan.

    Antarmuka publik:
        robot_pos       : dict {x, y, angle, dist}
        robot_navigating: bool — True jika simulator sedang dalam mode navigasi A*
        kombinasi_gerakan: dict nama→list_langkah
        pygame_socket   : socket aktif atau None
    """
    def __init__(self, gui_app=None):
        self.gui_app          = gui_app
        self.pygame_socket    = None
        self.robot_pos        = {"x": 0.0, "y": 0.0, "angle": 0.0, "dist": 0.0}
        self.running_sequence = False
        self.robot_navigating = False
        self.robot_balancing  = False   # True saat balance state machine aktif di simulator
        self.robot_grabbing   = False   # True saat grab sequence aktif di simulator
        self.robot_dropping   = False   # True saat drop sequence aktif di simulator
        self.storage_count    = 0       # Jumlah kubus di storage robot (0-8)
        self.storage_colors   = ["-"] * 8      # List warna kubus: ["R", "G", "B", ...] atau "-"
        self.line_sensors     = {"left": 0, "right": 0}
        self.line_latch       = False
        self.robot_front_dist = 1500.0
        self.robot_left_dist  = 1500.0
        self.stand_memory     = {}
        self.target_memory    = {}
        self.active_step_info = {
            "status": "IDLE",
            "kombinasi": "-",
            "nama": "-",
            "limit_type": "-",
            "limit_val": 0.0,
            "current_val": 0.0,
            "q_idx": 0,
            "q_total": 0,
            "step_idx": 0,
            "step_total": 0
        }
        # Preset default (tidak boleh dihapus dari UI)
        self.default_presets = {
            "Bentuk_L": [
                {"nama": "Maju",        "vx": 10, "vy": 0,  "vw": 0, "limit_type": "Waktu (s)", "limit_val": 2.0},
                {"nama": "Geser Kanan", "vx": 0,  "vy": 10, "vw": 0, "limit_type": "Waktu (s)", "limit_val": 1.5},
                {"nama": "Serong Kanan","vx": 12, "vy": 12, "vw": 0, "limit_type": "Waktu (s)", "limit_val": 2.0},
            ],
            "Rotasi_Kotak": [
                {"nama": "Maju",       "vx": 12,  "vy": 0, "vw": 0,  "limit_type": "Waktu (s)", "limit_val": 1.0},
                {"nama": "Putar Balik","vx": 0,   "vy": 0, "vw": 5,  "limit_type": "Sudut (°)", "limit_val": 180.0},
                {"nama": "Mundur",     "vx": -12, "vy": 0, "vw": 0,  "limit_type": "Waktu (s)", "limit_val": 1.0},
            ],
            "Kombinasi B": [
                {"nama": "Maju Cepat", "vx": 15,  "vy": 0,   "vw": 0,  "limit_type": "Waktu (s)", "limit_val": 1.5},
                {"nama": "Putar Kanan","vx": 0,   "vy": 0,   "vw": 10, "limit_type": "Sudut (°)", "limit_val": 90.0},
                {"nama": "Geser Kiri", "vx": 0,   "vy": -10, "vw": 0,  "limit_type": "Waktu (s)", "limit_val": 1.5},
            ],
        }
        self.kombinasi_gerakan = {}
        self.load_presets()

    # ------------------------------------------------------------------
    # Koneksi Socket
    # ------------------------------------------------------------------

    def start_connection(self):
        """Mulai thread koneksi ke simulator (background)."""
        threading.Thread(target=self._connect_loop, daemon=True).start()

    def _connect_loop(self):
        while True:
            if self.pygame_socket is None:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(0.1)
                    s.connect(('127.0.0.1', 5005))
                    s.settimeout(None)
                    self.pygame_socket = s
                    threading.Thread(target=self._listen_loop,
                                     args=(s,), daemon=True).start()
                except (ConnectionRefusedError, socket.timeout):
                    pass
            time.sleep(1.0)

    def _listen_loop(self, s):
        """Terima dan parse data STATUS dari simulator."""
        buffer = ""
        while True:
            try:
                data = s.recv(1024)
                if not data:
                    break
                buffer += data.decode('utf-8')
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    parts = line.split()
                    if len(parts) >= 3 and parts[0] == "SCAN_RESULT":
                        label = " ".join(parts[1:-1])
                        color = parts[-1]
                        self.stand_memory[label] = color
                    elif len(parts) >= 8 and parts[0] == "SCAN_ALMARI_RESULT":
                        # SCAN_ALMARI_RESULT prefix S1 c1 S2 c2 S3 c3
                        prefix = parts[1]
                        self.stand_memory[f"{prefix} S1"] = parts[3]
                        self.stand_memory[f"{prefix} S2"] = parts[5]
                        self.stand_memory[f"{prefix} S3"] = parts[7]
                    elif len(parts) >= 8 and parts[0] == "SCAN_TARGET_RESULT":
                        # SCAN_TARGET_RESULT prefix S1 c1 S2 c2 S3 c3
                        prefix = parts[1]
                        self.target_memory[f"{prefix} S1"] = parts[3]
                        self.target_memory[f"{prefix} S2"] = parts[5]
                        self.target_memory[f"{prefix} S3"] = parts[7]
                    elif len(parts) >= 4 and parts[0] == "STATUS":
                        self.robot_pos["x"]     = float(parts[1])
                        self.robot_pos["y"]     = float(parts[2])
                        self.robot_pos["angle"] = float(parts[3])
                        if len(parts) >= 5:
                            self.robot_pos["dist"] = float(parts[4])
                        if len(parts) >= 6:
                            self.robot_navigating = (int(parts[5]) == 1)
                        else:
                            self.robot_navigating = False
                        # Kolom 7: bal_status (1=balance aktif, 0=selesai)
                        if len(parts) >= 7:
                            self.robot_balancing = (int(parts[6]) == 1)
                        else:
                            self.robot_balancing = False
                        
                        # Kolom 9 & 10: line_l, line_r (0 atau 1)
                        if len(parts) >= 10:
                            l_val = int(parts[8])
                            r_val = int(parts[9])
                            self.line_sensors["left"]  = l_val
                            self.line_sensors["right"] = r_val
                            if l_val == 1 or r_val == 1:
                                self.line_latch = True
                        else:
                            self.line_sensors["left"]  = 0
                            self.line_sensors["right"] = 0
                        
                        # Kolom 11: grab_active (1=grab sequence aktif)
                        if len(parts) >= 11:
                            self.robot_grabbing = (int(parts[10]) == 1)
                        else:
                            self.robot_grabbing = False
                        
                        # Kolom 15: front_dist
                        if len(parts) >= 15:
                            self.robot_front_dist = float(parts[14])
                        else:
                            self.robot_front_dist = 1500.0
                            
                        # Kolom 16: left_dist
                        if len(parts) >= 16:
                            self.robot_left_dist = float(parts[15])
                        else:
                            self.robot_left_dist = 1500.0
                        
                        # Kolom 12: storage_count (jumlah kubus)
                        if len(parts) >= 12:
                            self.storage_count = int(parts[11])
                        else:
                            self.storage_count = 0
                        
                        # Kolom 13: storage_colors ("R,G,B" atau "-")
                        if len(parts) >= 13:
                            raw_colors = parts[12]
                            self.storage_colors = raw_colors.split(",") if raw_colors != "-" else ["-"] * 8
                            while len(self.storage_colors) < 8:
                                self.storage_colors.append("-")
                        else:
                            self.storage_colors = ["-"] * 8
                            
                        # Kolom 14: drop_active
                        if len(parts) >= 14:
                            self.robot_dropping = (int(parts[13]) == 1)
                        else:
                            self.robot_dropping = False
            except Exception:
                break
        self.pygame_socket = None

    def send_command(self, cmd_str):
        """Kirim perintah ke simulator (thread-safe)."""
        if self.pygame_socket:
            try:
                self.pygame_socket.sendall((cmd_str + "\n").encode('utf-8'))
            except (ConnectionResetError, BrokenPipeError):
                self.pygame_socket = None

    def set_storage_manual(self, colors_list):
        """Kirim perintah update storage ke simulator"""
        if self.pygame_socket and not self.running_sequence:
            color_str = ",".join(colors_list) if colors_list else "-"
            self.send_command(f"SET_STORAGE {color_str}")

    # ------------------------------------------------------------------
    # Manajemen Preset
    # ------------------------------------------------------------------

    def load_presets(self):
        """Muat preset dari presets.json (kombinasi_gerakan & urutan_kombinasi)."""
        self.urutan_kombinasi = {}
        if os.path.exists("presets.json"):
            try:
                with open("presets.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "kombinasi_gerakan" in data:
                        self.kombinasi_gerakan = data.get("kombinasi_gerakan", {})
                        self.urutan_kombinasi = data.get("urutan_kombinasi", {})
                    else:
                        # Format lama
                        self.kombinasi_gerakan = data
                        self.urutan_kombinasi = {"Urutan Misi Utama": list(self.kombinasi_gerakan.keys())}
                if not self.urutan_kombinasi:
                    self.urutan_kombinasi = {"Urutan Misi Utama": list(self.kombinasi_gerakan.keys())}
                return
            except Exception:
                pass
        self.kombinasi_gerakan = dict(self.default_presets)
        self.urutan_kombinasi = {"Urutan Misi Utama": list(self.kombinasi_gerakan.keys())}
        self.save_presets()

    def save_presets(self):
        """Simpan preset ke presets.json."""
        try:
            with open("presets.json", "w", encoding="utf-8") as f:
                data = {
                    "kombinasi_gerakan": self.kombinasi_gerakan,
                    "urutan_kombinasi": self.urutan_kombinasi
                }
                json.dump(data, f, indent=4)
        except Exception as e:
            if self.gui_app:
                self.gui_app.show_error(f"Gagal menyimpan preset: {e}")

    # ------------------------------------------------------------------
    # Eksekusi Sekuens (Hierarki 3-Tingkat)
    # ------------------------------------------------------------------
    def execute_sequence(self, macro_sequence_queue, start_combo_idx=0, start_step_idx=0, urutan_name="Urutan Kombinasi"):
        self.execute_full_hierarchy(0, start_combo_idx, start_step_idx)

    def execute_full_hierarchy(self, start_urutan_idx=0, start_combo_idx=0, start_step_idx=0):
        """Jalankan seluruh Urutan Kombinasi secara berurutan (Urutan 1 -> Urutan 2 -> ...)."""
        self.running_sequence = True
        self.active_step_info["status"] = "RUNNING"
        self.jump_target_u_idx = None
        if self.gui_app:
            self.gui_app.set_run_button_state("disabled")

        urutan_keys = list(self.urutan_kombinasi.keys())
        u_total = len(urutan_keys)

        try:
            curr_u_idx = start_urutan_idx
            while curr_u_idx < u_total and self.running_sequence:
                urutan_name = urutan_keys[curr_u_idx]
                macro_sequence_queue = self.urutan_kombinasi.get(urutan_name, [])
                q_total = len(macro_sequence_queue)
                
                self.active_step_info["urutan_name"] = urutan_name
                self.active_step_info["u_idx"] = curr_u_idx + 1
                self.active_step_info["u_total"] = u_total

                # Auto-select Urutan Kombinasi aktif pada UI
                if self.gui_app:
                    self.gui_app.root.after(0, lambda u_name=urutan_name: self.gui_app._select_urutan_in_ui(u_name))

                time.sleep(0.15)

                for idx_k, nama_kombinasi in enumerate(macro_sequence_queue, 1):
                    if not self.running_sequence or self.jump_target_u_idx is not None:
                        break
                    # Lewati kombinasi sebelum start_combo_idx hanya pada urutan awal start_urutan_idx
                    if curr_u_idx == start_urutan_idx and idx_k < start_combo_idx + 1:
                        continue

                    self.active_step_info["kombinasi"] = nama_kombinasi
                    self.active_step_info["q_idx"] = idx_k
                    self.active_step_info["q_total"] = q_total

                    if self.gui_app:
                        self.gui_app.highlight_row(idx_k - 1)
                        self.gui_app.update_detail_view(nama_kombinasi)

                    time.sleep(0.2)
                    list_gerakan = self.kombinasi_gerakan.get(nama_kombinasi, [])
                    step_total = len(list_gerakan)

                    for idx_s, gerak in enumerate(list_gerakan, 1):
                        if not self.running_sequence or self.jump_target_u_idx is not None:
                            break
                        # Lewati langkah sebelum start_step_idx hanya pada urutan awal & kombinasi awal
                        if curr_u_idx == start_urutan_idx and idx_k == start_combo_idx + 1 and idx_s < start_step_idx + 1:
                            continue

                        nama_lower = gerak["nama"].lower()
                        self.active_step_info["start_x"] = self.robot_pos.get("x", 0)
                        self.active_step_info["start_y"] = self.robot_pos.get("y", 0)
                        self.active_step_info["start_angle"] = self.robot_pos.get("angle", 0)
                        self.active_step_info["nama"] = gerak["nama"]
                        self.active_step_info["step_idx"] = idx_s
                        self.active_step_info["step_total"] = step_total

                        self.active_step_info["temp_x"] = 0.0
                        self.active_step_info["temp_y"] = 0.0
                        self.active_step_info["temp_w"] = 0.0

                        # ---- Reset Odometry / Reset Coordinate ----
                        if (nama_lower.startswith("reset odometry") or
                                nama_lower.startswith("reset_odometry") or
                                "reset coordinate" in nama_lower or
                                "reset_coordinate" in nama_lower):
                            self.active_step_info["limit_type"] = "Reset Odom"
                            self.active_step_info["limit_val"] = 0.0
                            self.active_step_info["current_val"] = 0.0
                            self.send_command("RESET_ODOM")
                            time.sleep(0.15)
                            continue
    
                        # ---- Ambil Kubus Command ----
                        if "ambil kubus" in nama_lower or "ambil_kubus" in nama_lower or "grab" in nama_lower:
                            self.active_step_info["limit_type"] = "Ambil Kubus"
                            self.active_step_info["limit_val"] = 1.0
                            self.active_step_info["current_val"] = 0.0
                            storage_before = self.storage_count
                            self.send_command("AMBIL_KUBUS")
    
                            # Tunggu grab sequence MULAI di simulator (max 1 detik)
                            wait_start = time.time()
                            while self.running_sequence and not self.robot_grabbing:
                                time.sleep(0.05)
                                if time.time() - wait_start > 1.0:
                                    break
    
                            # Tunggu grab sequence SELESAI di simulator (max 10 detik)
                            wait_start = time.time()
                            while self.running_sequence and self.robot_grabbing:
                                time.sleep(0.05)
                                elapsed = time.time() - wait_start
                                self.active_step_info["current_val"] = min(1.0, elapsed / 5.0)
                                if elapsed > 10.0:
                                    break
    
                            self.active_step_info["current_val"] = 1.0
                            time.sleep(0.15)
                            continue
    
                        # ---- Scan Stand Command ----
                        if "scan stand" in nama_lower or "scan_stand" in nama_lower:
                            self.active_step_info["limit_type"] = "Scan Stand"
                            self.active_step_info["limit_val"] = 1.0
                            self.active_step_info["current_val"] = 0.0
                            label = str(gerak.get("keterangan", "")).strip()
                            if label:
                                self.send_command("VEL 0 0 0") # Stop movement
                                if self.gui_app:
                                    self.gui_app.root.after(0, self.gui_app.open_camera)
                                time.sleep(1.0) # Wait for camera to show
                                
                                self.send_command(f"SCAN_STAND {label}")
                                # Wait a bit for scan to complete and receive telemetry
                                time.sleep(1.0)
                                
                                if self.gui_app:
                                    self.gui_app.root.after(0, self.gui_app.close_camera)
                            self.active_step_info["current_val"] = 1.0
                            time.sleep(0.15)
                            continue
    
                        # ---- Scan Almari Command ----
                        if "scan almari" in nama_lower or "scan_almari" in nama_lower:
                            self.active_step_info["limit_type"] = "Scan Almari"
                            self.active_step_info["limit_val"] = 1.0
                            self.active_step_info["current_val"] = 0.0
                            label_prefix = str(gerak.get("keterangan", "")).strip()
                            if label_prefix:
                                self.send_command("VEL 0 0 0") # Stop movement
                                if self.gui_app:
                                    self.gui_app.root.after(0, self.gui_app.open_camera)
                                time.sleep(1.0) # Wait for camera to show
                                
                                self.send_command(f"SCAN_ALMARI {label_prefix}")
                                # Wait a bit for scan to complete and receive telemetry
                                time.sleep(1.0)
                                
                                if self.gui_app:
                                    self.gui_app.root.after(0, self.gui_app.close_camera)
                            self.active_step_info["current_val"] = 1.0
                            time.sleep(0.15)
                            continue
    
                        # ---- Scan Target Command ----
                        if "scan target" in nama_lower or "scan_target" in nama_lower:
                            self.active_step_info["limit_type"] = "Scan Target"
                            self.active_step_info["limit_val"] = 1.0
                            self.active_step_info["current_val"] = 0.0
                            label_prefix = str(gerak.get("keterangan", "")).strip()
                            if label_prefix:
                                self.send_command("VEL 0 0 0") # Stop movement
                                if self.gui_app:
                                    self.gui_app.root.after(0, self.gui_app.open_camera)
                                time.sleep(1.0) # Wait for camera to show
                                
                                self.send_command(f"SCAN_TARGET {label_prefix}")
                                # Wait a bit for scan to complete and receive telemetry
                                time.sleep(1.0)
                                
                                if self.gui_app:
                                    self.gui_app.root.after(0, self.gui_app.close_camera)
                            self.active_step_info["current_val"] = 1.0
                            time.sleep(0.15)
                            continue
    
                        # ---- Apakah Diambil? Command ----
                        if "apakah diambil" in nama_lower or "apakah_diambil" in nama_lower:
                            self.active_step_info["limit_type"] = "Cek Ambil"
                            self.active_step_info["limit_val"] = 1.0
                            self.active_step_info["current_val"] = 0.0
                            stand_label = str(gerak.get("keterangan", "")).strip()
                            
                            # Hitung total target Almari A yang masih dibutuhkan
                            needed_counts = {"RED": 0, "GREEN": 0, "BLUE": 0}
                            for k, v in self.target_memory.items():
                                if v in needed_counts:
                                    needed_counts[v] += 1
                                    
                            # Kurangi warna kubus yang sudah ada di storage robot saat ini
                            for color_code in self.storage_colors:
                                if color_code == "R": needed_counts["RED"] -= 1
                                elif color_code == "G": needed_counts["GREEN"] -= 1
                                elif color_code == "B": needed_counts["BLUE"] -= 1
                                
                            # Warna kubus yang terdeteksi di stand saat ini
                            scanned_color = self.stand_memory.get(stand_label, "EMPTY")
                            
                            # Cek apakah warna sesuai dengan target yang masih dibutuhkan & storage belum penuh
                            is_needed = (scanned_color in needed_counts) and (needed_counts[scanned_color] > 0) and (self.storage_count < 8)
                            
                            # Edit gerakan selanjutnya secara otomatis
                            if idx_s < step_total:
                                next_gerak = list_gerakan[idx_s]
                                if is_needed:
                                    next_gerak["nama"] = "ambil kubus"
                                    next_gerak["keterangan"] = stand_label
                                else:
                                    next_gerak["nama"] = "delay"
                                    next_gerak["limit_type"] = "Waktu (s)"
                                    next_gerak["limit_val"] = 0.1
                                    next_gerak["keterangan"] = "Dilewati (Tidak Cocok Target)"
                                    
                                if self.gui_app:
                                    self.gui_app.update_detail_view(nama_kombinasi)
                                    
                            self.active_step_info["current_val"] = 1.0
                            time.sleep(0.15)
                            continue
    
                        # ---- Apakah Ditaruh? Command ----
                        if "apakah ditaruh" in nama_lower or "apakah_ditaruh" in nama_lower:
                            self.active_step_info["limit_type"] = "Cek Taruh"
                            self.active_step_info["limit_val"] = 1.0
                            self.active_step_info["current_val"] = 0.0
                            dest_slot = str(gerak.get("keterangan", "")).strip()
                            
                            # Tentukan target_color (dari nama warna di keterangan ATAU dari target_memory):
                            dest_upper = dest_slot.upper()
                            target_color = "EMPTY"
                            if "RED" in dest_upper or "MERAH" in dest_upper:
                                target_color = "RED"
                            elif "GREEN" in dest_upper or "HIJAU" in dest_upper:
                                target_color = "GREEN"
                            elif "BLUE" in dest_upper or "BIRU" in dest_upper:
                                target_color = "BLUE"
                            else:
                                target_color = self.target_memory.get(dest_slot, "EMPTY")
                            
                            # Membaca seluruh warna kubus dalam storage dan mencocokkan 1 per 1
                            found_slot_idx = -1
                            if target_color != "EMPTY":
                                target_code = None
                                if target_color == "RED": target_code = "R"
                                elif target_color == "GREEN": target_code = "G"
                                elif target_color == "BLUE": target_code = "B"
                                
                                if target_code:
                                    for i_st, c_code in enumerate(self.storage_colors):
                                        if c_code == target_code:
                                            found_slot_idx = i_st
                                            break
                                
                            # Edit gerakan selanjutnya (taruh kubus) secara otomatis setelah sesuai!
                            if idx_s < step_total:
                                next_gerak = list_gerakan[idx_s]
                                if found_slot_idx != -1:
                                    next_gerak["nama"] = "taruh kubus"
                                    next_gerak["limit_val"] = float(found_slot_idx + 1)
                                    next_gerak["keterangan"] = f"{dest_slot} ({target_color} di S{found_slot_idx+1})"
                                    self.active_step_info["keterangan"] = f"Cocok! Kubus {target_color} ada di Storage S{found_slot_idx+1} -> Taruh di {dest_slot}"
                                else:
                                    next_gerak["nama"] = "delay"
                                    next_gerak["limit_type"] = "Waktu (s)"
                                    next_gerak["limit_val"] = 0.1
                                    if target_color == "EMPTY":
                                        next_gerak["keterangan"] = f"Dilewati ({dest_slot} Kosong / Tidak Butuh Kubus)"
                                        self.active_step_info["keterangan"] = f"Dilewati ({dest_slot} Kosong / Tidak Butuh Kubus)"
                                    else:
                                        next_gerak["keterangan"] = f"Dilewati (Tidak Ada Kubus {target_color} di Storage)"
                                        self.active_step_info["keterangan"] = f"Dilewati (Tidak Ada Kubus {target_color} di Storage)"
                                    
                                if self.gui_app:
                                    self.gui_app.update_detail_view(nama_kombinasi)
                                    
                            self.active_step_info["current_val"] = 1.0
                            time.sleep(0.15)
                            continue
    
                        # ---- Apakah Full? Command ----
                        if "apakah full" in nama_lower or "apakah_full" in nama_lower or "full?" in nama_lower:
                            self.active_step_info["limit_type"] = "Cek Full/Target"
                            self.active_step_info["limit_val"] = 8.0
                            self.active_step_info["current_val"] = float(self.storage_count)
                            
                            # 1. Cek secara fisik (kapasitas 8)
                            is_physically_full = (self.storage_count >= 8)
                            
                            # 2. Cek komparasi target kebutuhan Almari vs isi storage saat ini
                            needed_counts = {"RED": 0, "GREEN": 0, "BLUE": 0}
                            for slot, color in self.target_memory.items():
                                if color in needed_counts:
                                    needed_counts[color] += 1
                                    
                            total_needed = sum(needed_counts.values())
                            
                            stored_counts = {"RED": 0, "GREEN": 0, "BLUE": 0}
                            for code in self.storage_colors:
                                if code == "R": stored_counts["RED"] += 1
                                elif code == "G": stored_counts["GREEN"] += 1
                                elif code == "B": stored_counts["BLUE"] += 1
                                
                            is_target_fulfilled = False
                            if total_needed > 0:
                                is_target_fulfilled = (
                                    stored_counts["RED"] >= needed_counts["RED"] and
                                    stored_counts["GREEN"] >= needed_counts["GREEN"] and
                                    stored_counts["BLUE"] >= needed_counts["BLUE"]
                                )
                                
                            is_full_or_fulfilled = is_physically_full or is_target_fulfilled
                            
                            if is_full_or_fulfilled:
                                target_u_idx = 3 # Default Urutan #4 ("taruh ke almari")
                                desc = str(gerak.get("keterangan", "")).strip()
                                if desc:
                                    if desc.isdigit():
                                        target_u_idx = max(0, int(desc) - 1)
                                    else:
                                        for u_i, u_k in enumerate(urutan_keys):
                                            if desc.lower() in u_k.lower():
                                                target_u_idx = u_i
                                                break
                                
                                self.jump_target_u_idx = target_u_idx
                                target_u_name = urutan_keys[target_u_idx] if target_u_idx < len(urutan_keys) else "Taruh ke Almari"
                                
                                reason = "Storage Penuh (8)" if is_physically_full else "Target Terpenuhi"
                                self.active_step_info["keterangan"] = f"{reason}! Lompat ke Urutan #{target_u_idx+1} ({target_u_name})"
                                time.sleep(0.15)
                                break
                            else:
                                self.active_step_info["keterangan"] = f"Target Belum Cukup (Butuh: {total_needed}, Ada: {self.storage_count})"
                                self.active_step_info["current_val"] = float(self.storage_count)
                                time.sleep(0.15)
                                continue
    
                        # ---- Taruh Kubus Command ----
                        if "taruh kubus" in nama_lower or "taruh_kubus" in nama_lower or "drop" in nama_lower:
                            self.active_step_info["limit_type"] = "Taruh Kubus"
                            
                            # Cek slot_idx dari limit_val (1-8 -> 0-7)
                            slot_idx = int(float(self.active_step_info.get("limit_val", 1))) - 1
                            slot_idx = max(0, min(7, slot_idx))
                            
                            # Keterangan misal "A1 S3 (RED di S2)" atau "RED"
                            ket_str = str(gerak.get("keterangan", "")).upper()
                            target_code = None
                            if "RED" in ket_str or "MERAH" in ket_str: target_code = "R"
                            elif "GREEN" in ket_str or "HIJAU" in ket_str: target_code = "G"
                            elif "BLUE" in ket_str or "BIRU" in ket_str: target_code = "B"
                            
                            # Cocokan 1 per 1 warna kubus di storage!
                            if target_code and target_code in self.storage_colors:
                                slot_idx = self.storage_colors.index(target_code)
                            elif self.storage_colors[slot_idx] == "-" and self.storage_count > 0:
                                for i_st, c_code in enumerate(self.storage_colors):
                                    if c_code != "-":
                                        slot_idx = i_st
                                        break
                            
                            self.active_step_info["current_val"] = 0.0
                            self.send_command(f"TARUH_KUBUS {slot_idx}")
    
                            # Tunggu drop sequence MULAI di simulator (max 3 detik)
                            wait_start = time.time()
                            while self.running_sequence and not self.robot_dropping:
                                time.sleep(0.05)
                                if time.time() - wait_start > 3.0:
                                    break
    
                            # Tunggu drop sequence SELESAI di simulator (max 15 detik)
                            wait_start = time.time()
                            while self.running_sequence and self.robot_dropping:
                                time.sleep(0.05)
                                elapsed = time.time() - wait_start
                                self.active_step_info["current_val"] = min(1.0, elapsed / 5.0)
                                if elapsed > 15.0:
                                    break
    
                            self.active_step_info["current_val"] = 1.0
                            time.sleep(0.15)
                            continue
    
    
    
                        # ---- Rotasi (menuju sudut heading tertentu via NAV) ----
                        if (nama_lower.startswith("rotasi") or
                                nama_lower.startswith("putar") or
                                "rotasi" in nama_lower):
                            target_w = float(gerak["vw"]) if gerak.get("vw") is not None else 0.0
                            target_w = target_w % 360.0
    
                            curr_x = self.robot_pos["x"]
                            curr_y = self.robot_pos["y"]
    
                            self.active_step_info["limit_type"] = "Rotasi (°)"
                            self.active_step_info["limit_val"] = target_w
                            self.active_step_info["current_val"] = math.degrees(-self.robot_pos["angle"]) % 360.0
    
                            # Kirim perintah NAV ke posisi saat ini dengan target heading target_w
                            self.send_command(f"NAV {curr_x} {curr_y} {target_w}")
    
                            # Tunggu navigasi MULAI (max 2 detik)
                            wait_start = time.time()
                            while self.running_sequence and not self.robot_navigating:
                                time.sleep(0.05)
                                if time.time() - wait_start > 2.0:
                                    break
    
                            # Tunggu navigasi SELESAI (max 15 detik)
                            start_time = time.time()
                            while self.running_sequence and self.robot_navigating:
                                time.sleep(0.05)
                                # Update sisa selisih sudut heading
                                curr_deg = math.degrees(-self.robot_pos["angle"]) % 360.0
                                self.active_step_info["current_val"] = curr_deg
    
                                if time.time() - start_time > 15.0:
                                    break
    
                            self.send_command("CANCEL_NAV")
                            time.sleep(0.15)
                            continue
    
                        # Menentukan command pergerakan (bisa VEL biasa atau BALANCE)
                        if "balance depan kiri" in nama_lower or "balance_depan_kiri" in nama_lower:
                            cmd_prefix = "BALANCE_DEPAN_KIRI"
                        elif "balance depan" in nama_lower or "balance_depan" in nama_lower:
                            cmd_prefix = "BALANCE_DEPAN"
                        elif "balance kiri" in nama_lower or "balance_kiri" in nama_lower:
                            cmd_prefix = "BALANCE_KIRI"
                        elif "pwm" in nama_lower:
                            cmd_prefix = "VEL_LOCAL"
                        else:
                            cmd_prefix = "VEL"
                        is_find_coord  = (nama_lower.startswith("find coordinate") or
                                          nama_lower.startswith("find_coordinate"))
                        is_global_odom = (nama_lower.startswith("global odometry") or
                                          nama_lower.startswith("global_odometry"))
                        is_local_odom  = (nama_lower.startswith("local odometry") or
                                          nama_lower.startswith("local_odometry"))
                        is_plain_odom  = nama_lower.startswith("odometry")
    
                        # ---- Find Coordinate (navigasi A*) ----
                        if is_find_coord:
                            target_x = float(gerak["vx"]) if gerak["vx"] is not None else 0.0
                            target_y = float(gerak["vy"]) if gerak["vy"] is not None else 0.0
    
                            self.active_step_info["limit_type"] = "Navigasi A*"
                            self.active_step_info["limit_val"] = math.hypot(target_x, target_y)
                            self.active_step_info["current_val"] = 9999.0
    
                            raw_w = gerak.get("vw")
                            if raw_w is not None and str(raw_w).strip() != "":
                                target_w = float(raw_w)
                                self.send_command(f"NAV {target_x} {target_y} {target_w}")
                            else:
                                self.send_command(f"NAV {target_x} {target_y}")
    
                            # Tunggu navigasi MULAI (max 2 detik)
                            wait_start = time.time()
                            while self.running_sequence and not self.robot_navigating:
                                time.sleep(0.05)
                                if time.time() - wait_start > 2.0:
                                    break
    
                            # Tunggu navigasi SELESAI (max 30 detik)
                            start_time = time.time()
                            while self.running_sequence and self.robot_navigating:
                                time.sleep(0.05)
                                # Update sisa jarak navigasi
                                dx = target_x - self.robot_pos["x"]
                                dy = target_y - self.robot_pos["y"]
                                dist = math.hypot(dx, dy)
                                self.active_step_info["current_val"] = dist
    
                                if time.time() - start_time > 30.0:
                                    break
    
                            self.send_command("CANCEL_NAV")
                            time.sleep(0.15)
                            continue
    
                        # ---- Odometry (global / local / plain) ----
                        if is_global_odom or is_local_odom or is_plain_odom:
                            if is_global_odom:
                                tg_x = float(gerak["vx"]) if gerak["vx"] is not None else 0.0
                                tg_y = float(gerak["vy"]) if gerak["vy"] is not None else 0.0
                                tg_w = float(gerak["vw"]) if gerak["vw"] is not None else 0.0
                                cur_w = math.degrees(-self.robot_pos["angle"]) % 360.0
                                delta_w = (tg_w - cur_w + 180) % 360 - 180
                                tx = tg_x - self.robot_pos["x"]
                                ty = tg_y - self.robot_pos["y"]
                                tw = delta_w
                                self.active_step_info["target_x_pyg"] = tg_x
                                self.active_step_info["target_y_pyg"] = tg_y
                            else:
                                tx = float(gerak["vx"]) if gerak["vx"] is not None else 0.0
                                ty = float(gerak["vy"]) if gerak["vy"] is not None else 0.0
                                tw = float(gerak["vw"]) if gerak["vw"] is not None else 0.0
                                self.active_step_info["target_x_pyg"] = self.robot_pos["x"] + tx
                                self.active_step_info["target_y_pyg"] = self.robot_pos["y"] + ty
    
                            d_trans = math.hypot(tx, ty)
                            d_rot   = abs(tw)
                            T       = max(0.05, max(d_trans / 800.0 if d_trans > 0 else 0,
                                                   d_rot   / 180.0 if d_rot   > 0 else 0))
    
                            send_vx = (tx / T) / 40.0
                            send_vy = (ty / T) / 40.0
                            send_vw = (tw / T) / 18.0
                            limit_type = "Odometry"
                            limit_val  = d_trans
                            self.active_step_info["odom_start_time"] = time.time()
    
                        else:
                            send_vx    = float(gerak["vx"]) if gerak["vx"] is not None else 0.0
                            send_vy    = float(gerak["vy"]) if gerak["vy"] is not None else 0.0
                            send_vw    = float(gerak["vw"]) if gerak["vw"] is not None else 0.0
                            limit_type = gerak["limit_type"]
                            limit_val  = float(gerak["limit_val"])
    
                        self.active_step_info["limit_type"] = limit_type
                        self.active_step_info["limit_val"] = limit_val
                        self.active_step_info["current_val"] = 0.0
    
                        # Kirim perintah (VEL atau BALANCE) dan tunggu sesuai limit
                        self.send_command(f"{cmd_prefix} {send_vx} {send_vy} {send_vw}")
    
                        start_x     = self.robot_pos["x"]
                        start_y     = self.robot_pos["y"]
                        start_angle = self.robot_pos["angle"]
                        start_time  = time.time()
    
                        accumulated_angle = 0.0
                        last_angle = self.robot_pos["angle"]
                        last_loop_time = time.time()
    
                        self.line_latch = False  # Reset latch
                        while self.running_sequence:
                            time.sleep(0.01)
                            now = time.time()
                            dt = now - last_loop_time
                            last_loop_time = now
                            
                            if limit_type == "Odometry":
                                # Gunakan perbedaan koordinat fisik simulator agar Temp akurat
                                self.active_step_info["temp_x"] = self.robot_pos["y"] - start_y
                                self.active_step_info["temp_y"] = self.robot_pos["x"] - start_x
                                # Angle Pygame dibalik (-angle), jadi kita invert untuk temp_w
                                cur_w = math.degrees(-self.robot_pos["angle"]) % 360.0
                                sw = math.degrees(-start_angle) % 360.0
                                dw = (cur_w - sw + 180) % 360 - 180
                                self.active_step_info["temp_w"] = dw
                            else:
                                self.active_step_info["temp_x"] += send_vx * dt * 40.0
                                self.active_step_info["temp_y"] += send_vy * dt * 40.0
                                self.active_step_info["temp_w"] += send_vw * dt * 18.0
    
                            if limit_type == "Odometry":
                                t_x = self.active_step_info["target_x_pyg"]
                                t_y = self.active_step_info["target_y_pyg"]
                                dist_to_target = math.hypot(t_x - self.robot_pos["x"], t_y - self.robot_pos["y"])
                                self.active_step_info["current_val"] = limit_val - dist_to_target
                                
                                # Cek jarak target (toleransi 10 mm)
                                if dist_to_target <= 10.0:
                                    break
                                
                                # Fallback timeout 7 detik jika tersangkut / menabrak dinding
                                if time.time() - self.active_step_info["odom_start_time"] > 7.0:
                                    break
    
                            elif limit_type == "Waktu (s)":
                                elapsed = time.time() - start_time
                                self.active_step_info["current_val"] = elapsed
                                if elapsed >= limit_val:
                                    break
                            elif limit_type in ("Jarak (px)", "Jarak (mm)"):
                                dist = math.hypot(self.active_step_info["temp_x"], self.active_step_info["temp_y"])
                                self.active_step_info["current_val"] = dist
                                if dist >= limit_val:
                                    break
                            elif limit_type == "Sudut (°)":
                                accumulated_angle = abs(self.active_step_info["temp_w"])
                                self.active_step_info["current_val"] = accumulated_angle
                                if accumulated_angle >= limit_val:
                                    break
                            elif limit_type == "Sensor Garis":
                                has_line = self.line_latch or (self.line_sensors["left"] == 1 or self.line_sensors["right"] == 1)
                                self.active_step_info["current_val"] = 1.0 if has_line else 0.0
                                if has_line:
                                    break
                            elif limit_type == "Sensor Jarak Depan (mm)":
                                dist_val = self.robot_front_dist
                                self.active_step_info["current_val"] = dist_val
                                if dist_val <= limit_val:
                                    break
                            elif limit_type == "Sensor Jarak Kiri (mm)":
                                dist_val = self.robot_left_dist
                                self.active_step_info["current_val"] = dist_val
                                if dist_val <= limit_val:
                                    break
    
                            self.send_command(f"{cmd_prefix} {send_vx} {send_vy} {send_vw}")
    
                        self.send_command("VEL 0 0 0")
                        time.sleep(0.1)
    
                        if is_local_odom:
                            self.send_command("RESET_ODOM")
                            time.sleep(0.1)

                if self.jump_target_u_idx is not None:
                    curr_u_idx = self.jump_target_u_idx
                    self.jump_target_u_idx = None
                    start_combo_idx = 0
                    start_step_idx = 0
                else:
                    curr_u_idx += 1
    
        finally:
            self.send_command("VEL 0 0 0")
            self.running_sequence = False
            self.active_step_info["status"] = "IDLE"
            self.active_step_info["kombinasi"] = "-"
            self.active_step_info["nama"] = "-"
            self.active_step_info["limit_type"] = "-"
            self.active_step_info["limit_val"] = 0.0
            self.active_step_info["current_val"] = 0.0
            self.active_step_info["q_idx"] = 0
            self.active_step_info["q_total"] = 0
            self.active_step_info["step_idx"] = 0
            self.active_step_info["step_total"] = 0
            if self.gui_app:
                self.gui_app.set_run_button_state("normal")

    def stop_execution(self):
        self.running_sequence = False
        self.active_step_info["status"] = "IDLE"
        self.active_step_info["kombinasi"] = "-"
        self.active_step_info["nama"] = "-"
        self.active_step_info["limit_type"] = "-"
        self.active_step_info["limit_val"] = 0.0
        self.active_step_info["current_val"] = 0.0
        self.active_step_info["q_idx"] = 0
        self.active_step_info["q_total"] = 0
        self.active_step_info["step_idx"] = 0
        self.active_step_info["step_total"] = 0
        self.send_command("VEL 0 0 0")
        if self.gui_app:
            self.gui_app.set_status_text("Status: Sekuens Dihentikan. Robot berhenti.")

    def reset_robot_position(self):
        self.running_sequence = False
        self.send_command("RESET")
        self.active_step_info["status"] = "IDLE"
        self.active_step_info["kombinasi"] = "-"
        self.active_step_info["nama"] = "-"
        self.active_step_info["limit_type"] = "-"
        self.active_step_info["limit_val"] = 0.0
        self.active_step_info["current_val"] = 0.0
        self.active_step_info["q_idx"] = 0
        self.active_step_info["q_total"] = 0
        self.active_step_info["step_idx"] = 0
        self.active_step_info["step_total"] = 0
        self.robot_pos = {"x": 0.0, "y": 0.0, "angle": 0.0, "dist": 0.0}
        if self.gui_app:
            self.gui_app.set_status_text("Status: Robot di-reset ke HOME.")
