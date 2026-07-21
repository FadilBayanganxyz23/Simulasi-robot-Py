"""
simulator/vision.py
===================
Modul Pemrosesan Visi Komputer & Deteksi Warna (OpenCV + Pygame).

Fungsi utama:
- perform_scan_stand: Scanning 1 stand presisi tinggi (ultra-narrow crop 36px)
- perform_scan_almari: Scanning 3 slot sekaligus pada almari gudang (A1/A2)
- load_hsv_calibration: Membaca nilai kalibrasi warna HSV dari file json
"""

import pygame
import math
import cv2
import numpy as np
import json


def load_hsv_calibration():
    """Membaca nilai range HSV dari file hsv_calibration.json jika tersedia."""
    hsv_ranges = {
        "RED":   {"h": [0, 10],   "s": [100, 255], "v": [100, 255]},
        "GREEN": {"h": [40, 80],  "s": [100, 255], "v": [100, 255]},
        "BLUE":  {"h": [100, 140], "s": [100, 255], "v": [100, 255]}
    }
    try:
        with open("hsv_calibration.json", "r") as f:
            loaded = json.load(f)
            for k, v in loaded.items():
                if k in hsv_ranges:
                    hsv_ranges[k].update(v)
    except Exception:
        pass
    return hsv_ranges


def perform_scan_stand(robot_obj, screen_surf, offset_x_val, scale_val):
    """
    Melakukan scanning warna kubus pada 1 stand tepat di depan robot.
    Menggunakan crop ultra-sempit (36px width x 90px height) agar tidak ada
    bocoran warna dari stand tetangga di sebelah kiri/kanan.
    """
    rx = int(robot_obj.orig_x * scale_val) + offset_x_val
    ry = int(robot_obj.orig_y * scale_val)
    
    cam_surf = pygame.Surface((300, 300))
    cam_surf.blit(screen_surf, (0, 0), (rx - 150, ry - 150, 300, 300))
    
    deg = math.degrees(robot_obj.angle)
    rotated_surf = pygame.transform.rotate(cam_surf, deg + 90)
    w, h = rotated_surf.get_size()
    
    # Crop khusus strip tegak ultra-sempit (lebar 36px, tinggi 90px) HANYA 1 garis stand & kubus di atasnya
    final_cam = rotated_surf.subsurface((w//2 - 18, h//2 - 110, 36, 90))
    
    img_string = pygame.image.tostring(final_cam, "RGB")
    img_arr = np.frombuffer(img_string, dtype=np.uint8).reshape((90, 36, 3))
    
    hsv_ranges = load_hsv_calibration()

    img_bgr = cv2.cvtColor(img_arr, cv2.COLOR_RGB2BGR)
    img_hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

    for color_name in ["RED", "GREEN", "BLUE"]:
        h_range = hsv_ranges[color_name]["h"]
        s_range = hsv_ranges[color_name]["s"]
        v_range = hsv_ranges[color_name]["v"]
        
        lower1 = np.array([h_range[0], s_range[0], v_range[0]])
        upper1 = np.array([h_range[1], s_range[1], v_range[1]])
        
        if h_range[0] > h_range[1]:
            lower2 = np.array([0, s_range[0], v_range[0]])
            upper2 = np.array([h_range[1], s_range[1], v_range[1]])
            lower1 = np.array([h_range[0], s_range[0], v_range[0]])
            upper1 = np.array([179, s_range[1], v_range[1]])
            mask1 = cv2.inRange(img_hsv, lower1, upper1)
            mask2 = cv2.inRange(img_hsv, lower2, upper2)
            mask = mask1 | mask2
        else:
            mask = cv2.inRange(img_hsv, lower1, upper1)
            
        if cv2.countNonZero(mask) > 15: # threshold jumlah pixel kubus
            return color_name
            
    return "EMPTY"


def perform_scan_almari(robot_obj, screen_surf, offset_x_val, scale_val, label_prefix):
    """
    Melakukan scanning multi-object (S1, S2, S3) pada rak Almari Gudang.
    Mengembalikan list 3 warna: [s1, s2, s3].
    """
    rx = int(robot_obj.orig_x * scale_val) + offset_x_val
    ry = int(robot_obj.orig_y * scale_val)
    
    cam_surf = pygame.Surface((300, 300))
    cam_surf.blit(screen_surf, (0, 0), (rx - 150, ry - 150, 300, 300))
    
    deg = math.degrees(robot_obj.angle)
    rotated_surf = pygame.transform.rotate(cam_surf, deg + 90)
    w, h = rotated_surf.get_size()
    final_cam = rotated_surf.subsurface((w//2 - 100, h//2 - 100, 200, 200))
    
    img_string = pygame.image.tostring(final_cam, "RGB")
    img_arr = np.frombuffer(img_string, dtype=np.uint8).reshape((200, 200, 3))
    
    hsv_ranges = load_hsv_calibration()

    img_bgr = cv2.cvtColor(img_arr, cv2.COLOR_RGB2BGR)
    img_hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    row_hsv = img_hsv[0:75, :] # Crop area depan robot di luar tubuh robot (y < 75)
    
    detected_objs = []
    
    for color_name in ["RED", "GREEN", "BLUE"]:
        h_range = hsv_ranges[color_name]["h"]
        s_range = hsv_ranges[color_name]["s"]
        v_range = hsv_ranges[color_name]["v"]
        
        lower1 = np.array([h_range[0], s_range[0], v_range[0]])
        upper1 = np.array([h_range[1], s_range[1], v_range[1]])
        
        if h_range[0] > h_range[1]:
            lower2 = np.array([0, s_range[0], v_range[0]])
            upper2 = np.array([h_range[1], s_range[1], v_range[1]])
            lower1 = np.array([h_range[0], s_range[0], v_range[0]])
            upper1 = np.array([179, s_range[1], v_range[1]])
            mask1 = cv2.inRange(row_hsv, lower1, upper1)
            mask2 = cv2.inRange(row_hsv, lower2, upper2)
            mask = mask1 | mask2
        else:
            mask = cv2.inRange(row_hsv, lower1, upper1)
            
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Ambil semua kontur per warna untuk mendeteksi banyak kubus sekaligus (misal S2 & S3 sama-sama RED)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > 30:
                x, y, w, h = cv2.boundingRect(cnt)
                cx = x + w // 2
                detected_objs.append({"color": color_name, "cx": cx})
                
    # Inisialisasi S1, S2, S3 sebagai EMPTY
    s1, s2, s3 = "EMPTY", "EMPTY", "EMPTY"
    
    # Petakan koordinat X ke S1 (1x / terkecil < 83), S2 (2x / tengah 83..117), S3 (3x / terbesar > 117)
    for obj in detected_objs:
        cx = obj["cx"]
        if cx < 83:
            s1 = obj["color"]
        elif cx > 117:
            s3 = obj["color"]
        else:
            s2 = obj["color"]
            
    return [s1, s2, s3]
