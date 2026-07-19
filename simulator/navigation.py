"""
simulator/navigation.py
=======================
Bertanggung jawab atas:
- Grid rintangan (GRID_OBSTACLE) untuk A* pathfinding
- Algoritma A* (find_path_astar)
- Logika satu frame navigasi waypoint (step_navigation)

State navigasi dikelola melalui dict `NavState`:
    {
        "waypoints"    : list of (world_x, world_y),
        "index"        : int,
        "is_navigating": bool,
        "target_w"     : float atau None  (heading tujuan dalam derajat)
    }

Cara pakai di main loop:
    nav_state = make_nav_state()
    ...
    nav_vx, nav_vy, nav_vw, nav_ext = step_navigation(robot, nav_state, origin_angle)
"""

import math
import heapq

from simulator.field_layout import FIELD_OFFSET_X, FIELD_OFFSET_Y


# ---------------------------------------------------------------------------
# Grid Rintangan
# ---------------------------------------------------------------------------

GRID_W = 50
GRID_H = 100
GRID_OBSTACLE = [[False] * GRID_H for _ in range(GRID_W)]

def init_obstacle_grid(robot, raw_lapangan):
    """
    Isi GRID_OBSTACLE berdasarkan deteksi tabrakan robot.
    Panggil satu kali setelah robot dibuat.
    Menggunakan teknik Obstacle Inflation (safety margin 225mm) agar jalur A* 
    tidak mepet dengan rintangan asli (202mm).
    """
    global GRID_OBSTACLE
    ox = FIELD_OFFSET_X
    oy = FIELD_OFFSET_Y

    # Simpan nilai radius asli robot
    orig_collision_radius = robot.COLLISION_RADIUS
    orig_robot_radius = robot.ROBOT_RADIUS

    # Terapkan inflasi rintangan (safety buffer)
    # Kita gunakan 225mm (> 202mm radius fisik) agar rute menjaga jarak aman dari tembok
    robot.COLLISION_RADIUS = 225
    robot.ROBOT_RADIUS = 228

    from simulator.field_layout import check_box_collision_circle
    for i in range(GRID_W):
        for j in range(GRID_H):
            wx = ox + i * 40 + 20
            wy = oy + j * 40 + 20
            
            # Cek slider box dengan safety radius
            if check_box_collision_circle(wx, wy, radius=robot.COLLISION_RADIUS):
                GRID_OBSTACLE[i][j] = True
                continue
                
            hit = False
            for angle in [0, math.pi / 2, math.pi, -math.pi / 2]:
                if robot.check_collision(wx, wy, angle, raw_lapangan):
                    hit = True
                    break
            GRID_OBSTACLE[i][j] = hit

    # Kembalikan ke radius fisik asli untuk simulasi pergerakan riil robot
    robot.COLLISION_RADIUS = orig_collision_radius
    robot.ROBOT_RADIUS = orig_robot_radius



# ---------------------------------------------------------------------------
# A* Pathfinding
# ---------------------------------------------------------------------------

def find_path_astar(start_w, goal_w):
    """
    Cari jalur terpendek dari start_w ke goal_w menggunakan A*.

    Parameter:
        start_w, goal_w : tuple (world_x, world_y) dalam piksel lapangan

    Return:
        List of (world_x, world_y) waypoints, atau [] jika tidak ditemukan.
    """
    ox = FIELD_OFFSET_X
    oy = FIELD_OFFSET_Y

    def to_grid(wx, wy):
        gi = max(0, min(GRID_W - 1, int((wx - ox) / 40)))
        gj = max(0, min(GRID_H - 1, int((wy - oy) / 40)))
        return gi, gj

    def nearest_free(gx, gy, max_r=40):
        if not GRID_OBSTACLE[gx][gy]:
            return gx, gy
        for r in range(1, max_r + 1):
            for di in range(-r, r + 1):
                for dj in range(-r, r + 1):
                    nx, ny = gx + di, gy + dj
                    if 0 <= nx < GRID_W and 0 <= ny < GRID_H and not GRID_OBSTACLE[nx][ny]:
                        return nx, ny
        return gx, gy

    sg = nearest_free(*to_grid(*start_w))
    gg = nearest_free(*to_grid(*goal_w))

    open_set = []
    heapq.heappush(open_set, (0.0, sg))
    came_from = {}
    g_score   = {sg: 0.0}
    f_score   = {sg: math.hypot(sg[0] - gg[0], sg[1] - gg[1])}

    directions = [
        (0, 1, 1.0), (0, -1, 1.0), (1, 0, 1.0), (-1, 0, 1.0),
        (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414),
    ]

    while open_set:
        current = heapq.heappop(open_set)[1]
        if current == gg:
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.append(sg)
            path.reverse()
            return [(ox + i * 40 + 20, oy + j * 40 + 20) for i, j in path]

        for di, dj, cost in directions:
            nb = (current[0] + di, current[1] + dj)
            if not (0 <= nb[0] < GRID_W and 0 <= nb[1] < GRID_H):
                continue
            if GRID_OBSTACLE[nb[0]][nb[1]]:
                continue
            if abs(di) == 1 and abs(dj) == 1:
                if (GRID_OBSTACLE[current[0] + di][current[1]] or
                        GRID_OBSTACLE[current[0]][current[1] + dj]):
                    continue
            tg = g_score[current] + cost
            if nb not in g_score or tg < g_score[nb]:
                came_from[nb] = current
                g_score[nb]   = tg
                f_score[nb]   = tg + math.hypot(nb[0] - gg[0], nb[1] - gg[1])
                heapq.heappush(open_set, (f_score[nb], nb))
    return []


