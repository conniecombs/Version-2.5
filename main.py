# main.py
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog, ttk, colorchooser
from tkinterdnd2 import DND_FILES, TkinterDnD
from PIL import Image, ImageTk
import threading
import queue
import os
import sys
import keyring
import pyperclip
import subprocess
import platform
import time
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# Local Imports
from modules import config
from modules import api
from modules.widgets import ScrollableFrame, LogWindow, CollapsibleGroupFrame, MouseWheelComboBox
from modules.gallery_manager import GalleryManager
from modules.settings_manager import SettingsManager
from modules.template_manager import TemplateManager, TemplateEditor
from modules.upload_manager import UploadManager
from modules.utils import ContextUtils
from modules.path_validator import PathValidator, PathValidationError
from loguru import logger

# Tkinter can hit the default limit (1000) when rendering thousands of widgets.
sys.setrecursionlimit(config.RECURSION_LIMIT) 

# Configure CustomTkinter
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

# --- Main Application ---
class UploaderApp(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)
        self.title(f"Connie's Uploader Ultimate {config.APP_VERSION}")
        self.geometry("1250x850")
        self.minsize(1050, 720)
        
        # Menu Var
        self.menu_thread_var = tk.IntVar(value=5)
        self.var_show_previews = tk.BooleanVar(value=True) # <--- NEW: Preview Toggle

        # ThreadPoolExecutor for Thumbnail Generation
        # Max workers controls how many folders are processed concurrently.
        self.thumb_executor = ThreadPoolExecutor(max_workers=config.THUMBNAIL_WORKER_THREADS)

        # Icon
        try:
            ico_path = config.resource_path("logo.ico")
            png_path = config.resource_path("logo.png")
            if os.path.exists(ico_path):
                self.iconbitmap(ico_path)
            elif os.path.exists(png_path):
                icon_image = Image.open(png_path)
                photo = ImageTk.PhotoImage(icon_image)
                self.iconphoto(True, photo)
        except Exception as e:
            print(f"Icon load warning: {e}")

        # Managers
        self.settings_mgr = SettingsManager()
        self.settings = self.settings_mgr.load()
        self.template_mgr = TemplateManager()
        
        # State
        self.progress_queue = queue.Queue()
        self.ui_queue = queue.Queue()
        self.result_queue = queue.Queue()
        
        self.cancel_event = threading.Event()
        self.lock = threading.Lock()
        
        # Initialize UploadManager (Modular Logic)
        self.upload_manager = UploadManager(self.progress_queue, self.result_queue, self.cancel_event)
        
        self.file_widgets = {} 
        self.groups = []       
        self.results = []
        self.log_cache = []
        self.image_refs = []
        self.log_window_ref = None
        self.clipboard_buffer = []
        self.upload_total = 0
        self.upload_count = 0
        self.is_uploading = False
        self.current_output_files = []
        self.pix_galleries_to_finalize = [] 
        
        # Auth
        self.turbo_cookies = None
        self.turbo_endpoint = None
        self.turbo_upload_id = None
        self.vipr_session = None
        self.vipr_meta = None
        self.vipr_galleries_map = {}

        self._load_credentials()
        self._create_menu()
        self._create_layout()
        self._apply_settings()
        
        # DnD
        self.drop_target_register(DND_FILES)
        self.dnd_bind('<<Drop>>', self.drop_files)
        
        # CLI - Securely validate command line argument
        if len(sys.argv) > 1:
            try:
                validated_path = PathValidator.validate_input_path(sys.argv[1])
                self.after(500, lambda: self._process_files([str(validated_path)]))
            except PathValidationError as e:
                logger.error(f"Invalid CLI argument: {e}")
                messagebox.showerror("Invalid Path", f"Cannot process path from command line:\n{e}")
        
        self.after(100, self.update_ui_loop)

    def _load_credentials(self):
        self.creds = {
            'imx_api': keyring.get_password(config.KEYRING_SERVICE_API, "api") or "",
            'imx_user': keyring.get_password(config.KEYRING_SERVICE_USER, "user") or "",
            'imx_pass': keyring.get_password(config.KEYRING_SERVICE_PASS, "pass") or "",
            'turbo_user': keyring.get_password("ImageUploader:turbo_user", "user") or "",
            'turbo_pass': keyring.get_password("ImageUploader:turbo_pass", "pass") or "",
            'vipr_user': keyring.get_password(config.KEYRING_SERVICE_VIPR_USER, "user") or "",
            'vipr_pass': keyring.get_password(config.KEYRING_SERVICE_VIPR_PASS, "pass") or ""
        }

    def _create_menu(self):
        menubar = tk.Menu(self)
        self.configure(menu=menubar)
        
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Add Files", command=self.add_files)
        file_menu.add_command(label="Add Folder", command=self.add_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit)
        
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Template Editor", command=self.open_template_editor)
        tools_menu.add_command(label="Set Credentials", command=self.open_creds_dialog)
        tools_menu.add_command(label="Manage Galleries", command=self.open_gallery_manager)
        
        thread_menu = tk.Menu(tools_menu, tearoff=0)
        tools_menu.add_cascade(label="Set Thread Limit", menu=thread_menu)
        for i in range(1, 11):
            thread_menu.add_radiobutton(label=f"{i} Threads", value=i, variable=self.menu_thread_var, command=lambda n=i: self.set_global_threads(n))

        tools_menu.add_separator()
        tools_menu.add_command(label="Install Context Menu", command=ContextUtils.install_menu)
        
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Execution Log", command=self.toggle_log)
        view_menu.add_separator()
        # <--- NEW: Preview Toggle Menu Item
        view_menu.add_checkbutton(label="Show Image Previews", onvalue=True, offvalue=False, variable=self.var_show_previews)

    def set_global_threads(self, n):
        self.menu_thread_var.set(n)
        if hasattr(self, 'var_imx_threads'): self.var_imx_threads.set(n)
        if hasattr(self, 'var_pix_threads'): self.var_pix_threads.set(n)
        if hasattr(self, 'var_turbo_threads'): self.var_turbo_threads.set(n)
        if hasattr(self, 'var_vipr_threads'): self.var_vipr_threads.set(n)

    def open_template_editor(self):
        # Callback to sync Main Window when Editor saves
        def on_update(new_key):
            # Refresh values
            keys = self.template_mgr.get_all_keys()
            self.cb_output_format.configure(values=keys)
            # Select the new key
            self.var_format.set(new_key)
            self.cb_output_format.set(new_key)

        TemplateEditor(
            self, 
            self.template_mgr, 
            current_mode=self.var_format.get(), # Pass current selection
            data_callback=self.get_preview_data,
            update_callback=on_update # Pass update logic
        )

    def get_preview_data(self):
        if not self.groups: return None, None, None
        grp = next((g for g in self.groups if g.files), None)
        if not grp: return None, None, None
        try: current_tab = self.notebook.get()
        except: current_tab = "imx.to"
        size = "200"
        try:
            if current_tab == "imx.to": size = self.var_imx_thumb.get()
            elif current_tab == "pixhost.to": size = self.var_pix_thumb.get()
            elif current_tab == "turboimagehost": size = self.var_turbo_thumb.get()
            elif current_tab == "vipr.im":
                val = self.var_vipr_thumb.get()
                size = val.split('x')[0] if 'x' in val else val
        except: pass
        return grp.files, grp.title, size

    def on_gallery_created(self, service, gid):
        if service == "imx.to":
            self.ent_imx_gal.delete(0, "end")
            self.ent_imx_gal.insert(0, gid)
            self.notebook.set("imx.to")
        elif service == "pixhost.to":
            self.ent_pix_hash.delete(0, "end")
            self.ent_pix_hash.insert(0, gid)
            self.notebook.set("pixhost.to")
        elif service == "vipr.im":
            self.refresh_vipr_galleries(select_id=gid)

    def open_gallery_manager(self):
        GalleryManager(self, self.creds, callback=self.on_gallery_created)

    def open_creds_dialog(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Service Credentials")
        dlg.geometry("450x380")
        dlg.transient(self)
        nb = ctk.CTkTabview(dlg)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        nb.add("imx.to")
        tab_imx = nb.tab("imx.to")
        ctk.CTkLabel(tab_imx, text="IMX Upload API Key:", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        imx_api_var = ctk.StringVar(value=self.creds['imx_api'])
        ctk.CTkEntry(tab_imx, textvariable=imx_api_var, show="*").pack(fill="x", pady=5)
        
        ctk.CTkLabel(tab_imx, text="IMX Gallery Manager:", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(10,0))
        ctk.CTkLabel(tab_imx, text="Username:").pack(anchor="w")
        imx_user_var = ctk.StringVar(value=self.creds['imx_user'])
        ctk.CTkEntry(tab_imx, textvariable=imx_user_var).pack(fill="x")
        ctk.CTkLabel(tab_imx, text="Password:").pack(anchor="w")
        imx_pass_var = ctk.StringVar(value=self.creds['imx_pass'])
        ctk.CTkEntry(tab_imx, textvariable=imx_pass_var, show="*").pack(fill="x")

        nb.add("Turbo")
        tab_turbo = nb.tab("Turbo")
        ctk.CTkLabel(tab_turbo, text="Login Optional", text_color="red").pack(anchor="w", pady=5)
        ctk.CTkLabel(tab_turbo, text="Username:").pack(anchor="w")
        turbo_user_var = ctk.StringVar(value=self.creds['turbo_user'])
        ctk.CTkEntry(tab_turbo, textvariable=turbo_user_var).pack(fill="x")
        ctk.CTkLabel(tab_turbo, text="Password:").pack(anchor="w")
        turbo_pass_var = ctk.StringVar(value=self.creds['turbo_pass'])
        ctk.CTkEntry(tab_turbo, textvariable=turbo_pass_var, show="*").pack(fill="x")

        nb.add("Vipr")
        tab_vipr = nb.tab("Vipr")
        ctk.CTkLabel(tab_vipr, text="Username:").pack(anchor="w")
        vipr_user_var = ctk.StringVar(value=self.creds['vipr_user'])
        ctk.CTkEntry(tab_vipr, textvariable=vipr_user_var).pack(fill="x")
        ctk.CTkLabel(tab_vipr, text="Password:").pack(anchor="w")
        vipr_pass_var = ctk.StringVar(value=self.creds['vipr_pass'])
        ctk.CTkEntry(tab_vipr, textvariable=vipr_pass_var, show="*").pack(fill="x")

        btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=10)
        
        def save_all():
            keyring.set_password(config.KEYRING_SERVICE_API, "api", imx_api_var.get().strip())
            keyring.set_password(config.KEYRING_SERVICE_USER, "user", imx_user_var.get().strip())
            keyring.set_password(config.KEYRING_SERVICE_PASS, "pass", imx_pass_var.get().strip())
            keyring.set_password("ImageUploader:turbo_user", "user", turbo_user_var.get().strip())
            keyring.set_password("ImageUploader:turbo_pass", "pass", turbo_pass_var.get().strip())
            keyring.set_password(config.KEYRING_SERVICE_VIPR_USER, "user", vipr_user_var.get().strip())
            keyring.set_password(config.KEYRING_SERVICE_VIPR_PASS, "pass", vipr_pass_var.get().strip())
            self._load_credentials()
            messagebox.showinfo("Success", "All credentials updated!")
            dlg.destroy()

        ctk.CTkButton(btn_frame, text="Save All", command=save_all).pack(side="right", padx=5)
        ctk.CTkButton(btn_frame, text="Cancel", command=dlg.destroy, fg_color="gray").pack(side="right")

    def refresh_vipr_galleries(self, select_id=None):
        if not self.creds['vipr_user']:
            messagebox.showerror("Error", "Vipr credentials missing.")
            return
        def _refresh():
            try:
                self.log("Vipr: Logging in...")
                client = api.create_resilient_client() # Direct API call
                self.vipr_session = api.vipr_login(self.creds['vipr_user'], self.creds['vipr_pass'], client=client)
                if not self.vipr_session: return
                
                self.log("Vipr: Fetching metadata...")
                meta = api.get_vipr_metadata(self.vipr_session)
                if meta and meta['galleries']:
                    self.vipr_galleries_map = {g['name']: g['id'] for g in meta['galleries']}
                    gal_names = ["None"] + list(self.vipr_galleries_map.keys())
                    
                    def update_cb():
                        self.cb_vipr_gallery.configure(values=gal_names)
                        if select_id:
                            found = next((n for n, i in self.vipr_galleries_map.items() if i == select_id), None)
                            if found: self.cb_vipr_gallery.set(found)
                        else:
                            self.cb_vipr_gallery.set(gal_names[0])
                    self.after(0, update_cb)
                    self.vipr_meta = meta
                else:
                    self.log("Vipr: No galleries found.")
            except Exception as e: self.log(f"Vipr Error: {e}")
        threading.Thread(target=_refresh, daemon=True).start()

    def _create_layout(self):
        main_container = ctk.CTkFrame(self)
        main_container.pack(fill="both", expand=True, padx=15, pady=15)
        
        # Left Sidebar
        self.settings_frame_container = ctk.CTkFrame(main_container, width=300)
        self.settings_frame_container.pack(side="left", fill="y", padx=(0, 10))
        
        ctk.CTkLabel(self.settings_frame_container, text="Settings", font=("Segoe UI", 16, "bold")).pack(pady=10, padx=10, anchor="w")
        
        # --- OUTPUT SETTINGS FRAME (Cleaned up) ---
        out_frame = ctk.CTkFrame(self.settings_frame_container)
        out_frame.pack(fill="x", padx=10, pady=5)
        
        # Renamed to clarify this is for the TEXT file, not the image geometry
        ctk.CTkLabel(out_frame, text="Link Style / Template").pack(pady=2)
        
        self.var_format = ctk.StringVar(value="BBCode")
        
        # Single ComboBox instance
        self.cb_output_format = MouseWheelComboBox(out_frame, variable=self.var_format, values=self.template_mgr.get_all_keys(), state="readonly")
        self.cb_output_format.pack(fill="x", padx=5, pady=5)
        
        self.var_auto_copy = ctk.BooleanVar()
        ctk.CTkCheckBox(out_frame, text="Auto-copy to clipboard", variable=self.var_auto_copy).pack(anchor="w", padx=5, pady=2)
        self.var_auto_gallery = ctk.BooleanVar()
        ctk.CTkCheckBox(out_frame, text="One Gallery Per Folder", variable=self.var_auto_gallery).pack(anchor="w", padx=5, pady=2)
        
        self.btn_open = ctk.CTkButton(out_frame, text="Open Output Folder", command=self.open_output_folder, state="disabled")
        self.btn_open.pack(fill="x", padx=5, pady=10)
        # ------------------------------------------

        # Bottom Buttons
        btn_frame = ctk.CTkFrame(self.settings_frame_container, fg_color="transparent")
        btn_frame.pack(side="bottom", fill="x", padx=10, pady=10)
        
        self.btn_start = ctk.CTkButton(btn_frame, text="Start Upload", command=self.start_upload)
        self.btn_start.pack(fill="x", pady=5)
        
        self.btn_stop = ctk.CTkButton(btn_frame, text="Stop", command=self.stop_upload, state="disabled", fg_color="#FF3B30", hover_color="#D63028")
        self.btn_stop.pack(fill="x", pady=5)
        
        util_grid = ctk.CTkFrame(btn_frame, fg_color="transparent")
        util_grid.pack(fill="x")
        ctk.CTkButton(util_grid, text="Retry Failed", command=self.retry_failed, width=100).pack(side="left", padx=2)
        ctk.CTkButton(util_grid, text="Clear List", command=self.clear_list, width=100).pack(side="right", padx=2)

        # Tabs
        self.notebook = ctk.CTkTabview(self.settings_frame_container)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=5)
        self.notebook.add("imx.to")
        self.notebook.add("pixhost.to")
        self.notebook.add("turboimagehost")
        self.notebook.add("vipr.im")

        # Right Panel (Files)
        right_panel = ctk.CTkFrame(main_container)
        right_panel.pack(side="right", fill="both", expand=True)
        
        self.list_container = ScrollableFrame(right_panel, width=600)
        self.list_container.pack(fill="both", expand=True, padx=5, pady=5)
        self.file_frame = self.list_container
        
        footer = ctk.CTkFrame(right_panel, height=40, fg_color="transparent")
        footer.pack(fill="x", padx=5, pady=5)
        
        self.lbl_eta = ctk.CTkLabel(footer, text="Ready...", text_color="gray")
        self.lbl_eta.pack(anchor="w")
        
        self.overall_progress = ctk.CTkProgressBar(footer)
        self.overall_progress.set(0)
        self.overall_progress.pack(fill="x", pady=5)

        self._build_imx_tab()
        self._build_pix_tab()
        self._build_turbo_tab()
        self._build_vipr_tab()

    # --- Tab Builders ---
    def _build_imx_tab(self):
        p = self.notebook.tab("imx.to")
        ctk.CTkLabel(p, text="Requires Credentials", text_color="red").pack(pady=5)
        self.var_imx_thumb = ctk.StringVar(value="180")
        self.var_imx_format = ctk.StringVar(value="Fixed Width")
        self.var_imx_cover = ctk.BooleanVar()
        self.var_imx_links = ctk.BooleanVar()
        self.var_imx_threads = ctk.IntVar(value=5)
        
        ctk.CTkLabel(p, text="Thumb Size:").pack(anchor="w")
        MouseWheelComboBox(p, variable=self.var_imx_thumb, values=["100","180","250","300","600"]).pack(fill="x")
        ctk.CTkLabel(p, text="Format:").pack(anchor="w")
        MouseWheelComboBox(p, variable=self.var_imx_format, values=["Fixed Width", "Fixed Height", "Proportional", "Square"]).pack(fill="x")
        ctk.CTkCheckBox(p, text="1st Image Cover", variable=self.var_imx_cover).pack(anchor="w", pady=5)
        ctk.CTkCheckBox(p, text="Links.txt", variable=self.var_imx_links).pack(anchor="w", pady=5)
        ctk.CTkLabel(p, text="Gallery ID:").pack(anchor="w", pady=(10,0))
        self.ent_imx_gal = ctk.CTkEntry(p)
        self.ent_imx_gal.pack(fill="x")

    def _build_pix_tab(self):
        p = self.notebook.tab("pixhost.to")
        self.var_pix_content = ctk.StringVar(value="Safe")
        self.var_pix_thumb = ctk.StringVar(value="200")
        self.var_pix_cover = ctk.BooleanVar()
        self.var_pix_links = ctk.BooleanVar()
        self.var_pix_threads = ctk.IntVar(value=3)

        ctk.CTkLabel(p, text="Content:").pack(anchor="w")
        MouseWheelComboBox(p, variable=self.var_pix_content, values=["Safe", "Adult"]).pack(fill="x")
        
        ctk.CTkLabel(p, text="Thumb Size:").pack(anchor="w")
        MouseWheelComboBox(p, variable=self.var_pix_thumb, values=["150","200","250","300","350","400","450","500"]).pack(fill="x")
        
        ctk.CTkCheckBox(p, text="1st Image Cover", variable=self.var_pix_cover).pack(anchor="w", pady=5)
        ctk.CTkCheckBox(p, text="Links.txt", variable=self.var_pix_links).pack(anchor="w", pady=5)
        
        ctk.CTkLabel(p, text="Gallery Hash (Optional):").pack(anchor="w", pady=(10,0))
        self.ent_pix_hash = ctk.CTkEntry(p)
        self.ent_pix_hash.pack(fill="x")

    def _build_turbo_tab(self):
        p = self.notebook.tab("turboimagehost")
        ctk.CTkLabel(p, text="Login Optional", text_color="red").pack(pady=5)
        self.var_turbo_content = ctk.StringVar(value="Safe")
        self.var_turbo_thumb = ctk.StringVar(value="180")
        self.var_turbo_cover = ctk.BooleanVar()
        self.var_turbo_links = ctk.BooleanVar()
        self.var_turbo_threads = ctk.IntVar(value=2)

        ctk.CTkLabel(p, text="Thumb Size:").pack(anchor="w")
        MouseWheelComboBox(p, variable=self.var_turbo_thumb, values=["150","200","250","300","350","400","500","600"]).pack(fill="x")
        ctk.CTkCheckBox(p, text="1st Image Cover", variable=self.var_turbo_cover).pack(anchor="w", pady=5)
        ctk.CTkCheckBox(p, text="Links.txt", variable=self.var_turbo_links).pack(anchor="w", pady=5)
        ctk.CTkLabel(p, text="Gallery ID:").pack(anchor="w")
        self.ent_turbo_gal = ctk.CTkEntry(p)
        self.ent_turbo_gal.pack(fill="x")

    def _build_vipr_tab(self):
        p = self.notebook.tab("vipr.im")
        ctk.CTkLabel(p, text="Requires Credentials", text_color="red").pack(pady=5)

        self.var_vipr_thumb = ctk.StringVar(value="170x170")
        self.var_vipr_gallery = ctk.StringVar()
        self.var_vipr_cover = ctk.BooleanVar()
        self.var_vipr_links = ctk.BooleanVar()
        self.var_vipr_threads = ctk.IntVar(value=1)

        ctk.CTkLabel(p, text="Thumb Size:").pack(anchor="w")
        MouseWheelComboBox(p, variable=self.var_vipr_thumb, values=["100x100", "170x170", "250x250", "300x300", "350x350", "500x500", "800x800"]).pack(fill="x")
        
        ctk.CTkCheckBox(p, text="1st Image Cover", variable=self.var_vipr_cover).pack(anchor="w", pady=5)
        ctk.CTkCheckBox(p, text="Links.txt", variable=self.var_vipr_links).pack(anchor="w", pady=5)
        
        ctk.CTkButton(p, text="Refresh Galleries / Login", command=self.refresh_vipr_galleries).pack(fill="x", pady=10)
        self.cb_vipr_gallery = MouseWheelComboBox(p, variable=self.var_vipr_gallery, values=["None"])
        self.cb_vipr_gallery.pack(fill="x")

    # --- Settings Methods ---
    def _apply_settings(self):
        s = self.settings
        self.var_imx_thumb.set(s.get("imx_thumb", "180"))
        self.var_imx_format.set(s.get("imx_format", "Fixed Width"))
        self.var_imx_cover.set(s.get("imx_cover", False))
        self.var_imx_links.set(s.get("imx_links", False))
        self.var_imx_threads.set(s.get("imx_threads", 5))
        self.menu_thread_var.set(s.get("imx_threads", 5))
        
        self.var_pix_content.set(s.get("pix_content", "Safe"))
        self.var_pix_thumb.set(s.get("pix_thumb", "200"))
        self.var_pix_cover.set(s.get("pix_cover", False))
        self.var_pix_links.set(s.get("pix_links", False))
        self.var_pix_threads.set(s.get("pix_threads", 3))
        
        self.var_turbo_content.set(s.get("turbo_content", "Safe"))
        self.var_turbo_thumb.set(s.get("turbo_thumb", "180"))
        self.var_turbo_cover.set(s.get("turbo_cover", False))
        self.var_turbo_links.set(s.get("turbo_links", False))
        self.var_turbo_threads.set(s.get("turbo_threads", 2))
        
        self.var_vipr_thumb.set(s.get("vipr_thumb", "170x170"))
        self.var_vipr_cover.set(s.get("vipr_cover", False))
        self.var_vipr_links.set(s.get("vipr_links", False))
        self.var_vipr_threads.set(s.get("vipr_threads", 1))
        
        self.var_format.set(s.get("output_format", "BBCode"))
        self.var_auto_copy.set(s.get("auto_copy", False))
        self.var_auto_gallery.set(s.get("auto_gallery", False))
        
        # Load Preview Setting
        self.var_show_previews.set(s.get("show_previews", True))
        
        try: self.notebook.set(s.get("service", "imx.to"))
        except: pass

        self.ent_imx_gal.delete(0, "end")
        self.ent_imx_gal.insert(0, s.get("gallery_id", ""))
        
        self.ent_pix_hash.delete(0, "end")
        self.ent_pix_hash.insert(0, s.get("pix_gallery_hash", ""))

    def _safe_int(self, value, default=2):
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def _gather_settings(self):
        vipr_gal_name = self.cb_vipr_gallery.get()
        vipr_id = self.vipr_galleries_map.get(vipr_gal_name, "0")

        return {
            "service": self.notebook.get(),
            "imx_thumb": self.var_imx_thumb.get(),
            "imx_format": self.var_imx_format.get(),
            "imx_cover": self.var_imx_cover.get(),
            "imx_links": self.var_imx_links.get(),
            "imx_threads": self._safe_int(self.var_imx_threads.get(), 5),
            "pix_content": self.var_pix_content.get(),
            "pix_thumb": self.var_pix_thumb.get(),
            "pix_cover": self.var_pix_cover.get(),
            "pix_links": self.var_pix_links.get(),
            "pix_threads": self._safe_int(self.var_pix_threads.get(), 3),
            "turbo_content": self.var_turbo_content.get(),
            "turbo_thumb": self.var_turbo_thumb.get(),
            "turbo_cover": self.var_turbo_cover.get(),
            "turbo_links": self.var_turbo_links.get(),
            "turbo_threads": self._safe_int(self.var_turbo_threads.get(), 2),
            "vipr_thumb": self.var_vipr_thumb.get(),
            "vipr_cover": self.var_vipr_cover.get(),
            "vipr_links": self.var_vipr_links.get(),
            "vipr_threads": self._safe_int(self.var_vipr_threads.get(), 1),
            "vipr_gal_id": vipr_id,
            "output_format": self.var_format.get(),
            "auto_copy": self.var_auto_copy.get(),
            "auto_gallery": self.var_auto_gallery.get(),
            "show_previews": self.var_show_previews.get(), # Save Preference
            "gallery_id": self.ent_imx_gal.get(),
            "pix_gallery_hash": self.ent_pix_hash.get()
        }

    # --- File Management ---
    def drop_files(self, event):
        files = self.tk.splitlist(event.data)
        self._process_files(files)

    def add_files(self):
        files = filedialog.askopenfilenames()
        if files: self._process_files(files)

    def add_folder(self):
        folder = filedialog.askdirectory()
        if not folder: return
        subdirs = [os.path.join(folder, d) for d in os.listdir(folder) if os.path.isdir(os.path.join(folder, d))]
        has_images = any(f.lower().endswith(config.SUPPORTED_EXTENSIONS) for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)))
        if subdirs:
            msg = f"This folder contains {len(subdirs)} subfolders.\nDo you want to add each subfolder as a separate group?"
            if messagebox.askyesno("Batch Add Groups", msg):
                self._process_files(subdirs)
                if has_images: self._process_files([folder])
                return
        self._process_files([folder])

    def _process_files(self, inputs):
        misc_files = []
        folder_jobs = []

        # Capture current state of the checkbox safely on the main thread
        show_previews = self.var_show_previews.get()

        for path in inputs:
            try:
                # Validate path first
                validated_path = PathValidator.validate_input_path(path)
                path = str(validated_path)

                if validated_path.is_dir():
                    folder_name = validated_path.name
                    group_widget = self._create_group(folder_name)

                    # Use secure directory scanning
                    try:
                        files_in_folder = PathValidator.scan_directory_for_images(path, recursive=True)
                        files_in_folder = [str(f) for f in files_in_folder]

                        if files_in_folder:
                            folder_jobs.append((group_widget, sorted(files_in_folder, key=config.natural_sort_key)))
                        else:
                            group_widget.destroy()
                    except PathValidationError as e:
                        logger.error(f"Error scanning directory {path}: {e}")
                        group_widget.destroy()

                elif validated_path.is_file():
                    # Validate it's an image file
                    try:
                        PathValidator.validate_image_file(path)
                        misc_files.append(path)
                    except PathValidationError as e:
                        logger.warning(f"Skipping invalid file {path}: {e}")

            except PathValidationError as e:
                logger.warning(f"Skipping invalid path {path}: {e}")
                messagebox.showwarning("Invalid Path", f"Cannot process path:\n{path}\n\n{e}")
                continue
        
        # --- FIX 3: Submit jobs to ThreadPoolExecutor instead of spawning threads ---
        for grp, f_list in folder_jobs:
             # Pass 'show_previews' state to the worker
             self.thumb_executor.submit(self._thumb_worker, f_list, grp, show_previews)
        # ----------------------------------------------------------------------------
        
        if misc_files:
            misc_group = next((g for g in self.groups if g.title == "Miscellaneous"), None)
            if not misc_group: misc_group = self._create_group("Miscellaneous")
            # Pass 'show_previews' state
            self.thumb_executor.submit(self._thumb_worker, sorted(misc_files, key=config.natural_sort_key), misc_group, show_previews)

    def _create_group(self, title):
        group = CollapsibleGroupFrame(self.list_container, title=title)
        group.pack(fill="x", pady=2, padx=2)
        self.groups.append(group)
        return group

    def _thumb_worker(self, files, group_widget, show_previews):
        for f in files:
            if f in self.file_widgets: continue
            
            pil_image = None
            if show_previews:
                try:
                    img = Image.open(f)
                    img.thumbnail(config.UI_THUMB_SIZE)
                    pil_image = img
                except: pil_image = None
            
            self.ui_queue.put(('add', f, pil_image, group_widget))

            # If skipping previews, run much faster (shorter sleep)
            time.sleep(config.THUMBNAIL_SLEEP_WITH_PREVIEW if show_previews else config.THUMBNAIL_SLEEP_NO_PREVIEW)

    # --- Upload Logic ---
    def start_upload(self):
        # 1. Filter for pending files
        pending_by_group = {}
        for grp in self.groups:
            for fp in grp.files:
                if self.file_widgets[fp]['state'] == 'pending':
                    if grp not in pending_by_group: pending_by_group[grp] = []
                    pending_by_group[grp].append(fp)
        
        if not pending_by_group: 
            messagebox.showinfo("Info", "No pending files found. Please add files or use 'Retry Failed'.")
            return
        
        try:
            cfg = self._gather_settings()
            
            # --- FIX: Update global settings so output generation knows which service we used ---
            self.settings = cfg 
            # ----------------------------------------------------------------------------------

            self.settings_mgr.save(cfg)
            cfg['api_key'] = self.creds.get('imx_api', '')
            
            self.cancel_event.clear()
            self.results = []
            # Reset queue so we don't process old results
            self.result_queue = queue.Queue()
            self.upload_manager.result_queue = self.result_queue
            
            self.pix_galleries_to_finalize = []
            self.clipboard_buffer = []
            
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.lbl_eta.configure(text="Starting...")
            
            self.overall_progress.set(0)
            try:
                self.overall_progress.configure(progress_color=["#3B8ED0", "#1F6AA5"]) 
            except Exception:
                self.overall_progress.configure(progress_color="blue")

            self.upload_total = sum(len(v) for v in pending_by_group.values())
            self.upload_count = 0
            self.is_uploading = True
            
            for files in pending_by_group.values():
                for fp in files: self.file_widgets[fp]['state'] = 'queued'

            # Delegate to the new modular manager
            self.upload_manager.start_batch(pending_by_group, cfg, self.creds)

        except Exception as e:
            messagebox.showerror("Error starting upload", str(e))
            self.btn_start.configure(state="normal")

    def update_ui_loop(self):
        try:
            # 1. Process Result Queue (Images finished uploading)
            try:
                while True:
                    fp, img, thumb = self.result_queue.get_nowait()
                    with self.lock:
                        self.results.append((fp, img, thumb))
            except queue.Empty: pass

            # 2. Process UI Queue (Thumbnails generation)
            ui_limit = config.UI_QUEUE_BATCH_SIZE
            try:
                while ui_limit > 0:
                    a, f, p, g = self.ui_queue.get_nowait()
                    if a == 'add': self._create_row(f, p, g)
                    ui_limit -= 1
            except queue.Empty: pass

            # 3. Process Progress Queue (Upload progress status)
            prog_limit = config.PROGRESS_QUEUE_BATCH_SIZE
            try:
                while prog_limit > 0:
                    item = self.progress_queue.get_nowait()
                    k = item[0]
                    
                    if k == 'register_pix_gal':
                        # New Pixhost Gallery created automatically
                        new_data = item[2]
                        self.pix_galleries_to_finalize.append(new_data)
                    
                    else:
                        f = item[1]
                        v = item[2]
                        if f in self.file_widgets:
                            w = self.file_widgets[f]
                            if k=='status':
                                w['status'].configure(text=v)
                                if v in ['Done', 'Failed']:
                                    with self.lock:
                                        self.upload_count += 1
                                    w['state'] = 'success' if v == 'Done' else 'failed'
                                    w['prog'].set(1.0)
                                    w['prog'].configure(progress_color="#34C759" if v=='Done' else "#FF3B30")
                                    self._update_group_progress(f)
                            elif k=='prog':
                                w['prog'].set(v)
                    prog_limit -= 1
            except queue.Empty: pass
            
            if self.is_uploading:
                with self.lock:
                    if self.upload_count >= self.upload_total:
                        self.finish_upload()
        except Exception as e:
            print(f"UI Loop Error: {e}")
        finally:
            self.after(config.UI_UPDATE_INTERVAL_MS, self.update_ui_loop)

    def _create_row(self, fp, pil_image, group_widget):
        group_widget.add_file(fp)
        row = ctk.CTkFrame(group_widget.content_frame)
        row.pack(fill="x", pady=1)
        
        if pil_image:
            img_widget = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=config.UI_THUMB_SIZE)
            l = ctk.CTkLabel(row, image=img_widget, text="")
            l.pack(side="left", padx=5)
            self.image_refs.append(img_widget)
        else:
            ctk.CTkLabel(row, text="[Img]", width=40).pack(side="left")
            
        st = ctk.CTkLabel(row, text="Wait", width=60)
        st.pack(side="left")
        
        ctk.CTkLabel(row, text=os.path.basename(fp)).pack(side="left", fill="x", expand=True, padx=5)
        
        pr = ctk.CTkProgressBar(row, width=100)
        pr.set(0)
        pr.pack(side="right", padx=5)
        
        self.file_widgets[fp] = {'row':row, 'status':st, 'prog':pr, 'state':'pending', 'group': group_widget}
        self.lbl_eta.configure(text=f"Files: {len(self.file_widgets)}")

    def _update_group_progress(self, fp):
        if fp not in self.file_widgets: return
        try:
            group = self.file_widgets[fp]['group']
            total = len(group.files)
            if total == 0: return
            done = 0
            for f in group.files:
                if f in self.file_widgets:
                    if self.file_widgets[f]['state'] in ['success', 'failed']:
                        done += 1
            
            group.prog.set(done / total)
            group.lbl_counts.configure(text=f"({done}/{total})")
            
            if done == total and not group.is_completed:
                group.mark_complete()
                self.generate_group_output(group)
        except Exception as e:
            print(f"Group Update Error: {e}")

    def finish_upload(self):
        if self.pix_galleries_to_finalize:
            self.lbl_eta.configure(text="Finalizing Galleries...")
            # We use a temp client here just for finalization
            client = api.create_resilient_client()
            for gal in self.pix_galleries_to_finalize:
                try:
                    api.finalize_pixhost_gallery(gal.get('gallery_upload_hash'), gal.get('gallery_hash'), client=client)
                except: pass
            client.close()
        
        self.is_uploading = False
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        
        self.overall_progress.set(1.0) 
        self.overall_progress.configure(progress_color="#34C759") 

        self.lbl_eta.configure(text="All batches finished.")
        
        if self.var_auto_copy.get() and self.clipboard_buffer:
            try:
                full_text = "\n\n".join(self.clipboard_buffer)
                pyperclip.copy(full_text)
            except Exception: pass

        if self.current_output_files:
            self.btn_open.configure(state="normal")
            msg = "Output files created."
            if self.var_auto_copy.get():
                msg += " All output text copied to clipboard."
            messagebox.showinfo("Done", msg)

    def stop_upload(self):
        self.cancel_event.set()
        self.lbl_eta.configure(text="Stopping...")
        self.after(500, self.finish_upload)

    def generate_group_output(self, group):
        res_map = {r[0]: (r[1], r[2]) for r in self.results}
        group_results = []
        for fp in group.files:
            if fp in res_map:
                group_results.append(res_map[fp])
        
        # --- FIX: Log warning if no results found ---
        if not group_results:
            self.log(f"Warning: No successful uploads for group '{group.title}'. Output generation skipped.")
            # Don't show modal warning here, it blocks processing of other groups
            return

        gal_id = getattr(group, 'gallery_id', "")
        cover_url = group_results[0][1] if group_results else "" 

        gal_link = ""
        svc = self.settings.get('service', '')
        if gal_id:
            if svc == "pixhost.to": gal_link = f"https://pixhost.to/gallery/{gal_id}"
            elif svc == "imx.to": gal_link = f"https://imx.to/g/{gal_id}"
            elif svc == "vipr.im": gal_link = f"https://vipr.im/f/{gal_id}"

        ctx = {
            "gallery_link": gal_link,
            "gallery_name": group.title,
            "gallery_id": gal_id,
            "cover_url": cover_url
        }
        
        text = self.template_mgr.apply(self.var_format.get(), ctx, group_results)
        
        # Buffer text first (for final bulk copy)
        if self.var_auto_copy.get():
            self.clipboard_buffer.append(text)

        # Use secure filename sanitization
        safe_title = PathValidator.safe_filename(group.title, max_length=50)
        ts = datetime.now().strftime("%Y%m%d_%H%M")

        # --- CREATE OUTPUT FOLDER SECURELY ---
        try:
            output_filename = f"{safe_title}_{ts}.txt"
            out_path = PathValidator.validate_output_path(
                os.path.join("Output", output_filename),
                create_parent=True
            )
            # ----------------------------

            with open(out_path, "w", encoding="utf-8") as f: f.write(text)
            self.current_output_files.append(str(out_path))
            self.log(f"Saved: {out_path}")
            
            # --- FIX: Immediate Feedback per Batch ---
            self.lbl_eta.configure(text=f"Saved: {safe_title}_{ts}.txt")
            self.btn_open.configure(state="normal") # Enable button immediately
            
            # --- FIX: Immediate Clipboard Update (Accumulated) ---
            if self.var_auto_copy.get():
                try:
                    # Update system clipboard immediately with everything generated so far
                    full_text = "\n\n".join(self.clipboard_buffer)
                    pyperclip.copy(full_text)
                except Exception: pass
            # -----------------------------------------
            
            need_links_txt = False
            if svc == "imx.to" and self.var_imx_links.get(): need_links_txt = True
            elif svc == "pixhost.to" and self.var_pix_links.get(): need_links_txt = True
            elif svc == "turboimagehost" and self.var_turbo_links.get(): need_links_txt = True
            elif svc == "vipr.im" and self.var_vipr_links.get(): need_links_txt = True
            
            if need_links_txt:
                links_filename = f"{safe_title}_{ts}_links.txt"
                links_path = PathValidator.validate_output_path(
                    os.path.join("Output", links_filename),
                    create_parent=True
                )
                raw_links = "\n".join([r[0] for r in group_results])
                with open(links_path, "w", encoding="utf-8") as f: f.write(raw_links)
                self.log(f"Saved Links: {links_path}")
                
        except Exception as e:
            self.log(f"Error writing output for {group.title}: {e}")

    def open_output_folder(self):
        if self.current_output_files:
             folder = os.path.dirname(os.path.abspath(self.current_output_files[0]))
             if platform.system() == "Windows": os.startfile(folder)
             else: subprocess.call(["xdg-open", folder])

    def toggle_log(self):
        if self.log_window_ref and self.log_window_ref.winfo_exists(): self.log_window_ref.lift()
        else: self.log_window_ref = LogWindow(self, self.log_cache)

    def retry_failed(self):
        cnt = 0
        for w in self.file_widgets.values():
            if w['state'] == 'failed':
                w['status'].configure(text="Retry")
                w['prog'].set(0)
                w['state'] = 'pending'
                cnt += 1
        if cnt: self.start_upload()

    def clear_list(self):
        self.cancel_event.set()
        self.is_uploading = False
        self.upload_count = 0
        self.upload_total = 0
        self.current_output_files = []
        self.clipboard_buffer = []
        for grp in self.groups:
            grp.destroy()
        self.groups.clear()
        self.file_widgets.clear()
        self.image_refs.clear()
        self.overall_progress.set(0)
        self.lbl_eta.configure(text="Cleared.")
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
    
    def log(self, msg):
        config.logger.info(msg)
        if self.log_window_ref and self.log_window_ref.winfo_exists():
            self.log_window_ref.append_log(msg+"\n")
        else: self.log_cache.append(msg+"\n")

if __name__ == "__main__":
    app = UploaderApp()
    app.mainloop()
