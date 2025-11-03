import tkinter as tk
from tkinter import ttk, messagebox
from .spacegroup_selector import select_spacegroup
from .element_selector import select_element
import matplotlib

import sys

import cProfile
import pstats

class MainApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PyXtal System Builder")
        self.geometry("400x200")
        ttk.Label(self, text="PyXtal GUI System Builder", font=("Arial", 14)).pack(pady=20)
        ttk.Button(self, text="Create System by Spacegroup", command=self.create_system).pack(pady=10)

        def run():
            self.withdraw()
            select_element(master=self)
            profiler = cProfile.Profile()
            profiler.enable()

            self.create_system()

            profiler.disable()
            stats = pstats.Stats(profiler)
            stats.sort_stats('cumtime')  # sort by total time
            stats.print_stats(200)     # show top 20 functions

            sys.exit(0)

        self.after(0, run)

    def create_system(self):
        sg = select_spacegroup(master = self)
        if sg:
            pass
            #messagebox.showinfo("Selected Space Group", f"You chose {sg.number}: {sg.symbol}")
        else:
            pass
            #messagebox.showwarning("No Selection", "No space group was selected.")


if __name__ == "__main__":
    app = MainApp()
    app.mainloop()
    

    