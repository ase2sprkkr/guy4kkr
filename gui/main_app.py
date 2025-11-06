import tkinter as tk
from tkinter import ttk, messagebox
from .spacegroup_selector import select_spacegroup
from .element_selector import select_element
from .element_assignment import select_site_elements
from .common import chain_dialogs
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
        profile = False

        def run():
            self.withdraw()
            profile = True
            if profile:
                profiler = cProfile.Profile()
                profiler.enable()

            chain_dialogs(
                select_spacegroup,
                select_site_elements,
                all = { 'master' : self },
                back = True
            )

            if profile:
                profiler.disable()
                stats = pstats.Stats(profiler)
                stats.sort_stats('cumtime')  # sort by total time
                stats.print_stats(200)     # show top 20 functions
                profiler.dump_stats("profile_results.prof")

            sys.exit(0)

        self.after(0, run)

    def create_system(self):
        return select_spacegroup(master = self)
        


if __name__ == "__main__":
    app = MainApp()
    app.mainloop()
    

    