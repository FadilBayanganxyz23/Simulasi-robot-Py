"""
simul_jalan.py
==============
Entry point simulator Pygame.

Hanya berisi:
- Inisialisasi Pygame + server socket
- Main game loop:
    1. Terima koneksi & perintah dari GUI client (socket)
    2. Update navigasi otomatis (step_navigation)
    3. Update robot (robot.update)
    4. Kirim status ke GUI (socket)
    5. Render frame

Semua logika layout, robot, dan navigasi ada di folder simulator/.
"""

import pygame
import math
import sys
import os
import socket

# Pastikan window terbuka di tengah layar
os.environ['SDL_VIDEO_CENTERED'] = '1'
pygame.init()

screen_w = 1280
screen_h = 720
screen   = pygame.display.set_mode((screen_w, screen_h))
pygame.display.set_caption("Simulasi Robot Omni 12-Sisi - Lapangan 4x2m (Millimeter Exact)")
clock = pygame.time.Clock()

# ---------------------------------------------------------------------------
# Import modul simulator (setelah pygame.init())
# ---------------------------------------------------------------------------
from simulator.field_layout import (
    WHITE, BLACK, RED, GREEN, GREY, YELLOW,
    FIELD_OFFSET_X, FIELD_OFFSET_Y,
    HOME_X, HOME_Y,
    build_field_surfaces,
)
from simulator.robot import SimRobot
from simulator.navigation import (
    init_obstacle_grid,
    make_nav_state, start_navigation, cancel_navigation, step_navigation,
)

# ---------------------------------------------------------------------------
# Bangun lapangan
# ---------------------------------------------------------------------------
raw_lapangan, scaled_lapangan, SCALE, offset_x = build_field_surfaces(screen_w, screen_h)

# ---------------------------------------------------------------------------
# Inisialisasi Robot & Grid Rintangan
# ---------------------------------------------------------------------------
robot = SimRobot()
init_obstacle_grid(robot, raw_lapangan)

# ---------------------------------------------------------------------------
# Font & State Awal
# ---------------------------------------------------------------------------
font_title = pygame.font.SysFont("Arial", 28, bold=True)
font_text  = pygame.font.SysFont("Arial", 18)
show_help  = True
running    = True

# Odometri origin (diperbarui saat RESET_ODOM)
origin_x     = HOME_X
origin_y     = HOME_Y
origin_angle = -math.pi / 2

# Mode kontrol: "STATE_MACHINE" (perintah dari GUI) atau "MANUAL" (keyboard di simulator)
control_mode = "STATE_MACHINE"

# Kecepatan perintah manual dari GUI
cmd_vx, cmd_vy, cmd_vw = 0.0, 0.0, 0.0
use_ext_control = False

# State navigasi otomatis
nav_state = make_nav_state()

# State Coretan & Label lapangan
scribbles = []
labels = []
active_tool = "TELEPORT"  # "TELEPORT", "DRAW", "LABEL", "ERASE"
is_drawing = False
current_stroke = []

# ---------------------------------------------------------------------------
# State Machine: BALANCE_BG_LEFT
# ---------------------------------------------------------------------------
# Konsep:
#   Fase 1 (SIDE): Robot bergerak ke samping (ke arah tembok samping terdekat)
#                  sampai sensor samping mencapai jarak TARGET_DIST_MM dari tembok.
#                  Jika jarak sensor < TARGET_DIST_MM -> gerak menjauh (PWM balik)
#                  Jika jarak sensor > TARGET_DIST_MM -> gerak mendekat
#
#   Fase 2 (BACK): Robot bergerak ke belakang (ke arah tembok belakang terdekat)
#                  sampai sensor belakang mencapai TARGET_DIST_MM dari tembok.
#                  Jika jarak sensor < TARGET_DIST_MM -> gerak menjauh (maju)
#                  Jika jarak sensor > TARGET_DIST_MM -> gerak mendekat (mundur)
#
#   Selesai: Kalibrasi odometri ke posisi saat ini, heading dibulatkan ke 90 derajat.
#
# Catatan konvensi ext_vx/vy di robot.update():
#   ext_vx = gerak maju/mundur (sumbu Y global Pygame, positif = maju)
#   ext_vy = gerak geser kiri/kanan (sumbu X global Pygame, positif = kanan)
#
# Jarak sensor = jarak dari dinding ke sisi luar robot = jarak_pusat - ROBOT_RADIUS
#

TARGET_DIST_MM     = 50     # mm dari sisi robot ke tembok (5 cm)
BALANCE_KP         = 1.4    # Proportional gain: speed = KP * error
                            # KP=1.5 → critical (1 langkah pas), <1.5 → smooth tanpa overshoot
BALANCE_MAX_SPEED  = 80.0   # kecepatan maksimum (mm/s)
BALANCE_MIN_SPEED  = 6.0    # kecepatan minimum agar tidak berhenti sebelum sampai
BALANCE_TOLERANCE  = 4.0    # toleransi error (mm) — dianggap selesai

balance_state = {
    "active":    False,
    "phase":     None,     # "SIDE" atau "BACK"
    "wall_side": None,     # "LEFT" atau "RIGHT" (dinding samping terdekat)
    "wall_back": None,     # "TOP"  atau "BOTTOM" (dinding belakang terdekat)
    "target_x":  0.0,      # target posisi X pusat robot (fase SIDE)
    "target_y":  0.0,      # target posisi Y pusat robot (fase BACK)
}


def start_balance(robot, bst, mode):
    """
    Inisialisasi state machine Balance.
    mode: "BALANCE_DEPAN", "BALANCE_KIRI", "BALANCE_DEPAN_KIRI"
    """
    bst["active"] = True
    bst["mode"]   = mode
    bst["phase"]  = None

