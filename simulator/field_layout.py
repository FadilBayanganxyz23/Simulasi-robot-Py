"""
simulator/field_layout.py
=========================
Bertanggung jawab atas:
- Konstanta warna dan ukuran lapangan
- Pembuatan surface lapangan (generate_vector_field)
- Fungsi deteksi tabrakan berbasis piksel dan segmen dinding
- Singleton surface lapangan (raw_lapangan, scaled_lapangan, SCALE, offset_x)

Modul ini diinisialisasi SEKALI saat diimpor; Pygame harus sudah
di-init sebelum mengimpor modul ini.
"""

import pygame
import math

# ---------------------------------------------------------------------------
# Warna
# ---------------------------------------------------------------------------
WHITE  = (255, 255, 255)
BLACK  = (0,   0,   0)
RED    = (255, 0,   0)
GREEN  = (0,   255, 0)
BLUE   = (0,   100, 255)
YELLOW = (255, 215, 0)
GREY   = (80,  80,  80)

# ---------------------------------------------------------------------------
# Konstanta Lapangan
# ---------------------------------------------------------------------------
FIELD_OFFSET_X = 30
FIELD_OFFSET_Y = 30

# Posisi HOME robot (dalam koordinat world/pixel lapangan)
HOME_X = FIELD_OFFSET_X + 1100
HOME_Y = FIELD_OFFSET_Y + 2850


# ---------------------------------------------------------------------------
# Fungsi Gambar Elemen Lapangan
# ---------------------------------------------------------------------------

