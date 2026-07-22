import subprocess
import sys
import time
import os

def get_executable_dir():
    """Mengembalikan direktori tempat executable atau script berada."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def main():
    print("Memulai Simulator dan GUI Controller...")
    
    base_dir = get_executable_dir()
    
    # Cek apakah dijalankan dari file .exe (PyInstaller) atau script .py biasa
    if getattr(sys, 'frozen', False):
        sim_cmd = [os.path.join(base_dir, "simul_jalan.exe")]
        gui_cmd = [os.path.join(base_dir, "gui_controller.exe")]
    else:
        sim_cmd = [sys.executable, os.path.join(base_dir, "simul_jalan.py")]
        gui_cmd = [sys.executable, os.path.join(base_dir, "gui_controller.py")]
    
    # Menjalankan simulator (sebagai server)
    sim_process = subprocess.Popen(sim_cmd)
    
    # Tunggu sebentar agar server socket di simulator siap menerima koneksi
    time.sleep(1)
    
    # Menjalankan GUI Controller (sebagai klien)
    gui_process = subprocess.Popen(gui_cmd)
    
    try:
        # Tunggu sampai salah satu aplikasi ditutup oleh user
        while sim_process.poll() is None and gui_process.poll() is None:
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        print("\nMenghentikan program...")
        
    finally:
        # Hentikan paksa proses yang masih berjalan agar tidak ada zombie process
        if sim_process.poll() is None:
            sim_process.terminate()
        if gui_process.poll() is None:
            gui_process.terminate()
            
        print("Simulator dan GUI Controller berhasil ditutup.")

if __name__ == "__main__":
    main()