# ---------------------------------------------------------------------------
# State Navigasi
# ---------------------------------------------------------------------------

def make_nav_state():
    """Buat dict state navigasi awal (tidak aktif)."""
    return {
        "waypoints":     [],
        "index":         0,
        "is_navigating": False,
        "target_w":      None,
    }


def start_navigation(nav_state, robot, home_x, home_y,
                     target_x, target_y, target_w=None):
    """
    Mulai navigasi otomatis dari posisi robot saat ini ke (target_x, target_y).

    Parameter:
        nav_state : dict state navigasi (akan dimodifikasi in-place)
        robot     : SimRobot
        home_x/y  : posisi HOME dalam koordinat world
        target_x  : target Vx (Maju/Mundur) dalam mm, relatif ke HOME
        target_y  : target Vy (Geser) dalam mm, relatif ke HOME
        target_w  : target heading dalam derajat (None = tidak perlu rotasi)
    """
    world_tx = target_x + home_x
    world_ty = home_y - target_y

    path = find_path_astar((robot.orig_x, robot.orig_y), (world_tx, world_ty))
    if path:
        nav_state["waypoints"]     = path
        nav_state["index"]         = 0
        nav_state["is_navigating"] = True
        nav_state["target_w"]      = target_w
    else:
        nav_state["is_navigating"] = False
        nav_state["waypoints"]     = []


def cancel_navigation(nav_state):
    """Batalkan navigasi dan reset state."""
    nav_state["is_navigating"] = False
    nav_state["waypoints"]     = []
    nav_state["target_w"]      = None


def step_navigation(robot, nav_state, origin_angle):
    """
    Hitung (nav_vx, nav_vy, nav_vw, nav_ext) untuk satu frame navigasi.

    Return:
        Tuple (vx, vy, vw, use_ext) yang langsung bisa diteruskan ke robot.update().
    """
    if not nav_state["is_navigating"] or not nav_state["waypoints"]:
        return 0.0, 0.0, 0.0, False

    NAV_SPEED   = 15.0
    SPEED_SCALE = 60.0 / 40.0
    ARRIVE_DIST = 25.0

    target_pt = nav_state["waypoints"][nav_state["index"]]
    dx = target_pt[0] - robot.orig_x
    dy = target_pt[1] - robot.orig_y
    dist = math.hypot(dx, dy)

    last_waypoint = nav_state["index"] >= len(nav_state["waypoints"]) - 1

    if not last_waypoint:
        # Waypoint antara: translasi lurus, tidak berotasi
        if dist < ARRIVE_DIST:
            nav_state["index"] += 1
            return 0.0, 0.0, 0.0, True
        vx_g = -(dy / dist) * NAV_SPEED * SPEED_SCALE
        vy_g =  (dx / dist) * NAV_SPEED * SPEED_SCALE
        return vx_g, vy_g, 0.0, True

    else:
        # Waypoint terakhir: translasi dulu, lalu rotasi (jika ada target_w)
        target_w = nav_state["target_w"]

        if dist >= ARRIVE_DIST:
            vx_g = -(dy / dist) * NAV_SPEED * SPEED_SCALE
            vy_g =  (dx / dist) * NAV_SPEED * SPEED_SCALE
            return vx_g, vy_g, 0.0, True

        # Sudah tiba di koordinat tujuan
        if target_w is None:
            # Tidak perlu rotasi → selesai
            cancel_navigation(nav_state)
            return 0.0, 0.0, 0.0, False

        # Hitung selisih heading
        # target_w dalam derajat relatif terhadap origin_angle (konvensi UI)
        target_rad = origin_angle - math.radians(target_w)
        diff_rad   = math.atan2(math.sin(target_rad - robot.angle),
                                math.cos(target_rad - robot.angle))
        diff_deg   = math.degrees(diff_rad)

        if abs(diff_deg) > 2.0:
            rot_dir = 1.0 if diff_rad > 0 else -1.0
            vw = rot_dir * min(5.0, abs(diff_deg) / 18.0)
            return 0.0, 0.0, vw, True
        else:
            # Rotasi selesai
            cancel_navigation(nav_state)
            return 0.0, 0.0, 0.0, False
