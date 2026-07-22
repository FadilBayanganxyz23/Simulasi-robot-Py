"""
build_exe.py
============
Script otomatis untuk meng-compile project Simul Lane Trace menjadi file .exe.
Akan menghasilkan folder 'dist/RobotSimulator' yang berisi:
- main.exe
- simul_jalan.exe
- gui_controller.exe
- file aset (presets.json, hsv_calibration.json, notes.txt, gui_background.jpg)
"""

import os
import shutil
import subprocess
import sys

def run(cmd):
    print(f"\n[BUILD] Running: {cmd}")
    res = subprocess.run(cmd, shell=True)
    if res.returncode != 0:
        print(f"[ERROR] Command failed with return code {res.returncode}")
        sys.exit(res.returncode)

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(base_dir, "dist", "RobotSimulator")
    build_temp_dir = os.path.join(base_dir, "build")
    
    print("==================================================")
    print(" Memulai Build .EXE Pilihan 2 (Multi-EXE Bundle) ")
    print("==================================================")

    # 1. Pastikan PyInstaller terinstall
    try:
        import PyInstaller
    except ImportError:
        print("[INFO] PyInstaller belum terinstall. Menginstall pyinstaller...")
        run(f'"{sys.executable}" -m pip install pyinstaller')

    # Bersihkan folder dist/RobotSimulator jika sudah ada
    if os.path.exists(dist_dir):
        print(f"[INFO] Membersihkan folder build lama: {dist_dir}")
        shutil.rmtree(dist_dir, ignore_errors=True)
        
    os.makedirs(dist_dir, exist_ok=True)

    # 2. Build simul_jalan.py -> simul_jalan.exe
    cmd_sim = (
        f'"{sys.executable}" -m PyInstaller '
        f'--noconfirm --onefile --windowed '
        f'--distpath "{dist_dir}" '
        f'--workpath "{build_temp_dir}" '
        f'--name "simul_jalan" '
        f'"{os.path.join(base_dir, "simul_jalan.py")}"'
    )
    run(cmd_sim)

    # 3. Build gui_controller.py -> gui_controller.exe
    cmd_gui = (
        f'"{sys.executable}" -m PyInstaller '
        f'--noconfirm --onefile --windowed '
        f'--distpath "{dist_dir}" '
        f'--workpath "{build_temp_dir}" '
        f'--name "gui_controller" '
        f'"{os.path.join(base_dir, "gui_controller.py")}"'
    )
    run(cmd_gui)

    # 4. Build main.py -> main.exe
    cmd_main = (
        f'"{sys.executable}" -m PyInstaller '
        f'--noconfirm --onefile '
        f'--distpath "{dist_dir}" '
        f'--workpath "{build_temp_dir}" '
        f'--name "main" '
        f'"{os.path.join(base_dir, "main.py")}"'
    )
    run(cmd_main)

    # 5. Salin file pendukung (presets, hsv, notes, gambar) ke folder dist/RobotSimulator
    files_to_copy = ["presets.json", "hsv_calibration.json", "notes.txt", "gui_background.jpg"]
    print("\n[INFO] Menyalin file aset dan konfigurasi ke folder output...")
    for file_name in files_to_copy:
        src = os.path.join(base_dir, file_name)
        dst = os.path.join(dist_dir, file_name)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f" - Copied {file_name}")
        else:
            print(f" - Warning: {file_name} tidak ditemukan, dilewati.")

    print("\n==================================================")
    print(f" SUCCESS! Paket .exe berhasil dibuat di:")
    print(f" {dist_dir}")
    print("==================================================")
    print("Untuk menjalankan aplikasi, cukup buka folder di atas dan jalankan 'main.exe'.")

if __name__ == "__main__":
    main()
