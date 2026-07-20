import subprocess
import sys
import time

def main():
    print("Memulai Simulator dan GUI Controller...")
    
    # Menjalankan simulator (sebagai server)
    sim_process = subprocess.Popen([sys.executable, "simul_jalan.py"])
    
    # Tunggu sebentar agar server socket di simulator siap menerima koneksi
    time.sleep(1)
    
    # Menjalankan GUI Controller (sebagai klien)
    gui_process = subprocess.Popen([sys.executable, "gui_controller.py"])
    
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