def update_balance(robot, bst, raw_lapangan):
    """
    Jalankan satu frame logic balance berbasis sensor IR & US.
    Kembali: (ext_vx, ext_vy, ext_vw, done)
    """
    if not bst["active"]:
        return 0.0, 0.0, 0.0, False

    (dist_us_f_l, dist_us_f_r, dist_ir_f, dist_ir_l_f, dist_ir_l_b) = robot.get_sensor_distances(raw_lapangan)

    a = robot.angle
    cos_a = math.cos(a)
    sin_a = math.sin(a)

    def prop_val(err, kp, max_val, min_val=0):
        val = kp * err
        if abs(val) < min_val:
            return 0.0
        return max(-max_val, min(max_val, val))

    mode = bst.get("mode")
    vx_local, vy_local, vw = 0.0, 0.0, 0.0
    is_done = False

    if mode == "BALANCE_DEPAN":
        # Maju/Mundur
        avg_dist = (dist_us_f_l + dist_us_f_r) / 2.0
        err_dist = avg_dist - TARGET_DIST_MM
        vx_local = prop_val(err_dist, BALANCE_KP, BALANCE_MAX_SPEED, BALANCE_MIN_SPEED)
        
        # Rotasi
        err_rot = dist_us_f_l - dist_us_f_r
        # Jika kiri lebih jauh (err_rot > 0), putar ke kiri (vw positif)
        # Jika kanan lebih jauh (err_rot < 0), putar ke kanan (vw negatif)
        vw = prop_val(err_rot, 0.5, 45.0, 0.5)

        if abs(err_dist) <= BALANCE_TOLERANCE and abs(err_rot) <= 2.0:
            is_done = True

    elif mode == "BALANCE_KIRI":
        # Kiri/Kanan
        avg_dist = (dist_ir_l_f + dist_ir_l_b) / 2.0
        err_dist = avg_dist - TARGET_DIST_MM
        # Jika err_dist > 0 (terlalu jauh), gerak kiri (vy_local negatif)
        vy_local = -prop_val(err_dist, BALANCE_KP, BALANCE_MAX_SPEED, BALANCE_MIN_SPEED)
        
        # Rotasi
        err_rot = dist_ir_l_b - dist_ir_l_f
        # Jika belakang lebih jauh (err_rot > 0), berarti robot serong kiri, putar ke kiri (+vw) 
        vw = prop_val(err_rot, 0.5, 45.0, 0.5)

        if abs(err_dist) <= BALANCE_TOLERANCE and abs(err_rot) <= 2.0:
            is_done = True

    elif mode == "BALANCE_DEPAN_KIRI":
        # Maju/Mundur
        avg_dist_f = (dist_us_f_l + dist_us_f_r) / 2.0
        err_dist_f = avg_dist_f - TARGET_DIST_MM
        vx_local = prop_val(err_dist_f, BALANCE_KP, BALANCE_MAX_SPEED, BALANCE_MIN_SPEED)
        
        # Kiri/Kanan
        avg_dist_l = (dist_ir_l_f + dist_ir_l_b) / 2.0
        err_dist_l = avg_dist_l - TARGET_DIST_MM
        vy_local = -prop_val(err_dist_l, BALANCE_KP, BALANCE_MAX_SPEED, BALANCE_MIN_SPEED)
        
        # Rotasi menggunakan sensor depan (US)
        err_rot = dist_us_f_l - dist_us_f_r
        vw = prop_val(err_rot, 0.5, 45.0, 0.5)

        if abs(err_dist_f) <= BALANCE_TOLERANCE and abs(err_dist_l) <= BALANCE_TOLERANCE and abs(err_rot) <= 2.0:
            is_done = True

    if is_done:
        bst["active"] = False
        return 0.0, 0.0, 0.0, True

    return vx_local, vy_local, vw, False


# ---------------------------------------------------------------------------
# Server Socket (127.0.0.1:5005)
# ---------------------------------------------------------------------------
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_socket.bind(('127.0.0.1', 5005))
server_socket.listen(1)
server_socket.setblocking(False)

client_socket = None
client_buffer = ""
is_vel_local = False

# State machine Ambil Kubus (Approach stand terdekat + Grab)
grab_sequence_state = {"active": False, "phase": "NONE", "_stuck_count": 0}

# State machine Taruh Kubus (Approach stand terdekat + Drop)
drop_sequence_state = {"active": False, "phase": "NONE", "slot": 0, "_stuck_count": 0}

# Inisialisasi 15 Stand / Slider Box (dengan label meja P1-P5)
stands = []
ox_st = FIELD_OFFSET_X
oy_st = FIELD_OFFSET_Y

# 1. Horizontal Group 1: ox+750, y in [280, 430, 580] (P3)
y_labels_p3 = {280: "P3 S1", 430: "P3 S2", 580: "P3 S3"}
for y in [280, 430, 580]:
    stands.append({
        "type": "H", "x": ox_st + 750, "y": oy_st + y,
        "rect": pygame.Rect(ox_st + 750, oy_st + y - 40, 250, 80),
        "color": None,
        "label": y_labels_p3[y]
    })

# 2. Horizontal Group 2: ox+1720, y in [280, 430, 580] (P5)
y_labels_p5 = {280: "P5 S1", 430: "P5 S2", 580: "P5 S3"}
for y in [280, 430, 580]:
    stands.append({
        "type": "H", "x": ox_st + 1720, "y": oy_st + y,
        "rect": pygame.Rect(ox_st + 1720, oy_st + y - 40, 250, 80),
        "color": None,
        "label": y_labels_p5[y]
    })

# 3. Horizontal Group 3: ox+500, y in [1330, 1480, 1630] (P4)
y_labels_p4 = {1330: "P4 S3", 1480: "P4 S2", 1630: "P4 S1"}
for y in [1330, 1480, 1630]:
    stands.append({
        "type": "H", "x": ox_st + 500, "y": oy_st + y,
        "rect": pygame.Rect(ox_st + 500, oy_st + y - 40, 250, 80),
        "color": None,
        "label": y_labels_p4[y]
    })