def draw_slider_box_h(surface, x, y, wall_on_right=False):
    """Gambar kotak slider horizontal (merah/putih)."""
    w, h = 250, 80
    box_x = x
    box_y = y - h // 2
    if wall_on_right:
        pygame.draw.rect(surface, WHITE, (box_x,         box_y, w // 2, h))
        pygame.draw.rect(surface, RED,   (box_x + w // 2, box_y, w // 2, h))
    else:
        pygame.draw.rect(surface, RED,   (box_x,         box_y, w // 2, h))
        pygame.draw.rect(surface, WHITE, (box_x + w // 2, box_y, w // 2, h))
    pygame.draw.rect(surface, BLACK, (box_x, box_y, w, h), 6)


def draw_slider_box_v(surface, x, y):
    """Gambar kotak slider vertikal (putih/merah)."""
    w, h = 80, 210
    box_x = x - w // 2
    box_y = y
    pygame.draw.rect(surface, WHITE, (box_x, box_y,           w, h // 2))
    pygame.draw.rect(surface, RED,   (box_x, box_y + h // 2,  w, h // 2))
    pygame.draw.rect(surface, BLACK, (box_x, box_y,           w, h),     6)


def generate_vector_field(surface):
    """
    Menggambar seluruh elemen lapangan ke surface:
    dinding luar, dinding dalam, rel slider, kotak slider, teks HOME.
    """
    ox = FIELD_OFFSET_X
    oy = FIELD_OFFSET_Y

    # 1. Dinding Pembatas Luar (tebal 30 mm)
    pygame.draw.line(surface, BLACK, (ox + 15,   oy),        (ox + 15,   oy + 4000), 30)
    pygame.draw.line(surface, BLACK, (ox + 1985, oy),        (ox + 1985, oy + 4000), 30)
    pygame.draw.line(surface, BLACK, (ox,        oy + 15),   (ox + 2000, oy + 15),   30)
    pygame.draw.line(surface, BLACK, (ox,        oy + 3985), (ox + 2000, oy + 3985), 30)

    # 2. Dinding Dalam Ruangan
    pygame.draw.line(surface, BLACK, (ox + 1000, oy + 30),   (ox + 1000, oy + 830),  10)
    pygame.draw.line(surface, BLACK, (ox + 650,  oy + 830),  (ox + 1000, oy + 830),  10)
    pygame.draw.line(surface, BLACK, (ox + 650,  oy + 830),  (ox + 650,  oy + 1080), 10)
    pygame.draw.line(surface, BLACK, (ox + 500,  oy + 1080), (ox + 500,  oy + 1880), 10)
    pygame.draw.line(surface, BLACK, (ox + 500,  oy + 1080), (ox + 650,  oy + 1080), 10)
    pygame.draw.line(surface, BLACK, (ox + 500,  oy + 1880), (ox + 1000, oy + 1880), 10)
    pygame.draw.line(surface, BLACK, (ox + 1620, oy + 830),  (ox + 1970, oy + 830),  10)
    pygame.draw.line(surface, BLACK, (ox + 800,  oy + 2500), (ox + 800,  oy + 3970), 10)
    pygame.draw.line(surface, BLACK, (ox + 800,  oy + 2500), (ox + 1400, oy + 2500), 10)
    pygame.draw.line(surface, BLACK, (ox + 800,  oy + 3200), (ox + 1400, oy + 3200), 10)

    # 3. Rel Slider dan Kotak Slider
    for y in [280, 430, 580]:
        pygame.draw.line(surface, BLACK, (ox + 500,  oy + y), (ox + 750,  oy + y), 10)
        draw_slider_box_h(surface, ox + 750,  oy + y, wall_on_right=True)

    for y in [280, 430, 580]:
        pygame.draw.line(surface, BLACK, (ox + 1470, oy + y), (ox + 1720, oy + y), 10)
        draw_slider_box_h(surface, ox + 1720, oy + y, wall_on_right=True)

    for y in [1330, 1480, 1630]:
        pygame.draw.line(surface, BLACK, (ox + 750,  oy + y), (ox + 1000, oy + y), 10)
        draw_slider_box_h(surface, ox + 500,  oy + y, wall_on_right=False)

    for y in [3420, 3570, 3720]:
        pygame.draw.line(surface, BLACK, (ox + 280,  oy + y), (ox + 530,  oy + y), 10)
        draw_slider_box_h(surface, ox + 30,   oy + y, wall_on_right=False)

    for x in [1100, 1400, 1700]:
        pygame.draw.line(surface, BLACK, (ox + x, oy + 3510), (ox + x, oy + 3760), 10)
        draw_slider_box_v(surface, ox + x, oy + 3760)

    # 4. Teks "HOME"
    font_home = pygame.font.SysFont("Arial", 110, bold=True)
    text_home = font_home.render("HOME", True, BLACK)
    text_rect = text_home.get_rect(center=(ox + 1100, oy + 2850))
    surface.blit(text_home, text_rect)


# ---------------------------------------------------------------------------
# Inisialisasi Surface Lapangan (dijalankan sekali saat import)
# ---------------------------------------------------------------------------

def build_field_surfaces(screen_w, screen_h):
    """
    Buat dan kembalikan (raw_lapangan, scaled_lapangan, SCALE, offset_x).
    Panggil setelah pygame.init() dan display.set_mode().
    """
    raw = pygame.Surface((2000 + 2 * FIELD_OFFSET_X,
                           4000 + 2 * FIELD_OFFSET_Y))
    raw.fill(WHITE)
    generate_vector_field(raw)

    scale  = screen_h / float(4000 + 2 * FIELD_OFFSET_Y)
    sw     = int((2000 + 2 * FIELD_OFFSET_X) * scale)
    scaled = pygame.transform.scale(raw, (sw, screen_h))
    off_x  = (screen_w - sw) // 2

    return raw, scaled, scale, off_x


# ---------------------------------------------------------------------------
# Fungsi Deteksi Tabrakan
# ---------------------------------------------------------------------------

def is_pixel_crossable(px, py):
    """Return True jika piksel (px,py) merupakan area yang boleh dilewati robot
    (misal area slider / area HOME terbuka)."""
    ox = FIELD_OFFSET_X
    oy = FIELD_OFFSET_Y

    if ox + 800 <= px <= ox + 1400 and oy + 2500 <= py <= oy + 3200:
        if abs(px - (ox + 800))  < 15: return False
        if abs(py - (oy + 2500)) < 15: return False
        if abs(py - (oy + 3200)) < 15: return False
        return True
    if ox + 490  <= px <= ox + 760  and oy + 230  <= py <= oy + 630:  return True
    if ox + 1460 <= px <= ox + 1730 and oy + 230  <= py <= oy + 630:  return True
    if ox + 740  <= px <= ox + 1010 and oy + 1280 <= py <= oy + 1700: return True
    if ox + 270  <= px <= ox + 540  and oy + 3350 <= py <= oy + 3800: return True
    if ox + 1090 <= px <= ox + 1740 and oy + 3430 <= py <= oy + 3760: return True
    return False


def is_in_slider_box(px, py):
    """Return True jika piksel (px,py) berada di dalam area kotak slider."""
    ox = FIELD_OFFSET_X
    oy = FIELD_OFFSET_Y

    for y in [280, 430, 580]:
        if ox + 750  <= px <= ox + 1000 and oy + y - 40 <= py <= oy + y + 40: return True
    for y in [280, 430, 580]:
        if ox + 1720 <= px <= ox + 1970 and oy + y - 40 <= py <= oy + y + 40: return True
    for y in [1330, 1480, 1630]:
        if ox + 500  <= px <= ox + 750  and oy + y - 40 <= py <= oy + y + 40: return True
    for y in [3420, 3570, 3720]:
        if ox + 30   <= px <= ox + 280  and oy + y - 40 <= py <= oy + y + 40: return True
    for x in [1100, 1400, 1700]:
        if ox + x - 40 <= px <= ox + x + 40 and oy + 3760 <= py <= oy + 3970: return True
    return False


def check_box_collision_circle(cx, cy, radius=50):
    """Return True jika lingkaran (cx,cy,radius) bertabrakan dengan kotak slider."""
    ox = FIELD_OFFSET_X
    oy = FIELD_OFFSET_Y

    def _overlap(cx, cy, r, rx, ry, rw, rh):
        clx = max(rx, min(cx, rx + rw))
        cly = max(ry, min(cy, ry + rh))
        return (cx - clx) ** 2 + (cy - cly) ** 2 < r * r

    for y in [280, 430, 580]:
        if _overlap(cx, cy, radius, ox + 750,  oy + y - 40, 250, 80): return True
    for y in [280, 430, 580]:
        if _overlap(cx, cy, radius, ox + 1720, oy + y - 40, 250, 80): return True
    for y in [1330, 1480, 1630]:
        if _overlap(cx, cy, radius, ox + 500,  oy + y - 40, 250, 80): return True
    for y in [3420, 3570, 3720]:
        if _overlap(cx, cy, radius, ox + 30,   oy + y - 40, 250, 80): return True
    for x in [1100, 1400, 1700]:
        if _overlap(cx, cy, radius, ox + x - 40, oy + 3760, 80, 210): return True
    return False


def check_wall_segments_collision(rx, ry, radius=202):
    """Return True jika lingkaran robot bertabrakan dengan dinding luar atau dalam."""
    ox = FIELD_OFFSET_X
    oy = FIELD_OFFSET_Y

    # Dinding luar
    if rx < ox + 30 + radius: return True
    if rx > ox + 1970 - radius: return True
    if ry < oy + 30 + radius: return True
    if ry > oy + 3970 - radius: return True

    walls = [
        # Dinding dalam ruangan
        (ox + 1000, oy + 30,   ox + 1000, oy + 830),
        (ox + 650,  oy + 830,  ox + 1000, oy + 830),
        (ox + 650,  oy + 830,  ox + 650,  oy + 1080),
        (ox + 500,  oy + 1080, ox + 500,  oy + 1880),
        (ox + 500,  oy + 1080, ox + 650,  oy + 1080),
        (ox + 500,  oy + 1880, ox + 1000, oy + 1880),
        (ox + 1620, oy + 830,  ox + 1970, oy + 830),
        # Dinding HOME
        (ox + 800,  oy + 2500, ox + 800,  oy + 3970),
        (ox + 800,  oy + 2500, ox + 1400, oy + 2500),
        (ox + 800,  oy + 3200, ox + 1400, oy + 3200),
    ]

    for x1, y1, x2, y2 in walls:
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0 and dy == 0:
            continue
        t = max(0.0, min(1.0, ((rx - x1) * dx + (ry - y1) * dy) / (dx * dx + dy * dy)))
        cx = x1 + t * dx
        cy = y1 + t * dy
        if (rx - cx) ** 2 + (ry - cy) ** 2 < radius ** 2:
            return True
    return False
