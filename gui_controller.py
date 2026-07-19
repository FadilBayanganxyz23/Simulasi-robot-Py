"""
gui_controller.py
=================
Entry point GUI pengontrol robot.

Hanya bertugas menginisialisasi Tkinter dan menjalankan SequenceGUI.
Semua logika UI ada di gui/app.py, semua logika socket ada di gui/logic.py.
"""

import tkinter as tk
from gui.app import SequenceGUI

if __name__ == "__main__":
    root = tk.Tk()
    app  = SequenceGUI(root)
    root.mainloop()
