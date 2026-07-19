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

    def update(self, keys, raw_lapangan, ext_vx=0.0, ext_vy=0.0, ext_vw=0.0, use_ext=False, is_local=False):
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

            # Cek pixel lapangan: gelap + bukan area crossable + bukan slider box = tembok
            if (not is_pixel_crossable(px, py)
                    and not is_in_slider_box(px, py)
                    and raw_lapangan.get_at((px, py))[0] < 100):
                return dist

            dist += STEP

        return max_dist

    def get_sensor_distances(self, raw_lapangan):
        """
        Hitung jarak sensor IR kiri dan belakang dari SISI robot ke rintangan terdekat.
        Mendeteksi tembok luar maupun tembok internal dalam layout lapangan.

        Return: (dist_left_mm, dist_back_mm)
        """
        a = self.angle
        lf_x, lf_y =  math.sin(a), -math.cos(a)   # arah kiri robot
        bk_x, bk_y = -math.cos(a), -math.sin(a)   # arah belakang robot

        raw_l = self._cast_ray_pixel(raw_lapangan, self.orig_x, self.orig_y, lf_x, lf_y)
        raw_b = self._cast_ray_pixel(raw_lapangan, self.orig_x, self.orig_y, bk_x, bk_y)

        # Kurangi ROBOT_RADIUS karena raw_l = jarak dari pusat, bukan dari tepi
        return max(0.0, raw_l - self.ROBOT_RADIUS), max(0.0, raw_b - self.ROBOT_RADIUS)

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

        # Garis sumbu depan (kuning tipis, untuk referensi)
        pygame.draw.line(surface, YELLOW,
                         (int(sx), int(sy)),
                         (int(sx + hw * fd_x), int(sy + hw * fd_y)), 2)

        # ----------------------------------------------------------------
        # 3. Sensor IR KIRI (oranye)
        # ----------------------------------------------------------------
        # Posisi mount sensor: tepi kiri robot
        ls_wx = self.orig_x + self.ROBOT_RADIUS * lf_x
        ls_wy = self.orig_y + self.ROBOT_RADIUS * lf_y
        # Ray-march melalui pixel lapangan
        dist_left_raw = self._cast_ray_pixel(raw_lapangan, self.orig_x, self.orig_y, lf_x, lf_y)
        sensor_dist_left = max(0.0, dist_left_raw - self.ROBOT_RADIUS)

        beam_end_lx = self.orig_x + dist_left_raw * lf_x
        beam_end_ly = self.orig_y + dist_left_raw * lf_y
        ls_sx  = offset_x + ls_wx * scale
        ls_sy  = ls_wy * scale
        lbe_sx = offset_x + beam_end_lx * scale
        lbe_sy = beam_end_ly * scale

        pygame.draw.line(surface, ORANGE,
                         (int(ls_sx), int(ls_sy)),
                         (int(lbe_sx), int(lbe_sy)), 2)
        pygame.draw.circle(surface, ORANGE, (int(ls_sx), int(ls_sy)), 5)

        # Label jarak sensor kiri (mm)
        font_s = pygame.font.SysFont("Arial", 11, bold=True)
        lbl_left = font_s.render(f"{sensor_dist_left:.0f}mm", True, ORANGE)
        surface.blit(lbl_left, (int(lbe_sx) + 4, int(lbe_sy) - 8))

        # ----------------------------------------------------------------
        # 4. Sensor IR BELAKANG (cyan)
        # ----------------------------------------------------------------
        bs_wx = self.orig_x + self.ROBOT_RADIUS * bk_x
        bs_wy = self.orig_y + self.ROBOT_RADIUS * bk_y
        dist_back_raw = self._cast_ray_pixel(raw_lapangan, self.orig_x, self.orig_y, bk_x, bk_y)
        sensor_dist_back = max(0.0, dist_back_raw - self.ROBOT_RADIUS)

        beam_end_bx = self.orig_x + dist_back_raw * bk_x
        beam_end_by = self.orig_y + dist_back_raw * bk_y
        bs_sx  = offset_x + bs_wx * scale
        bs_sy  = bs_wy * scale
        bbe_sx = offset_x + beam_end_bx * scale
        bbe_sy = beam_end_by * scale

        pygame.draw.line(surface, CYAN,
                         (int(bs_sx), int(bs_sy)),
                         (int(bbe_sx), int(bbe_sy)), 2)
        pygame.draw.circle(surface, CYAN, (int(bs_sx), int(bs_sy)), 5)

        lbl_back = font_s.render(f"{sensor_dist_back:.0f}mm", True, CYAN)
        surface.blit(lbl_back, (int(bbe_sx) + 4, int(bbe_sy) - 8))

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
