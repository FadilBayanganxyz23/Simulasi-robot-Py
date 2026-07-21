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
                    if len(parts) >= 4 and parts[0] == "STATUS":
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
        """Muat preset dari presets.json; gunakan default jika gagal."""
        if os.path.exists("presets.json"):
            try:
                with open("presets.json", "r", encoding="utf-8") as f:
                    self.kombinasi_gerakan = json.load(f)
                return
            except Exception:
                pass
        self.kombinasi_gerakan = dict(self.default_presets)
        self.save_presets()

    def save_presets(self):
        """Simpan preset ke presets.json."""
        try:
            with open("presets.json", "w", encoding="utf-8") as f:
                json.dump(self.kombinasi_gerakan, f, indent=4)
        except Exception as e:
            if self.gui_app:
                self.gui_app.show_error(f"Gagal menyimpan preset: {e}")

    # ------------------------------------------------------------------
    # Eksekusi Sekuens
    # ------------------------------------------------------------------
    def execute_sequence(self, macro_sequence_queue, start_combo_idx=0, start_step_idx=0):
        """Jalankan seluruh antrean kombinasi secara berurutan dalam thread terpisah."""
        self.running_sequence = True
        self.active_step_info["status"] = "RUNNING"
        if self.gui_app:
            self.gui_app.set_run_button_state("disabled")

        q_total = len(macro_sequence_queue)

        try:
            for idx_k, nama_kombinasi in enumerate(macro_sequence_queue, 1):
                if not self.running_sequence:
                    break
                if idx_k < start_combo_idx + 1:
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
                    if not self.running_sequence:
                        break
                    # Lewati langkah sebelum start_step_idx hanya pada kombinasi awal start_combo_idx
                    if idx_k == start_combo_idx + 1 and idx_s < start_step_idx + 1:
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

                    # ---- Taruh Kubus Command ----
                    if "taruh kubus" in nama_lower or "taruh_kubus" in nama_lower or "drop" in nama_lower:
                        self.active_step_info["limit_type"] = "Taruh Kubus"
                        # slot 1-8 -> idx 0-7
                        slot_idx = int(float(self.active_step_info.get("limit_val", 1))) - 1
                        slot_idx = max(0, min(7, slot_idx))
                        
                        self.active_step_info["current_val"] = 0.0
                        self.send_command(f"TARUH_KUBUS {slot_idx}")

                        # Tunggu drop sequence MULAI di simulator (max 1 detik)
                        wait_start = time.time()
                        while self.running_sequence and not self.robot_dropping:
                            time.sleep(0.05)
                            if time.time() - wait_start > 1.0:
                                break

                        # Tunggu drop sequence SELESAI di simulator (max 10 detik)
                        wait_start = time.time()
                        while self.running_sequence and self.robot_dropping:
                            time.sleep(0.05)
                            elapsed = time.time() - wait_start
                            self.active_step_info["current_val"] = min(1.0, elapsed / 5.0)
                            if elapsed > 10.0:
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
                        target_x = float(gerak["vy"])   # Geser Kanan/Kiri
                        target_y = float(gerak["vx"])   # Maju/Mundur

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
                            tg_x = float(gerak["vy"]) if gerak["vy"] is not None else 0.0
                            tg_y = float(gerak["vx"]) if gerak["vx"] is not None else 0.0
                            tg_w = float(gerak["vw"]) if gerak["vw"] is not None else 0.0
                            cur_w = math.degrees(-self.robot_pos["angle"]) % 360.0
                            delta_w = (tg_w - cur_w + 180) % 360 - 180
                            tx = tg_y - self.robot_pos["y"]
                            ty = tg_x - self.robot_pos["x"]
                            tw = delta_w
                        else:
                            tx = float(gerak["vx"]) if gerak["vx"] is not None else 0.0
                            ty = float(gerak["vy"]) if gerak["vy"] is not None else 0.0
                            tw = float(gerak["vw"]) if gerak["vw"] is not None else 0.0

                        d_trans = math.hypot(tx, ty)
                        d_rot   = abs(tw)
                        T       = max(0.05, max(d_trans / 800.0 if d_trans > 0 else 0,
                                               d_rot   / 180.0 if d_rot   > 0 else 0))

                        send_vx = (tx / T) / 40.0
                        send_vy = (ty / T) / 40.0
                        send_vw = (tw / T) / 18.0
                        limit_type = "Waktu (s)"
                        limit_val  = T

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
                        
                        self.active_step_info["temp_x"] += send_vx * dt * 40.0
                        self.active_step_info["temp_y"] += send_vy * dt * 40.0
                        self.active_step_info["temp_w"] += send_vw * dt * 18.0

                        if limit_type == "Waktu (s)":
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