# 4. Horizontal Group 4: ox+30, y in [3420, 3570, 3720] (P2)
y_labels_p2 = {3420: "P2 S3", 3570: "P2 S2", 3720: "P2 S1"}
for y in [3420, 3570, 3720]:
    stands.append({
        "type": "H", "x": ox_st + 30, "y": oy_st + y,
        "rect": pygame.Rect(ox_st + 30, oy_st + y - 40, 250, 80),
        "color": None,
        "label": y_labels_p2[y]
    })

# 5. Vertical Group: x in [1100, 1400, 1700], y = oy + 3760 (P1)
x_labels_p1 = {1100: "P1 S1", 1400: "P1 S2", 1700: "P1 S3"}
for x in [1100, 1400, 1700]:
    stands.append({
        "type": "V", "x": ox_st + x, "y": oy_st + 3760,
        "rect": pygame.Rect(ox_st + x - 40, oy_st + 3760, 80, 210),
        "color": None,
        "label": x_labels_p1[x]
    })

# ---------------------------------------------------------------------------
# Main Loop
# ---------------------------------------------------------------------------
while running:
    clock.tick(60)

    # 1. Terima koneksi client baru (non-blocking)
    try:
        conn, addr = server_socket.accept()
        conn.setblocking(False)
        client_socket = conn
        client_buffer = ""
    except BlockingIOError:
        pass

    # 2. Baca perintah dari client
    if client_socket:
        try:
            data = client_socket.recv(1024)
            if data:
                client_buffer += data.decode('utf-8')
                while "\n" in client_buffer:
                    line, client_buffer = client_buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()

                    def safe_float(s, default=0.0):
                        """Konversi string ke float, kembalikan default jika None/invalid."""
                        try:
                            if s is None or str(s).strip().lower() == "none":
                                return default
                            return float(s)
                        except (ValueError, TypeError):
                            return default

                    if control_mode == "MANUAL" and parts[0] in ("VEL", "NAV", "BALANCE_DEPAN", "BALANCE_KIRI", "BALANCE_DEPAN_KIRI"):
                        continue

                    if parts[0] == "VEL" and len(parts) >= 4:
                        cmd_vx = safe_float(parts[1])
                        cmd_vy = safe_float(parts[2])
                        cmd_vw = safe_float(parts[3])
                        use_ext_control = True
                        is_vel_local = False
                        balance_state["active"] = False
                        cancel_navigation(nav_state)   # manual override
                    elif parts[0] == "VEL_LOCAL" and len(parts) >= 4:
                        cmd_vx = safe_float(parts[1])
                        cmd_vy = safe_float(parts[2])
                        cmd_vw = safe_float(parts[3])
                        use_ext_control = True
                        is_vel_local = True
                        balance_state["active"] = False
                        cancel_navigation(nav_state)   # manual override

                    elif parts[0] == "NAV" and len(parts) >= 3:
                        target_x = safe_float(parts[1])
                        target_y = safe_float(parts[2])
                        target_w = safe_float(parts[3]) if len(parts) >= 4 else None
                        # Gunakan origin_x/origin_y yang dinamis (bukan HOME_X/HOME_Y)
                        # Sehingga NAV 0 0 = titik origin saat ini, bukan HOME
                        start_navigation(nav_state, robot, origin_x, origin_y,
                                         target_x, target_y, target_w)
                        balance_state["active"] = False

                    elif parts[0] == "CANCEL_NAV":
                        cancel_navigation(nav_state)
                        balance_state["active"] = False
                        cmd_vx, cmd_vy, cmd_vw = 0.0, 0.0, 0.0
                        use_ext_control = False

                    elif parts[0] == "RESET":
                        robot.orig_x     = HOME_X
                        robot.orig_y     = HOME_Y
                        robot.angle      = -math.pi / 2
                        robot.total_dist = 0.0
                        origin_x         = HOME_X
                        origin_y         = HOME_Y
                        origin_angle     = -math.pi / 2
                        cmd_vx, cmd_vy, cmd_vw = 0.0, 0.0, 0.0
                        use_ext_control = False
                        is_vel_local = False
                        balance_state["active"] = False
                        cancel_navigation(nav_state)
                        robot.storage = [None] * 8
                        robot.carousel_angle = 0.0
                        robot.target_carousel_angle = 0.0
                        robot.last_grabbed_color = None
                        grab_sequence_state["active"] = False
                        drop_sequence_state["active"] = False

                    elif parts[0] == "RESET_ODOM":
                        origin_x     = robot.orig_x
                        origin_y     = robot.orig_y
                        origin_angle = robot.angle
                        robot.total_dist = 0.0

                    elif parts[0] == "GRAB":
                        robot.start_grab()

                    elif parts[0] == "SET_STORAGE":
                        if len(parts) >= 2:
                            if parts[1] == "-":
                                robot.storage = [None] * 8
                            else:
                                colors_raw = parts[1].split(",")
                                robot.storage = [None] * 8
                                for i, c in enumerate(colors_raw):
                                    if i < 8:
                                        if c == "R": robot.storage[i] = "RED"
                                        elif c == "G": robot.storage[i] = "GREEN"
                                        elif c == "B": robot.storage[i] = "BLUE"
                    
                    elif parts[0] == "RESET_STORAGE":
                        robot.storage = [None] * 8
                        robot.carousel_angle = 0.0
                        robot.target_carousel_angle = 0.0
                        robot.last_grabbed_color = None
                    
                    elif parts[0] == "AMBIL_KUBUS":
                        grab_sequence_state["active"] = True
                        grab_sequence_state["phase"] = "APPROACH"
                        grab_sequence_state["_stuck_count"] = 0
                        cancel_navigation(nav_state)
                        balance_state["active"] = False
                        drop_sequence_state["active"] = False

                    elif parts[0] == "TARUH_KUBUS":
                        if len(parts) >= 2:
                            slot_idx = int(parts[1])
                            drop_sequence_state["active"] = True
                            drop_sequence_state["phase"] = "APPROACH"
                            drop_sequence_state["_stuck_count"] = 0
                            drop_sequence_state["slot"] = slot_idx
                            cancel_navigation(nav_state)
                            balance_state["active"] = False
                            grab_sequence_state["active"] = False

                    elif parts[0] in ("BALANCE_DEPAN", "BALANCE_KIRI", "BALANCE_DEPAN_KIRI"):
                        cancel_navigation(nav_state)
                        use_ext_control = False
                        cmd_vx, cmd_vy, cmd_vw = 0.0, 0.0, 0.0
                        start_balance(robot, balance_state, parts[0])

            else:
                # Data kosong -> client disconnect
                client_socket.close()
                client_socket = None
                cmd_vx, cmd_vy, cmd_vw = 0.0, 0.0, 0.0
                use_ext_control = False
                is_vel_local = False
                balance_state["active"] = False

        except BlockingIOError:
            pass
        except (ConnectionResetError, BrokenPipeError):
            client_socket = None
            cmd_vx, cmd_vy, cmd_vw = 0.0, 0.0, 0.0
            use_ext_control = False
            is_vel_local = False
            balance_state["active"] = False

    # 3. Event Keyboard
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
            elif event.key == pygame.K_h:
                show_help = not show_help
            elif event.key == pygame.K_m:
                # Toggle mode kontrol
                if control_mode == "STATE_MACHINE":
                    control_mode = "MANUAL"
                    # Cancel any active autonomous movements
                    cancel_navigation(nav_state)
                    balance_state["active"] = False
                    cmd_vx, cmd_vy, cmd_vw = 0.0, 0.0, 0.0
                    use_ext_control = False
                else:
                    control_mode = "STATE_MACHINE"
            elif event.key == pygame.K_F1:
                active_tool = "TELEPORT"
            elif event.key == pygame.K_F2:
                active_tool = "DRAW"
            elif event.key == pygame.K_F3:
                active_tool = "LABEL"
            elif event.key == pygame.K_F4:
                active_tool = "ERASE"
            elif event.key == pygame.K_F5:
                scribbles.clear()
                labels.clear()
            elif event.key == pygame.K_g:
                robot.start_grab()
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:  # Left click
                mx, my = event.pos
                if mx >= offset_x:
                    orig_mx = (mx - offset_x) / SCALE
                    orig_my = my / SCALE

                    # Cek apakah klik mengenai salah satu stand (slider box)
                    clicked_stand = None
                    for s in stands:
                        if s["rect"].collidepoint(orig_mx, orig_my):
                            clicked_stand = s
                            break

                    if clicked_stand:
                        # Cycle color: None -> RED -> GREEN -> BLUE -> None
                        if clicked_stand["color"] is None:
                            clicked_stand["color"] = "RED"
                        elif clicked_stand["color"] == "RED":
                            clicked_stand["color"] = "GREEN"
                        elif clicked_stand["color"] == "GREEN":
                            clicked_stand["color"] = "BLUE"
                        else:
                            clicked_stand["color"] = None
                    else:
                        if active_tool == "TELEPORT":
                            if not robot.check_collision(int(orig_mx), int(orig_my), robot.angle, raw_lapangan):
                                robot.orig_x = int(orig_mx)
                                robot.orig_y = int(orig_my)
                        elif active_tool == "DRAW":
                            is_drawing = True
                            current_stroke = [(orig_mx, orig_my)]
                            scribbles.append(current_stroke)
                        elif active_tool == "LABEL":
                            import tkinter as tk
                            from tkinter import simpledialog
                            root = tk.Tk()
                            root.withdraw()
                            root.attributes("-topmost", True)
                            text = simpledialog.askstring("Beri Label", "Masukkan teks label:", parent=root)
                            root.destroy()
                            if text and text.strip():
                                labels.append({"x": orig_mx, "y": orig_my, "text": text.strip()})
                        elif active_tool == "ERASE":
                            # Hapus label dekat klik
                            labels = [lbl for lbl in labels if math.hypot(lbl["x"] - orig_mx, lbl["y"] - orig_my) > 30]
                            # Hapus stroke coretan dekat klik
                            new_scribbles = []
                            for stroke in scribbles:
                                keep = True
                                for pt in stroke:
                                    if math.hypot(pt[0] - orig_mx, pt[1] - orig_my) < 20:
                                        keep = False
                                        break
                                if keep:
                                    new_scribbles.append(stroke)
                            scribbles = new_scribbles

        elif event.type == pygame.MOUSEMOTION:
            if active_tool == "DRAW" and is_drawing:
                mx, my = event.pos
                if mx >= offset_x:
                    orig_mx = (mx - offset_x) / SCALE
                    orig_my = my / SCALE
                    if not current_stroke or math.hypot(current_stroke[-1][0] - orig_mx, current_stroke[-1][1] - orig_my) > 3:
                        current_stroke.append((orig_mx, orig_my))
            elif active_tool == "ERASE" and pygame.mouse.get_pressed()[0]:
                mx, my = event.pos
                if mx >= offset_x:
                    orig_mx = (mx - offset_x) / SCALE
                    orig_my = my / SCALE
                    labels = [lbl for lbl in labels if math.hypot(lbl["x"] - orig_mx, lbl["y"] - orig_my) > 30]
                    new_scribbles = []
                    for stroke in scribbles:
                        keep = True
                        for pt in stroke:
                            if math.hypot(pt[0] - orig_mx, pt[1] - orig_my) < 20:
                                keep = False
                                break
                        if keep:
                            new_scribbles.append(stroke)
                    scribbles = new_scribbles

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                is_drawing = False

    # 4. Hitung kecepatan frame ini
    nav_vx, nav_vy, nav_vw, nav_ext = step_navigation(robot, nav_state, origin_angle)

    keys = pygame.key.get_pressed()

    # Keyboard reset posisi
    if keys[pygame.K_r]:
        robot.orig_x     = HOME_X
        robot.orig_y     = HOME_Y
        robot.angle      = -math.pi / 2
        robot.total_dist = 0.0

    # --- Update balance state machine (jalankan satu frame) ---
    if control_mode == "MANUAL":
        robot.update(keys, raw_lapangan, stands=stands)
    elif grab_sequence_state["active"]:
        # Jalankan logic approach & grab
        fd_x = math.cos(robot.angle)
        fd_y = math.sin(robot.angle)
        
        if grab_sequence_state["phase"] == "APPROACH":
            # Hitung posisi ujung gripper saat fully extended
            gripper_tip_dist = robot.ROBOT_RADIUS + 35.0
            tip_x = robot.orig_x + gripper_tip_dist * fd_x
            tip_y = robot.orig_y + gripper_tip_dist * fd_y
            
            # Cari stand terdekat di depan robot (dalam jangkauan gripper)
            best_stand = None
            min_d = 999999.0
            for s in stands:
                if s["color"] is None:
                    continue  # Lewati stand kosong
                if s["type"] == "H":
                    cx = s["x"] + 125
                    cy = s["y"]
                else:
                    cx = s["x"]
                    cy = s["y"] + 105
                
                # Cek apakah stand ini berada di depan robot (dot product positif)
                to_stand_x = cx - robot.orig_x
                to_stand_y = cy - robot.orig_y
                dot = to_stand_x * fd_x + to_stand_y * fd_y
                if dot <= 0:
                    continue  # Stand di belakang robot, lewati
                
                d = math.hypot(tip_x - cx, tip_y - cy)
                if d < min_d:
                    min_d = d
                    best_stand = s
            
            if best_stand is None:
                # Tidak ada stand berisi di depan robot — langsung grab saja
                grab_sequence_state["phase"] = "GRABBING"
                robot.start_grab()
                robot.update(keys, raw_lapangan, 0.0, 0.0, 0.0, use_ext=True, is_local=True, stands=stands)
            else:
                # Jarak gripper tip ke stand center
                grab_range = 100.0  # mm — jarak maks gripper bisa meraih
                
                if min_d <= grab_range:
                    # Sudah dalam jangkauan — mulai mengambil
                    grab_sequence_state["phase"] = "GRABBING"
                    robot.start_grab()
                    robot.update(keys, raw_lapangan, 0.0, 0.0, 0.0, use_ext=True, is_local=True, stands=stands)
                else:
                    # Belum cukup dekat — maju ke arah stand
                    err = min_d - grab_range
                    kp = 0.15
                    vx_local = err * kp
                    vx_local = max(3.0, min(10.0, vx_local))
                    
                    old_x = robot.orig_x
                    old_y = robot.orig_y
                    robot.update(keys, raw_lapangan, vx_local, 0.0, 0.0, use_ext=True, is_local=True, stands=stands)
                    
                    # Deteksi stuck: jika robot tidak bergerak (collision), langsung grab
                    actual_move = math.hypot(robot.orig_x - old_x, robot.orig_y - old_y)
                    if actual_move < 0.1:
                        if not hasattr(grab_sequence_state, '_stuck_count'):
                            grab_sequence_state['_stuck_count'] = 0
                        grab_sequence_state['_stuck_count'] = grab_sequence_state.get('_stuck_count', 0) + 1
                        if grab_sequence_state['_stuck_count'] > 10:  # Stuck 10 frame berturut-turut
                            grab_sequence_state["phase"] = "GRABBING"
                            grab_sequence_state['_stuck_count'] = 0
                            robot.start_grab()
                    else:
                        grab_sequence_state['_stuck_count'] = 0
                        
        elif grab_sequence_state["phase"] == "GRABBING":
            # Tunggu cakar selesai
            robot.update(keys, raw_lapangan, 0.0, 0.0, 0.0, use_ext=True, is_local=True, stands=stands)
            if robot.gripper_state == "IDLE" and robot.gripper_ext == 0.0:
                # Selesai seluruh sequence
                grab_sequence_state["active"] = False
                grab_sequence_state["phase"] = "NONE"
                grab_sequence_state['_stuck_count'] = 0
    elif drop_sequence_state["active"]:
        # Jalankan logic approach & drop (mirip ambil kubus)
        fd_x = math.cos(robot.angle)
        fd_y = math.sin(robot.angle)
        
        if drop_sequence_state["phase"] == "APPROACH":
            # Hitung posisi ujung gripper saat fully extended
            gripper_tip_dist = robot.ROBOT_RADIUS + 35.0
            tip_x = robot.orig_x + gripper_tip_dist * fd_x
            tip_y = robot.orig_y + gripper_tip_dist * fd_y
            
            # Cari stand terdekat di depan robot (yang KOSONG)
            best_stand = None
            min_d = 999999.0
            for s in stands:
                if s["color"] is not None:
                    continue  # Lewati stand yang sudah ada isinya
                if s["type"] == "H":
                    cx = s["x"] + 125
                    cy = s["y"]
                else:
                    cx = s["x"]
                    cy = s["y"] + 105
                
                # Cek apakah stand ini berada di depan robot
                to_stand_x = cx - robot.orig_x
                to_stand_y = cy - robot.orig_y
                dot = to_stand_x * fd_x + to_stand_y * fd_y
                if dot <= 0:
                    continue
                
                d = math.hypot(tip_x - cx, tip_y - cy)
                if d < min_d:
                    min_d = d
                    best_stand = s
            
            if best_stand is None:
                # Tidak ada stand kosong di depan robot — langsung drop saja
                drop_sequence_state["phase"] = "DROPPING"
                robot.start_drop(drop_sequence_state["slot"])
                robot.update(keys, raw_lapangan, 0.0, 0.0, 0.0, use_ext=True, is_local=True, stands=stands)
            else:
                # Jarak gripper tip ke stand center
                drop_range = 100.0  # mm
                
                if min_d <= drop_range:
                    drop_sequence_state["phase"] = "DROPPING"
                    robot.start_drop(drop_sequence_state["slot"])
                    robot.update(keys, raw_lapangan, 0.0, 0.0, 0.0, use_ext=True, is_local=True, stands=stands)
                else:
                    err = min_d - drop_range
                    kp = 0.15
                    vx_local = err * kp
                    vx_local = max(3.0, min(10.0, vx_local))
                    
                    old_x = robot.orig_x
                    old_y = robot.orig_y
                    robot.update(keys, raw_lapangan, vx_local, 0.0, 0.0, use_ext=True, is_local=True, stands=stands)
                    
                    # Deteksi stuck
                    actual_move = math.hypot(robot.orig_x - old_x, robot.orig_y - old_y)
                    if actual_move < 0.1:
                        drop_sequence_state['_stuck_count'] = drop_sequence_state.get('_stuck_count', 0) + 1
                        if drop_sequence_state['_stuck_count'] > 10:
                            drop_sequence_state["phase"] = "DROPPING"
                            drop_sequence_state['_stuck_count'] = 0
                            robot.start_drop(drop_sequence_state["slot"])
                    else:
                        drop_sequence_state['_stuck_count'] = 0
                        
        elif drop_sequence_state["phase"] == "DROPPING":
            robot.update(keys, raw_lapangan, 0.0, 0.0, 0.0, use_ext=True, is_local=True, stands=stands)
            if robot.gripper_state == "IDLE" and robot.gripper_ext == 0.0:
                drop_sequence_state["active"] = False
                drop_sequence_state["phase"] = "NONE"
                drop_sequence_state['_stuck_count'] = 0
    elif balance_state["active"]:
        bal_vx, bal_vy, bal_vw, bal_done = update_balance(robot, balance_state, raw_lapangan)
        if bal_done:
            # Semua fase selesai: kalibrasi heading saja (tanpa reset koordinat)
            # Koordinat robot bergeser sedikit dari posisi balance — ini normal
            half_pi = math.pi / 2.0
            calibrated_angle = round(robot.angle / half_pi) * half_pi
            rel_a = robot.angle - origin_angle
            calibrated_rel_a = round(rel_a / half_pi) * half_pi
            robot.angle  = calibrated_angle
            origin_angle = calibrated_angle - calibrated_rel_a
            # TIDAK reset origin_x/origin_y → koordinat tetap kontinu
            cmd_vx, cmd_vy, cmd_vw = 0.0, 0.0, 0.0
            use_ext_control = False
            robot.update(keys, raw_lapangan, stands=stands)
        else:
            robot.update(keys, raw_lapangan, bal_vx, bal_vy, bal_vw, use_ext=True, is_local=True, stands=stands)
    elif nav_state["is_navigating"]:
        robot.update(keys, raw_lapangan, nav_vx, nav_vy, nav_vw, use_ext=True, stands=stands)
    elif use_ext_control:
        robot.update(keys, raw_lapangan, cmd_vx, cmd_vy, cmd_vw, use_ext=True, is_local=is_vel_local, stands=stands)
    else:
        robot.update(keys, raw_lapangan, stands=stands)

    # 5. Hitung koordinat relatif terhadap origin dinamis
    rel_x     = robot.orig_x - origin_x
    rel_y     = origin_y - robot.orig_y
    rel_angle = robot.angle - origin_angle

    # 6. Kirim STATUS ke client GUI
    if client_socket:
        try:
            nav_status = 1 if nav_state["is_navigating"] else 0
            bal_status = 1 if balance_state["active"]    else 0
            phase_str  = balance_state["phase"] or "NONE"
            grab_active = 1 if grab_sequence_state["active"] else 0
            drop_active = 1 if drop_sequence_state["active"] else 0
            storage_count = sum(1 for c in robot.storage if c is not None)
            storage_colors = ",".join([c[0] if c else "-" for c in robot.storage])
            status_msg = (f"STATUS {rel_x} {rel_y} {rel_angle} "
                          f"{robot.total_dist} {nav_status} {bal_status} {phase_str} "
                          f"{robot.line_l} {robot.line_r} "
                          f"{grab_active} {storage_count} {storage_colors} {drop_active}\n")
            client_socket.sendall(status_msg.encode('utf-8'))
        except (BlockingIOError, ConnectionResetError, BrokenPipeError):
            pass

    # 7. Render
    screen.fill(BLACK)
    screen.blit(scaled_lapangan, (offset_x, 0))

    # --- Render Cubes on top of stands ---
    for s in stands:
        if s["color"] is not None:
            # Tentukan warna
            if s["color"] == "RED":
                color_val = (255, 0, 0)
            elif s["color"] == "GREEN":
                color_val = (0, 200, 0)
            else: # BLUE
                color_val = (0, 100, 255)
            
            # Hitung pusat stand
            if s["type"] == "H":
                cx = s["x"] + 125
                cy = s["y"]
            else:
                cx = s["x"]
                cy = s["y"] + 105
                
            scx = offset_x + cx * SCALE
            scy = cy * SCALE
            cube_w = 20
            cube_h = 20
            rect_s = pygame.Rect(scx - cube_w / 2, scy - cube_h / 2, cube_w, cube_h)
            
            pygame.draw.rect(screen, color_val, rect_s)
            pygame.draw.rect(screen, BLACK, rect_s, 1)

    # --- Render Coretan (Scribbles) ---
    for stroke in scribbles:
        if len(stroke) >= 2:
            scaled_stroke = [(offset_x + pt[0] * SCALE, pt[1] * SCALE) for pt in stroke]
            pygame.draw.lines(screen, RED, False, scaled_stroke, 3)
        elif len(stroke) == 1:
            pt = stroke[0]
            pygame.draw.circle(screen, RED, (int(offset_x + pt[0] * SCALE), int(pt[1] * SCALE)), 3)

    # --- Render Label ---
    font_lbl = pygame.font.SysFont("Arial", 14, bold=True)
    for lbl in labels:
        lx = offset_x + lbl["x"] * SCALE
        ly = lbl["y"] * SCALE
        txt_surf = font_lbl.render(lbl["text"], True, BLACK)
        txt_rect = txt_surf.get_rect(center=(lx, ly))
        bg_rect = txt_rect.inflate(10, 6)
        pygame.draw.rect(screen, WHITE, bg_rect)
        pygame.draw.rect(screen, RED, bg_rect, 1) # Red border
        screen.blit(txt_surf, txt_rect)

    # Gambar rute A* (hanya garis, tanpa node dan tanpa grid rintangan)
    waypoints = nav_state["waypoints"]
    if waypoints:
        scaled_pts = [(offset_x + pt[0] * SCALE, pt[1] * SCALE) for pt in waypoints]
        if len(scaled_pts) >= 2:
            pygame.draw.lines(screen, GREEN, False, scaled_pts, 2)

    # Gambar robot
    robot.draw(screen, raw_lapangan, SCALE, offset_x)

    # 8. HUD / Control Panel
    pos_x_cm    = rel_x / 10.0
    pos_y_cm    = rel_y / 10.0
    heading_deg = math.degrees(-rel_angle) % 360.0

    if show_help:
        # Definisi Warna Monokrom
        C_WHITE = (255, 255, 255)
        C_LIGHT = (200, 200, 200)
        C_GRAY  = (140, 140, 140)
        C_DARK  = (50, 50, 50)

        if offset_x > 220:
            # Render background sidebar kiri (monokrom gelap premium)
            pygame.draw.rect(screen, (15, 15, 15), (0, 0, offset_x - 20, screen_h))
            pygame.draw.line(screen, C_DARK, (offset_x - 20, 0), (offset_x - 20, screen_h), 2)

            # 1. Title
            title_surf = font_title.render("CONTROL PANEL", True, C_WHITE)
            screen.blit(title_surf, (30, 30))

            # 2. Status
            if control_mode == "MANUAL":
                status_lbl = "KENDALI MANUAL (Keyboard)"
            elif grab_sequence_state["active"]:
                status_lbl = f"AMBIL KUBUS ({grab_sequence_state['phase']})"
            elif balance_state["active"]:
                status_lbl = f"{balance_state.get('mode', 'BALANCE')}"
            elif use_ext_control or nav_state["is_navigating"]:
                status_lbl = "NAVIGASI OTOMATIS" if nav_state["is_navigating"] else "KENDALI GUI AKTIF"
            else:
                status_lbl = "IDLE (Menunggu GUI)"

            lbl_status_tag = font_text.render("[ STATUS ]", True, C_GRAY)
            lbl_status_val = font_text.render(status_lbl, True, C_WHITE)
            screen.blit(lbl_status_tag, (30, 75))
            screen.blit(lbl_status_val, (130, 75))

            # Fungsi pembantu untuk menggambar baris pemisah
            def draw_separator(y_pos):
                pygame.draw.line(screen, C_DARK, (30, y_pos), (offset_x - 50, y_pos), 1)

            # Fungsi pembantu untuk menampilkan baris data (Label : Value)
            def draw_row(label, value, y_pos, val_color=C_WHITE):
                lbl_surf = font_text.render(label, True, C_GRAY)
                val_surf = font_text.render(value, True, val_color)
                screen.blit(lbl_surf, (30, y_pos))
                screen.blit(val_surf, (165, y_pos))

            # --- SECTION 1: POSITION & ODOMETRY ---
            y_sec1 = 115
            draw_separator(y_sec1)
            
            draw_row("X Coordinate", f"{pos_x_cm/100:+.3f} m", y_sec1 + 15)
            draw_row("Y Coordinate", f"{pos_y_cm/100:+.3f} m", y_sec1 + 37)
            draw_row("Heading", f"{heading_deg:.1f}°", y_sec1 + 59)
            
            move_color = C_WHITE if robot.movement_status == "DIAM" else C_LIGHT
            draw_row("Movement Status", robot.movement_status, y_sec1 + 81, move_color)
            
            color_l = (0, 255, 0) if robot.line_l else C_GRAY
            color_r = (0, 255, 0) if robot.line_r else C_GRAY
            draw_row("Line Sensor L", "AKTIF" if robot.line_l else "MATI", y_sec1 + 103, color_l)
            draw_row("Line Sensor R", "AKTIF" if robot.line_r else "MATI", y_sec1 + 125, color_r)
            storage_count = sum(1 for c in robot.storage if c is not None)
            draw_row("Storage Cubes", f"{storage_count} / 8", y_sec1 + 147)
            # Tampilkan isi storage (warna)
            content_str = ", ".join([c[0] if c else "-" for c in robot.storage])
            draw_row("Storage Content", f"[{content_str}]", y_sec1 + 169)

            # --- SECTION 2: INTERACTIVE TOOLS ---
            y_sec2 = 310
            draw_separator(y_sec2)
            
            draw_row("Active Tool", active_tool, y_sec2 + 15, C_WHITE)
            
            # Daftar keybindings tool
            font_small = pygame.font.SysFont("Arial", 14)
            tool_items = [
                ("[F1] Teleport", "Klik lapangan untuk memindahkan robot"),
                ("[F2] Corek Draw", "Klik & seret untuk menggambar"),
                ("[F3] Text Label", "Klik lapangan untuk membuat teks label"),
                ("[F4] Eraser", "Klik & seret untuk menghapus coretan/label"),
                ("[F5] Clear All", "Bersihkan seluruh coretan & label")
            ]
            for idx, (key, desc) in enumerate(tool_items):
                key_surf = font_small.render(key, True, C_WHITE)
                desc_surf = font_small.render(desc, True, C_GRAY)
                screen.blit(key_surf, (30, y_sec2 + 45 + idx * 22))
                screen.blit(desc_surf, (135, y_sec2 + 45 + idx * 22))

            # --- SECTION 3: CONFIGURATION ---
            y_sec3 = 475
            draw_separator(y_sec3)
            
            draw_row("Control Mode", control_mode, y_sec3 + 15)
            
            mode_items = [
                ("[M]", "Toggle Mode (Manual / State Machine)"),
                ("[H]", "Tampilkan / Sembunyikan Bantuan"),
                ("[R]", "Reset posisi robot ke HOME"),
                ("W/S/A/D", "Gerakan Manual (Maju/Mundur/Geser)"),
                ("Arrows", "Putar Heading Robot (Manual)")
            ]
            for idx, (key, desc) in enumerate(mode_items):
                key_surf = font_small.render(key, True, C_WHITE)
                desc_surf = font_small.render(desc, True, C_GRAY)
                screen.blit(key_surf, (30, y_sec3 + 45 + idx * 22))
                screen.blit(desc_surf, (110, y_sec3 + 45 + idx * 22))

            draw_separator(y_sec3 + 165)

            # --- SECTION 4: STAND DASHBOARD (RIGHT SIDEBAR) ---
            right_sidebar_x = offset_x + int(2000 * SCALE) + 20
            pygame.draw.rect(screen, (15, 15, 15), (right_sidebar_x, 0, screen_w - right_sidebar_x, screen_h))
            pygame.draw.line(screen, C_DARK, (right_sidebar_x, 0), (right_sidebar_x, screen_h), 2)

            right_title = font_title.render("STAND DASHBOARD", True, C_WHITE)
            screen.blit(right_title, (right_sidebar_x + 30, 30))

            def get_stand_by_label(lbl):
                for s in stands:
                    if s.get("label") == lbl:
                        return s
                return None

            def draw_table_section(title, stand_labels, start_y):
                t_surf = font_text.render(title, True, C_GRAY)
                screen.blit(t_surf, (right_sidebar_x + 30, start_y))
                pygame.draw.line(screen, C_DARK, (right_sidebar_x + 30, start_y + 22), (screen_w - 30, start_y + 22), 1)
                
                for idx, s_label in enumerate(stand_labels):
                    s = get_stand_by_label(s_label)
                    y_pos = start_y + 30 + idx * 22
                    
                    lbl_surf = font_text.render(s_label, True, C_WHITE)
                    screen.blit(lbl_surf, (right_sidebar_x + 30, y_pos))
                    
                    color_text = "EMPTY"
                    color_disp = C_GRAY
                    indicator_color = (60, 60, 60)
                    if s and s["color"] is not None:
                        color_text = s["color"]
                        if s["color"] == "RED":
                            color_disp = (255, 100, 100)
                            indicator_color = (255, 0, 0)
                        elif s["color"] == "GREEN":
                            color_disp = (100, 255, 100)
                            indicator_color = (0, 200, 0)
                        elif s["color"] == "BLUE":
                            color_disp = (100, 180, 255)
                            indicator_color = (0, 100, 255)
                    
                    ind_rect = pygame.Rect(right_sidebar_x + 130, y_pos + 4, 12, 12)
                    pygame.draw.rect(screen, indicator_color, ind_rect)
                    pygame.draw.rect(screen, C_GRAY, ind_rect, 1)
                    
                    status_surf = font_text.render(f"[{color_text}]", True, color_disp)
                    screen.blit(status_surf, (right_sidebar_x + 155, y_pos))

            draw_table_section("P1 - START AREA (BOTTOM)", ["P1 S1", "P1 S2", "P1 S3"], 80)
            draw_table_section("P2 - BOTTOM LEFT SIDEBAR", ["P2 S3", "P2 S2", "P2 S1"], 190)
            draw_table_section("P3 - TOP LEFT SIDEBAR", ["P3 S1", "P3 S2", "P3 S3"], 300)
            draw_table_section("P4 - MID LEFT SIDEBAR", ["P4 S3", "P4 S2", "P4 S1"], 410)
            draw_table_section("P5 - TOP RIGHT SIDEBAR", ["P5 S1", "P5 S2", "P5 S3"], 520)
        else:
            text_x       = 20
            text_y_start = 15
            text_color   = BLACK
            text_bg = pygame.Surface((280, 220))
            text_bg.fill(WHITE)
            text_bg.set_alpha(200)
            screen.blit(text_bg, (10, 10))

            text_pos  = font_text.render(f"Robot: X={pos_x_cm/100:+.2f}m, Y={pos_y_cm/100:+.2f}m", True, BLACK)
            text_dir  = font_text.render(f"Hadap: {heading_deg:.0f}° | Mode: {control_mode}", True, BLACK)
            text_move = font_text.render(f"Gerak: {robot.movement_status} | Tool: {active_tool}", True, BLACK)
            text_h1   = font_text.render("W/S/A/D / Arrows: Gerakan Manual", True, (80, 80, 80))
            text_h2   = font_text.render("F1-F4: Pilih Tool | F5: Clear", True, (80, 80, 80))
            text_h3   = font_text.render("Tombol M: Toggle Mode | H: Menu", True, (80, 80, 80))

            screen.blit(text_pos,  (text_x, text_y_start))
            screen.blit(text_dir,  (text_x, text_y_start + 22))
            screen.blit(text_move, (text_x, text_y_start + 44))
            screen.blit(text_h1,   (text_x, text_y_start + 72))
            screen.blit(text_h2,   (text_x, text_y_start + 92))
            screen.blit(text_h3,   (text_x, text_y_start + 112))
    else:
        mini = font_text.render("Tekan 'H' untuk Menu Bantuan", True,
                                WHITE if offset_x > 220 else BLACK)
        screen.blit(mini, (20, screen_h - 40))

    pygame.display.flip()


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
if client_socket:
    client_socket.close()
server_socket.close()
pygame.quit()
sys.exit()
