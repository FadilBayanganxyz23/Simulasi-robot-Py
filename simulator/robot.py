"""
simulator/robot.py
==================
Bertanggung jawab atas:
- Class SimRobot: state posisi & sudut robot
- Kinematika robot omni 3 roda (Inverse Kinematics + Forward Kinematics)
- Deteksi tabrakan berbasis perimeter robot
- Rendering robot ke surface Pygame

Catatan konvensi:
  - robot.angle  : radian (sistem Pygame, Y ke bawah)
  - origin_angle : -π/2 → menghadap ke atas layar = heading 0° di UI
"""

import pygame
import math

from simulator.field_layout import (
    FIELD_OFFSET_X, FIELD_OFFSET_Y,
    is_pixel_crossable, is_in_slider_box,
    check_box_collision_circle, check_wall_segments_collision,
    RED, GREEN, BLUE, BLACK, YELLOW, WHITE,
)

# Warna tambahan untuk sensor IR
ORANGE = (255, 140,   0)   # Sensor kiri
CYAN   = (  0, 220, 220)   # Sensor belakang


class SimRobot:
    """
    Robot omni 12-sisi.

    Atribut publik:
        orig_x, orig_y  : posisi pusat robot dalam piksel world lapangan
        angle           : sudut orientasi robot dalam radian (Pygame)
        total_dist      : total jarak tempuh (piksel)
        movement_status : string deskripsi arah gerak terakhir
    """

    # Radius robot dalam mm (skala 1px = 1mm)
    ROBOT_RADIUS = 410 / 2       # radius lingkaran luar (untuk render)
    COLLISION_RADIUS = 202        # radius lingkaran collision

    def __init__(self):
        self.orig_x  = FIELD_OFFSET_X + 1100
        self.orig_y  = FIELD_OFFSET_Y + 2850
        self.angle   = -math.pi / 2    # menghadap ke atas (heading 0°)
        self.speed   = 12.0
        self.rot_speed = 0.05
        self.total_dist = 0.0
        self.movement_status = "DIAM"
        self.line_l = 0
        self.line_r = 0
        
        # Gripper & Carousel Storage
        self.gripper_state = "IDLE"      # "IDLE", "EXTENDING", "RETRACTING"
        self.gripper_ext = 0.0           # 0.0 to 1.0
        self.drop_slot = 0
        self.storage = [None] * 8                # Max 8 elements (colors: RED, GREEN, BLUE)
        self.last_grabbed_color = None
        self.carousel_angle = 0.0
        self.target_carousel_angle = 0.0

    # ------------------------------------------------------------------
    # Geometri Robot
    # ------------------------------------------------------------------

    def get_perimeter_points(self, x, y, angle, radius=None):
        """Return daftar titik perimeter 12-sisi robot dalam koordinat world."""
        r = radius if radius is not None else self.ROBOT_RADIUS
        vertices = []
        for i in range(12):
            theta = i * (2 * math.pi / 12)
            vx = r * math.cos(angle + theta)
            vy = r * math.sin(angle + theta)
            vertices.append((vx, vy))

        points = []
        segments = 3
        for i in range(12):
            p1 = vertices[i]
            p2 = vertices[(i + 1) % 12]
            for j in range(segments):
                t  = j / segments
                px = int(x + p1[0] + (p2[0] - p1[0]) * t)
                py = int(y + p1[1] + (p2[1] - p1[1]) * t)
                points.append((px, py))
        return points

    # ------------------------------------------------------------------
    # Collision Detection
    # ------------------------------------------------------------------

    def check_collision(self, x, y, angle, raw_lapangan):
        """
        Return True jika robot pada (x,y,angle) bertabrakan dengan rintangan.

        Parameter:
            raw_lapangan : pygame.Surface lapangan (untuk cek piksel).
        """
        if check_box_collision_circle(x, y, radius=self.COLLISION_RADIUS):
            return True
        if check_wall_segments_collision(x, y, radius=self.COLLISION_RADIUS):
            return True

        # Gunakan COLLISION_RADIUS - 5 sebagai radius perimeter check untuk memberi toleransi 5px
        # agar robot tidak tersangkut/jamming saat berputar dekat dinding akibat rounding error.
        points   = self.get_perimeter_points(x, y, angle, radius=self.COLLISION_RADIUS - 5)
        orig_w, orig_h = raw_lapangan.get_size()
        for px, py in points:
            if px < 0 or px >= orig_w or py < 0 or py >= orig_h:
                return True
            if is_pixel_crossable(px, py):
                continue
            if is_in_slider_box(px, py):
                continue
            if raw_lapangan.get_at((px, py))[0] < 100:
                return True
        return False

    # ------------------------------------------------------------------
    # Update Fisika (IK → FK → Odometri)
    # ------------------------------------------------------------------

    def update(self, keys, raw_lapangan, ext_vx=0.0, ext_vy=0.0, ext_vw=0.0, use_ext=False, is_local=False, stands=None):
        """
        Update posisi robot satu frame (60 fps, skala 40 px/frame).

        Parameter:
            keys        : pygame.key.get_pressed()
            raw_lapangan: surface lapangan untuk cek tabrakan
            ext_vx/vy/vw: kecepatan dari GUI/navigasi otomatis
            use_ext     : True → gunakan ext_vx/vy/vw, False → keyboard
            is_local    : True → ext_vx/vy adalah kecepatan lokal robot (no conversion)
        """
        old_x     = self.orig_x
        old_y     = self.orig_y
        old_angle = self.angle
        cos_a     = math.cos(self.angle)
        sin_a     = math.sin(self.angle)
        R         = 200.0   # radius roda (mm)

        if use_ext:
            if is_local:
                vx_local = ext_vx
                vy_local = ext_vy
            else:
                # Konversi kecepatan global GUI → lokal robot
                # GUI: vx = Maju/Mundur (sumbu Y dunia), vy = Geser (sumbu X dunia)
                v_glob_x = ext_vy
                v_glob_y = -ext_vx      # inversi karena Y Pygame ke bawah

                vx_local = v_glob_x * cos_a + v_glob_y * sin_a
                vy_local = -v_glob_x * sin_a + v_glob_y * cos_a

            # Inverse Kinematics (lokal → roda)
            w1 = -0.5 * vx_local + 0.866 * vy_local + ext_vw * R
            w2 = -0.5 * vx_local - 0.866 * vy_local + ext_vw * R
            w3 =         vx_local                   + ext_vw * R

            # Forward Kinematics (roda → lokal)
            calc_vx_local = (2.0 / 3.0) * w3 - (1.0 / 3.0) * (w1 + w2)
            calc_vy_local = (1.0 / math.sqrt(3.0)) * (w1 - w2)
            calc_vw       = (w1 + w2 + w3) / (3.0 * R)

            # Dynamic Odometry (lokal → global Pygame)
            calc_vx_global = calc_vx_local * cos_a - calc_vy_local * sin_a
            calc_vy_global = calc_vx_local * sin_a + calc_vy_local * cos_a

            dx       = calc_vx_global * (40.0 / 60.0)
            dy       = calc_vy_global * (40.0 / 60.0)
            speed_w  = calc_vw * (0.314159 / 60.0)
            self.angle += speed_w

        else:
            speed_x = 0.0
            speed_y = 0.0
            speed_w = 0.0

            if keys[pygame.K_LEFT]:
                speed_w = -self.rot_speed * (60.0 / 0.314159)
            if keys[pygame.K_RIGHT]:
                speed_w =  self.rot_speed * (60.0 / 0.314159)
            if keys[pygame.K_w] or keys[pygame.K_UP]:
                speed_x =  self.speed * (60.0 / 40.0)
            if keys[pygame.K_s] or keys[pygame.K_DOWN]:
                speed_x = -self.speed * (60.0 / 40.0)
            if keys[pygame.K_a]:
                speed_y = -self.speed * (60.0 / 40.0)
            if keys[pygame.K_d]:
                speed_y =  self.speed * (60.0 / 40.0)

            # IK + FK manual
            w1 = -0.5 * speed_x + 0.866 * speed_y + speed_w * R
            w2 = -0.5 * speed_x - 0.866 * speed_y + speed_w * R
            w3 =         speed_x                   + speed_w * R

            calc_vx_local = (2.0 / 3.0) * w3 - (1.0 / 3.0) * (w1 + w2)
            calc_vy_local = (1.0 / math.sqrt(3.0)) * (w1 - w2)
            calc_vw       = (w1 + w2 + w3) / (3.0 * R)

            calc_vx_global = calc_vx_local * cos_a - calc_vy_local * sin_a
            calc_vy_global = calc_vx_local * sin_a + calc_vy_local * cos_a

            dx = calc_vx_global * (40.0 / 60.0)
            dy = calc_vy_global * (40.0 / 60.0)
            self.angle += calc_vw * (0.314159 / 60.0)

        # Terapkan posisi baru (rollback jika tabrakan)
        self.orig_x += dx
        self.orig_y += dy

        if self.check_collision(self.orig_x, self.orig_y, self.angle, raw_lapangan):
            self.orig_x = old_x
            self.orig_y = old_y
            self.angle  = old_angle
        else:
            self.total_dist += math.sqrt(dx ** 2 + dy ** 2)

        # Hitung status arah gerak untuk display
        actual_dx = self.orig_x - old_x
        actual_dy = self.orig_y - old_y
        actual_dw = math.atan2(math.sin(self.angle - old_angle),
                               math.cos(self.angle - old_angle))

        local_dx =  actual_dx * cos_a + actual_dy * sin_a
        local_dy = -actual_dx * sin_a + actual_dy * cos_a

        status = []
        if abs(actual_dw) > 0.0005:
            status.append("PUTAR KANAN" if actual_dw > 0 else "PUTAR KIRI")
        if abs(local_dx) > 0.05 or abs(local_dy) > 0.05:
            if abs(local_dx) > abs(local_dy):
                status.append("MAJU" if local_dx > 0 else "MUNDUR")
            else:
                status.append("GESER KANAN" if local_dy > 0 else "GESER KIRI")
        self.movement_status = " + ".join(status) if status else "DIAM"
        self.update_line_sensors(raw_lapangan)

        # Animasi Gripper & Logika Ambil
        if self.gripper_state == "WAITING_CAROUSEL_GRAB":
            if abs(self.carousel_angle - self.target_carousel_angle) < 1.0:
                self.carousel_angle = self.target_carousel_angle
                self.gripper_state = "EXTENDING"
                self.gripper_ext = 0.0
        elif self.gripper_state == "WAITING_CAROUSEL_DROP":
            if abs(self.carousel_angle - self.target_carousel_angle) < 1.0:
                self.carousel_angle = self.target_carousel_angle
                self.gripper_state = "EXTENDING_DROP"
                self.gripper_ext = 0.0
        elif self.gripper_state == "EXTENDING":
            self.gripper_ext += 0.05
            if self.gripper_ext >= 1.0:
                self.gripper_ext = 1.0
                self.gripper_state = "RETRACTING"
                self.perform_grab(stands)
        elif self.gripper_state == "RETRACTING":
            self.gripper_ext -= 0.05
            if self.gripper_ext <= 0.0:
                self.gripper_ext = 0.0
                self.gripper_state = "IDLE"
        elif self.gripper_state == "EXTENDING_DROP":
            self.gripper_ext += 0.05
            if self.gripper_ext >= 1.0:
                self.gripper_ext = 1.0
                self.gripper_state = "RETRACTING_DROP"
                self.perform_drop(stands)
        elif self.gripper_state == "RETRACTING_DROP":
            self.gripper_ext -= 0.05
            if self.gripper_ext <= 0.0:
                self.gripper_ext = 0.0
                self.gripper_state = "IDLE"

        # Animasi Putar Carousel (ke arah terpendek)
        if abs(self.carousel_angle - self.target_carousel_angle) > 0.01:
            diff = self.target_carousel_angle - self.carousel_angle
            step = 3.0 if diff > 0 else -3.0
            if abs(diff) <= abs(step):
                self.carousel_angle = self.target_carousel_angle
            else:
                self.carousel_angle += step

    def get_line_sensor_positions(self):
        """Return world coordinates (px, py) untuk sensor garis kiri dan kanan di depan robot."""
        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)
        
        # Posisi relatif di depan robot (radius 205, kita pasang di radius 190)
        # Gap antara kiri dan kanan = 10mm (5mm ke kiri, 5mm ke kanan dari garis lurus)
        local_x = 190.0
        local_y_l = -5.0
        local_y_r = 5.0
        
        l_x = int(self.orig_x + local_x * cos_a - local_y_l * sin_a)
        l_y = int(self.orig_y + local_x * sin_a + local_y_l * cos_a)
        
        r_x = int(self.orig_x + local_x * cos_a - local_y_r * sin_a)
        r_y = int(self.orig_y + local_x * sin_a + local_y_r * cos_a)
        
        return (l_x, l_y), (r_x, r_y)

    def update_line_sensors(self, raw_lapangan):
        """Baca piksel lapangan di lokasi sensor untuk mendeteksi garis hitam (< 100)."""
        (l_x, l_y), (r_x, r_y) = self.get_line_sensor_positions()
        orig_w, orig_h = raw_lapangan.get_size()
        
        # Sensor kiri
        if 0 <= l_x < orig_w and 0 <= l_y < orig_h:
            color = raw_lapangan.get_at((l_x, l_y))
            self.line_l = 1 if (color[0] < 100 and color[1] < 100 and color[2] < 100) else 0
        else:
            self.line_l = 0
            
        # Sensor kanan
        if 0 <= r_x < orig_w and 0 <= r_y < orig_h:
            color = raw_lapangan.get_at((r_x, r_y))
            self.line_r = 1 if (color[0] < 100 and color[1] < 100 and color[2] < 100) else 0
        else:
            self.line_r = 0

    def start_grab(self):
        if self.gripper_state == "IDLE":
            target_idx = -1
            for i in range(8):
                if self.storage[i] is None:
                    target_idx = i
                    break
            if target_idx != -1:
                current_mod = self.carousel_angle % 360
                target_mod = target_idx * 45.0
                diff = (target_mod - current_mod) % 360
                if diff > 180:
                    diff -= 360
                self.target_carousel_angle = self.carousel_angle + diff
                self.gripper_state = "WAITING_CAROUSEL_GRAB"
            else:
                self.gripper_state = "EXTENDING"
                self.gripper_ext = 0.0

    def start_drop(self, slot_idx):
        if self.gripper_state == "IDLE":
            self.drop_slot = slot_idx
            current_mod = self.carousel_angle % 360
            target_mod = slot_idx * 45.0
            diff = (target_mod - current_mod) % 360
            if diff > 180:
                diff -= 360
            self.target_carousel_angle = self.carousel_angle + diff
            self.gripper_state = "WAITING_CAROUSEL_DROP"

    def perform_grab(self, stands):
        if not stands:
            return
        
        # Arah hadap robot
        fd_x = math.cos(self.angle)
        fd_y = math.sin(self.angle)
        
        # Ujung gripper berjarak ROBOT_RADIUS + 35mm
        gripper_tip_dist = self.ROBOT_RADIUS + 35.0
        tip_x = self.orig_x + gripper_tip_dist * fd_x
        tip_y = self.orig_y + gripper_tip_dist * fd_y
        
        # Cari stand terdekat (maksimal 180 mm — diperbesar karena collision boundary)
        best_stand = None
        min_d = 180.0
        for s in stands:
            if s["type"] == "H":
                cx = s["x"] + 125
                cy = s["y"]
            else:
                cx = s["x"]
                cy = s["y"] + 105
            
            d = math.hypot(tip_x - cx, tip_y - cy)
            if d < min_d:
                min_d = d
                best_stand = s
                
        if best_stand and best_stand["color"] is not None:
            for i in range(8):
                if self.storage[i] is None:
                    cube_color = best_stand["color"]
                    best_stand["color"] = None
                    self.storage[i] = cube_color
                    self.last_grabbed_color = cube_color
                    break

    def perform_drop(self, stands):
        if not stands or self.drop_slot < 0 or self.drop_slot >= 8:
            return
            
        # Arah hadap robot
        fd_x = math.cos(self.angle)
        fd_y = math.sin(self.angle)
        
        # Ujung gripper berjarak ROBOT_RADIUS + 35mm
        gripper_tip_dist = self.ROBOT_RADIUS + 35.0
        tip_x = self.orig_x + gripper_tip_dist * fd_x
        tip_y = self.orig_y + gripper_tip_dist * fd_y
        
        # Cari stand terdekat
        best_stand = None
        min_d = 180.0
        for s in stands:
            if s["type"] == "H":
                cx = s["x"] + 125
                cy = s["y"]
            else:
                cx = s["x"]
                cy = s["y"] + 105
            
            d = math.hypot(tip_x - cx, tip_y - cy)
            if d < min_d:
                min_d = d
                best_stand = s
                
        if best_stand and best_stand["color"] is None:
            # Pindahkan kubus dari storage ke stand
            cube_color = self.storage[self.drop_slot]
            if cube_color is not None:
                self.storage[self.drop_slot] = None
                best_stand["color"] = cube_color
        else:
            # Jatuhkan kubus (dihapus dari storage) jika tidak ada stand
            if self.storage[self.drop_slot] is not None:
                self.storage[self.drop_slot] = None

    def _cast_ray_pixel(self, raw_lapangan, ox, oy, dx, dy, max_dist=3000):
        """
        Ray-march dari (ox, oy) ke arah (dx, dy) dalam koordinat world (mm = px).
        Mendeteksi tembok terluar DAN tembok internal di layout lapangan.

        Langkah 3px per iterasi → cepat tapi tidak melewati tembok tipis.
        Return: jarak dari pusat robot ke rintangan pertama (mm).
        """
        STEP = 3
        orig_w, orig_h = raw_lapangan.get_size()
        dist = self.ROBOT_RADIUS + STEP   # mulai dari tepi robot, bukan pusat

        while dist < max_dist:
            px = int(ox + dist * dx)
            py = int(oy + dist * dy)

            # Keluar batas = tembok terluar
            if px < 0 or px >= orig_w or py < 0 or py >= orig_h:
                return dist

            # Cek pixel lapangan: gelap + bukan area crossable ATAU di dalam slider box = tembok
            if not is_pixel_crossable(px, py):
                if is_in_slider_box(px, py) or raw_lapangan.get_at((px, py))[0] < 100:
                    return dist

            dist += STEP

        return max_dist

    def get_sensor_distances(self, raw_lapangan):
        """
        Hitung jarak dari sisi robot ke tembok untuk sensor:
        - 2 US Depan (jarak 140mm)
        - 1 IR Depan Tengah
        - 2 IR Kiri (jarak 100mm)
        
        Return: (dist_us_f_l, dist_us_f_r, dist_ir_f, dist_ir_l_f, dist_ir_l_b)
        """
        a = self.angle
        fd_x, fd_y =  math.cos(a),  math.sin(a)
        lf_x, lf_y =  math.sin(a), -math.cos(a)

        # 1. IR Depan (Tengah)
        raw_ir_f = self._cast_ray_pixel(raw_lapangan, self.orig_x, self.orig_y, fd_x, fd_y)
        dist_ir_f = max(0.0, raw_ir_f - self.ROBOT_RADIUS)

        # 2. US Depan (Kiri & Kanan) - offset 70mm ke kiri dan kanan dari pusat
        us_l_x = self.orig_x + 70.0 * lf_x
        us_l_y = self.orig_y + 70.0 * lf_y
        us_r_x = self.orig_x - 70.0 * lf_x
        us_r_y = self.orig_y - 70.0 * lf_y
        
        raw_us_l = self._cast_ray_pixel(raw_lapangan, us_l_x, us_l_y, fd_x, fd_y)
        raw_us_r = self._cast_ray_pixel(raw_lapangan, us_r_x, us_r_y, fd_x, fd_y)
        offset_front = math.sqrt(self.ROBOT_RADIUS**2 - 70.0**2)
        dist_us_f_l = max(0.0, raw_us_l - offset_front)
        dist_us_f_r = max(0.0, raw_us_r - offset_front)

        # 3. IR Kiri (Depan & Belakang) - offset 50mm ke depan dan belakang
        ir_l_f_x = self.orig_x + 50.0 * fd_x
        ir_l_f_y = self.orig_y + 50.0 * fd_y
        ir_l_b_x = self.orig_x - 50.0 * fd_x
        ir_l_b_y = self.orig_y - 50.0 * fd_y
        
        raw_ir_l_f = self._cast_ray_pixel(raw_lapangan, ir_l_f_x, ir_l_f_y, lf_x, lf_y)
        raw_ir_l_b = self._cast_ray_pixel(raw_lapangan, ir_l_b_x, ir_l_b_y, lf_x, lf_y)
        offset_left = math.sqrt(self.ROBOT_RADIUS**2 - 50.0**2)
        dist_ir_l_f = max(0.0, raw_ir_l_f - offset_left)
        dist_ir_l_b = max(0.0, raw_ir_l_b - offset_left)

        return (dist_us_f_l, dist_us_f_r, dist_ir_f, dist_ir_l_f, dist_ir_l_b)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def draw(self, surface, raw_lapangan, scale, offset_x):
        """
        Gambar robot ke surface layar.

        Parameter:
            surface     : pygame.Surface layar
            raw_lapangan: surface lapangan (untuk cek tabrakan titik)
            scale       : faktor skala (pixel lapangan → pixel layar)
            offset_x    : offset horizontal layar
        """
        sx = offset_x + self.orig_x * scale
        sy = self.orig_y * scale
        hw = self.ROBOT_RADIUS * scale
        hh = self.ROBOT_RADIUS * scale
        a  = self.angle

        # --- Arah vektor robot ---
        # Depan:   (cos a,  sin a)
        # Kiri:    ( sin a, -cos a)   [90° CCW di Pygame]
        # Belakang:(-cos a, -sin a)
        fd_x, fd_y =  math.cos(a),  math.sin(a)   # front direction
        lf_x, lf_y =  math.sin(a), -math.cos(a)   # left direction
        bk_x, bk_y = -math.cos(a), -math.sin(a)   # back direction

        # ----------------------------------------------------------------
        # 0. Gripper depan (animasi cakar & kubus yang dibawa)
        # ----------------------------------------------------------------
        if self.gripper_ext > 0.0 or self.gripper_state != "IDLE":
            base_x = sx + hw * fd_x
            base_y = sy + hw * fd_y
            ext_len = 35.0 * self.gripper_ext * scale
            tip_x = base_x + ext_len * fd_x
            tip_y = base_y + ext_len * fd_y
            
            # Gambar batang utama gripper
            pygame.draw.line(surface, (180, 180, 180), (int(base_x), int(base_y)), (int(tip_x), int(tip_y)), int(4 * scale) if int(4*scale) > 1 else 2)
            
            # Gambar cakar kiri dan kanan
            c_left_x = tip_x + 8 * scale * fd_x + 12 * scale * lf_x
            c_left_y = tip_y + 8 * scale * fd_y + 12 * scale * lf_y
            c_right_x = tip_x + 8 * scale * fd_x - 12 * scale * lf_x
            c_right_y = tip_y + 8 * scale * fd_y - 12 * scale * lf_y
            
            pygame.draw.line(surface, (120, 120, 120), (int(tip_x), int(tip_y)), (int(c_left_x), int(c_left_y)), 2)
            pygame.draw.line(surface, (120, 120, 120), (int(tip_x), int(tip_y)), (int(c_right_x), int(c_right_y)), 2)
            
            # Jika sedang menarik kubus (retracting) dan storage tidak kosong, gambarkan kubus dibawa cakar
            if self.gripper_state == "RETRACTING" and self.last_grabbed_color:
                last_color = self.last_grabbed_color
                if last_color == "RED":
                    c_val = (255, 0, 0)
                elif last_color == "GREEN":
                    c_val = (0, 200, 0)
                else:
                    c_val = (0, 100, 255)
                # Ukuran kubus dibawa: 14x14 mm (skala)
                cb_size = 14 * scale
                cb_rect = pygame.Rect(tip_x + 3*scale*fd_x - cb_size/2, tip_y + 3*scale*fd_y - cb_size/2, cb_size, cb_size)
                pygame.draw.rect(surface, c_val, cb_rect)
                pygame.draw.rect(surface, BLACK, cb_rect, 1)

        # ----------------------------------------------------------------
        # 1. Badan robot (12-sisi)
        # ----------------------------------------------------------------
        corners = []
        for i in range(12):
            theta = i * (2 * math.pi / 12)
            corners.append((sx + hw * math.cos(a + theta),
                            sy + hh * math.sin(a + theta)))
        pygame.draw.polygon(surface, BLUE,  corners)
        pygame.draw.polygon(surface, BLACK, corners, 2)

        # ----------------------------------------------------------------
        # 2. Indikator DEPAN — segitiga kuning padat di luar tepi depan
        # ----------------------------------------------------------------
        tip_dist  = hw * 1.35           # ujung segitiga
        wing_dist = hw * 1.05           # pangkal sayap segitiga
        wing_half = hw * 0.22           # setengah lebar pangkal

        tip_x  = sx + tip_dist  * fd_x
        tip_y  = sy + tip_dist  * fd_y
        # Dua titik pangkal sayap (tegak lurus terhadap arah depan)
        wl_x = sx + wing_dist * fd_x + wing_half * lf_x
        wl_y = sy + wing_dist * fd_y + wing_half * lf_y
        wr_x = sx + wing_dist * fd_x - wing_half * lf_x
        wr_y = sy + wing_dist * fd_y - wing_half * lf_y
        pygame.draw.polygon(surface, YELLOW, [(tip_x, tip_y), (wl_x, wl_y), (wr_x, wr_y)])
        pygame.draw.polygon(surface, BLACK,  [(tip_x, tip_y), (wl_x, wl_y), (wr_x, wr_y)], 1)

        # ----------------------------------------------------------------
        # 2b. Carousel Storage (8 slot penampung kubus berputar)
        # ----------------------------------------------------------------
        # Background lingkar carousel
        pygame.draw.circle(surface, (30, 30, 40), (int(sx), int(sy)), int(hw * 0.55))
        pygame.draw.circle(surface, (100, 100, 120), (int(sx), int(sy)), int(hw * 0.55), 1)

        # Gambar sekat/divider carousel
        for i in range(8):
            angle_deg = self.carousel_angle - i * 45.0
            angle_rad = a + math.radians(angle_deg - 22.5)
            dx_div = sx + (hw * 0.55) * math.cos(angle_rad)
            dy_div = sy + (hw * 0.55) * math.sin(angle_rad)
            pygame.draw.line(surface, (60, 60, 80), (int(sx), int(sy)), (int(dx_div), int(dy_div)), 1)

        if not hasattr(self, '_font'):
            self._font = pygame.font.SysFont(None, int(12 * scale)) if pygame.font.get_init() else None

        # Gambar slot penampung & kubus di dalamnya
        for i in range(8):
            angle_deg = self.carousel_angle - i * 45.0
            angle_rad = a + math.radians(angle_deg)
            slot_x = sx + (hw * 0.38) * math.cos(angle_rad)
            slot_y = sy + (hw * 0.38) * math.sin(angle_rad)
            
            slot_color = (60, 60, 60)
            if self.storage[i] is not None:
                color_name = self.storage[i]
                if color_name == "RED" or color_name == "R":
                    slot_color = (220, 20, 60)
                elif color_name == "GREEN" or color_name == "G":
                    slot_color = (50, 205, 50)
                else: # BLUE
                    slot_color = (0, 100, 255)
            
            # Gambar kompartemen slot
            radius_slot = int(8 * scale) if int(8 * scale) > 4 else 6
            pygame.draw.circle(surface, slot_color, (int(slot_x), int(slot_y)), radius_slot)
            pygame.draw.circle(surface, BLACK, (int(slot_x), int(slot_y)), radius_slot, 1)

            # Tulis angka 1-8
            if self._font:
                text_surf = self._font.render(str(i + 1), True, (255, 255, 255))
                text_rect = text_surf.get_rect(center=(int(slot_x), int(slot_y)))
                surface.blit(text_surf, text_rect)

        # Ambil semua data sensor
        (dist_us_f_l, dist_us_f_r, dist_ir_f, dist_ir_l_f, dist_ir_l_b) = self.get_sensor_distances(raw_lapangan)
        font_s = pygame.font.SysFont("Arial", 11, bold=True)
        
        def draw_sensor(name, dist_val, ox, oy, dx, dy, color, draw_text=True, text_offset_y=-8):
            beam_end_x = ox + (dist_val) * dx
            beam_end_y = oy + (dist_val) * dy
            ssx, ssy = offset_x + ox * scale, oy * scale
            bex, bey = offset_x + beam_end_x * scale, beam_end_y * scale
            
            pygame.draw.line(surface, color, (int(ssx), int(ssy)), (int(bex), int(bey)), 2)
            pygame.draw.circle(surface, color, (int(ssx), int(ssy)), 5)
            
            if draw_text:
                lbl = font_s.render(f"{dist_val:.0f}mm", True, color)
                surface.blit(lbl, (int(bex) + 4, int(bey) + text_offset_y))

        # ----------------------------------------------------------------
        # 3. Sensor US Depan (Kuning) - Kiri dan Kanan
        # ----------------------------------------------------------------
        offset_front = math.sqrt(self.ROBOT_RADIUS**2 - 70.0**2)
        # US Depan Kiri
        us_l_x = self.orig_x + 70.0 * lf_x + offset_front * fd_x
        us_l_y = self.orig_y + 70.0 * lf_y + offset_front * fd_y
        draw_sensor("US_L", dist_us_f_l, us_l_x, us_l_y, fd_x, fd_y, (200, 200, 0), text_offset_y=-15)
        
        # US Depan Kanan
        us_r_x = self.orig_x - 70.0 * lf_x + offset_front * fd_x
        us_r_y = self.orig_y - 70.0 * lf_y + offset_front * fd_y
        draw_sensor("US_R", dist_us_f_r, us_r_x, us_r_y, fd_x, fd_y, (200, 200, 0), text_offset_y=5)

        # ----------------------------------------------------------------
        # 4. Sensor IR Depan (Magenta) - Tengah
        # ----------------------------------------------------------------
        ir_f_x = self.orig_x + self.ROBOT_RADIUS * fd_x
        ir_f_y = self.orig_y + self.ROBOT_RADIUS * fd_y
        draw_sensor("IR_F", dist_ir_f, ir_f_x, ir_f_y, fd_x, fd_y, (255, 0, 255))

        # ----------------------------------------------------------------
        # 5. Sensor IR Kiri (Oranye) - Depan dan Belakang
        # ----------------------------------------------------------------
        offset_left = math.sqrt(self.ROBOT_RADIUS**2 - 50.0**2)
        # IR Kiri Depan
        ir_l_f_x = self.orig_x + 50.0 * fd_x + offset_left * lf_x
        ir_l_f_y = self.orig_y + 50.0 * fd_y + offset_left * lf_y
        draw_sensor("IR_LF", dist_ir_l_f, ir_l_f_x, ir_l_f_y, lf_x, lf_y, (255, 128, 0), text_offset_y=-15)
        
        # IR Kiri Belakang
        ir_l_b_x = self.orig_x - 50.0 * fd_x + offset_left * lf_x
        ir_l_b_y = self.orig_y - 50.0 * fd_y + offset_left * lf_y
        draw_sensor("IR_LB", dist_ir_l_b, ir_l_b_x, ir_l_b_y, lf_x, lf_y, (255, 128, 0), text_offset_y=5)

        # ----------------------------------------------------------------
        # 5. Sensor Garis Depan Kiri & Kanan (merah/hijau indikator)
        # ----------------------------------------------------------------
        (gl_x, gl_y), (gr_x, gr_y) = self.get_line_sensor_positions()
        sgl_x = offset_x + gl_x * scale
        sgl_y = gl_y * scale
        sgr_x = offset_x + gr_x * scale
        sgr_y = gr_y * scale
        
        color_l = (0, 255, 0) if self.line_l else (120, 120, 120)
        color_r = (0, 255, 0) if self.line_r else (120, 120, 120)
        
        # Gambar sensor kiri
        pygame.draw.circle(surface, color_l, (int(sgl_x), int(sgl_y)), int(5 * scale))
        pygame.draw.circle(surface, BLACK, (int(sgl_x), int(sgl_y)), int(5 * scale), 1)
        # Gambar sensor kanan
        pygame.draw.circle(surface, color_r, (int(sgr_x), int(sgr_y)), int(5 * scale))
        pygame.draw.circle(surface, BLACK, (int(sgr_x), int(sgr_y)), int(5 * scale), 1)

        # ----------------------------------------------------------------
        # 6. Lingkaran tengah dan titik perimeter
        # ----------------------------------------------------------------
        pygame.draw.circle(surface, WHITE, (int(sx), int(sy)), int(hw * 0.35), 1)

        points  = self.get_perimeter_points(self.orig_x, self.orig_y, self.angle)
        orig_w, orig_h = raw_lapangan.get_size()
        for px, py in points:
            is_hit = False
            if px < 0 or px >= orig_w or py < 0 or py >= orig_h:
                is_hit = True
            elif not is_pixel_crossable(px, py) and is_in_slider_box(px, py):
                is_hit = True
            elif not is_pixel_crossable(px, py) and raw_lapangan.get_at((px, py))[0] < 100:
                is_hit = True
            dot_color = RED if is_hit else GREEN
            pygame.draw.circle(surface, dot_color,
                               (int(offset_x + px * scale), int(py * scale)), 2)
