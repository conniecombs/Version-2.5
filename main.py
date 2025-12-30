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
import gc
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
from modules.async_upload_manager import AsyncUploadManager
from modules.upload_coordinator import UploadCoordinator, GroupContext
from modules.utils import ContextUtils
from modules.path_validator import PathValidator, PathValidationError
from modules.error_handler import get_error_handler, ErrorSeverity
from modules.app_state import AppState, StateManager
from modules.config_loader import get_config_loader
from modules.thumbnail_cache import get_thumbnail_cache
from loguru import logger

# Load user configuration (YAML-based, optional)
_config_loader = get_config_loader()
_app_config = _config_loader.config

# Tkinter can hit the default limit (1000) when rendering thousands of widgets.
sys.setrecursionlimit(_app_config.ui.recursion_limit) 

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
        self.thumb_executor = ThreadPoolExecutor(max_workers=_app_config.threading.thumbnail_workers)

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

        # Centralized State Management (replaces 30+ scattered variables)
        self.app_state = AppState()
        self.app_state_mgr = StateManager(self.app_state)

        # Initialize AsyncUploadManager with state queues (performance-optimized)
        # Uses async/await for better concurrency and lower resource usage
        self.upload_manager = AsyncUploadManager(
            self.app_state.queues.progress_queue,
            self.app_state.queues.result_queue,
            self.app_state.upload.cancel_event
        )

        # Initialize UploadCoordinator (business logic layer)
        self.coordinator = UploadCoordinator(
            self.app_state,
            self.upload_manager,
            self.template_mgr
        )

        # Backward compatibility aliases (will be gradually removed)
        # These allow existing code to work while we refactor
        self.progress_queue = self.app_state.queues.progress_queue
        self.ui_queue = self.app_state.queues.ui_queue
        self.result_queue = self.app_state.queues.result_queue
        self.cancel_event = self.app_state.upload.cancel_event
        self.lock = self.app_state.lock
        self.file_widgets = self.app_state.files.file_widgets
        self.groups = self.app_state.files.groups
        self.results = self.app_state.results.results
        self.log_cache = self.app_state.ui.log_cache
        self.image_refs = self.app_state.files.image_refs
        self.log_window_ref = self.app_state.ui.log_window_ref
        self.clipboard_buffer = self.app_state.results.clipboard_buffer
        self.current_output_files = self.app_state.results.current_output_files
        self.pix_galleries_to_finalize = self.app_state.results.pix_galleries_to_finalize
        self.turbo_cookies = self.app_state.auth.turbo_cookies
        self.turbo_endpoint = self.app_state.auth.turbo_endpoint
        self.turbo_upload_id = self.app_state.auth.turbo_upload_id
        self.vipr_session = self.app_state.auth.vipr_session
        self.vipr_meta = self.app_state.auth.vipr_meta
        self.vipr_galleries_map = self.app_state.auth.vipr_galleries_map
        self.upload_total = self.app_state.upload.upload_total
        self.upload_count = self.app_state.upload.upload_count
        self.is_uploading = self.app_state.upload.is_uploading

        self._load_credentials()
        self._create_menu()
        self._create_layout()
        self._apply_settings()
        self._setup_coordinator_callbacks()

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

    def _setup_coordinator_callbacks(self):
        """Set up UI callbacks for the upload coordinator."""
        self.coordinator.on_upload_start = self._on_upload_start
        self.coordinator.on_upload_finish = self._on_upload_finish
        self.coordinator.on_upload_progress = self._on_upload_progress
        self.coordinator.on_status_update = self._on_status_update

    def _on_upload_start(self):
        """UI callback when upload starts."""
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.lbl_eta.configure(text="Starting...")
        self.overall_progress.set(0)
        try:
            self.overall_progress.configure(progress_color=["#3B8ED0", "#1F6AA5"])
        except Exception:
            self.overall_progress.configure(progress_color="blue")

    def _on_upload_finish(self):
        """UI callback when upload finishes."""
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.overall_progress.set(1.0)
        self.overall_progress.configure(progress_color="#34C759")

        # Handle clipboard copy
        if self.var_auto_copy.get() and self.coordinator.clipboard_buffer:
            try:
                full_text = self.coordinator.get_clipboard_text()
                pyperclip.copy(full_text)
            except Exception as e:
                logger.error(f"Failed to copy to clipboard: {e}")

        # Show completion message
        if self.coordinator.current_output_files:
            self.btn_open.configure(state="normal")
            msg = "Output files created."
            if self.var_auto_copy.get():
                msg += " All output text copied to clipboard."
            messagebox.showinfo("Done", msg)

    def _on_upload_progress(self, current: int, total: int):
        """UI callback for upload progress updates."""
        if total > 0:
            self.overall_progress.set(current / total)
            self.app_state.upload.upload_count = current
            self.app_state.upload.upload_total = total

    def _on_status_update(self, status: str):
        """UI callback for status text updates."""
        self.lbl_eta.configure(text=status)

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
        tools_menu.add_command(label="Thumbnail Cache Stats", command=self.show_cache_stats)
        tools_menu.add_command(label="Clear Thumbnail Cache", command=self.clear_cache)
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
        """Generate thumbnails with caching for performance."""
        thumb_cache = get_thumbnail_cache()

        for f in files:
            if f in self.file_widgets: continue

            pil_image = None
            if show_previews:
                # Try cache first (fast path)
                pil_image = thumb_cache.get(f, _app_config.ui.thumbnail_size)

                if pil_image is None:
                    # Cache miss - generate thumbnail
                    try:
                        # Use context manager to ensure file is properly closed
                        with Image.open(f) as img:
                            img.thumbnail(_app_config.ui.thumbnail_size)
                            # Create a copy since original will be closed
                            pil_image = img.copy()

                        # Store in cache for future use
                        if pil_image:
                            thumb_cache.put(f, pil_image, _app_config.ui.thumbnail_size)

                    except Exception as e:
                        logger.debug(f"Failed to create thumbnail for {f}: {e}")
                        pil_image = None

            self.ui_queue.put(('add', f, pil_image, group_widget))

            # If skipping previews, run much faster (shorter sleep)
            time.sleep(_app_config.performance.thumbnail_sleep_with_preview if show_previews
                      else _app_config.performance.thumbnail_sleep_no_preview)

    # --- Upload Logic ---
    def start_upload(self):
        """Start the upload process using the coordinator."""
        # Filter for pending files
        pending_by_group = self.coordinator.filter_pending_files(self.groups)

        if not pending_by_group:
            messagebox.showinfo("Info", "No pending files found. Please add files or use 'Retry Failed'.")
            return

        try:
            # Gather and save settings
            cfg = self._gather_settings()
            self.settings = cfg  # Update global settings for output generation
            self.settings_mgr.save(cfg)
            cfg['api_key'] = self.creds.get('imx_api', '')

            # Start upload through coordinator (handles all business logic)
            if self.coordinator.start_upload(pending_by_group, cfg, self.creds):
                # Update backward compatibility aliases
                self.is_uploading = self.coordinator.is_uploading
                self.upload_total = self.coordinator.upload_total
                self.upload_count = self.coordinator.upload_count
            else:
                messagebox.showinfo("Info", "Upload could not be started.")

        except Exception as e:
            logger.error(f"Error starting upload: {e}")
            messagebox.showerror("Error starting upload", str(e))
            self.btn_start.configure(state="normal")

    def update_ui_loop(self):
        try:
            # 1. Process Error Notifications (show to user)
            error_handler = get_error_handler()
            notification_limit = 3  # Max 3 notifications per cycle to avoid blocking UI
            shown = 0
            while shown < notification_limit and error_handler.has_notifications():
                notification = error_handler.get_notification(block=False)
                if notification:
                    self._show_notification(notification)
                    shown += 1

            # 2. Process Result Queue (Images finished uploading)
            try:
                while True:
                    fp, img, thumb = self.result_queue.get_nowait()
                    with self.lock:
                        self.results.append((fp, img, thumb))
            except queue.Empty: pass

            # 3. Process UI Queue (Thumbnails generation)
            ui_limit = _app_config.performance.ui_queue_batch_size
            try:
                while ui_limit > 0:
                    a, f, p, g = self.ui_queue.get_nowait()
                    if a == 'add': self._create_row(f, p, g)
                    ui_limit -= 1
            except queue.Empty: pass

            # 4. Process Progress Queue (Upload progress status)
            prog_limit = _app_config.performance.progress_queue_batch_size
            try:
                while prog_limit > 0:
                    item = self.progress_queue.get_nowait()
                    k = item[0]
                    
                    if k == 'register_pix_gal':
                        # New Pixhost Gallery created automatically
                        new_data = item[2]
                        self.coordinator.register_pixhost_gallery(new_data)

                    else:
                        f = item[1]
                        v = item[2]
                        if f in self.file_widgets:
                            w = self.file_widgets[f]
                            if k=='status':
                                w['status'].configure(text=v)
                                if v in ['Done', 'Failed']:
                                    # Increment through coordinator
                                    count = self.coordinator.increment_upload_count()
                                    # Update backward compatibility alias
                                    self.upload_count = count

                                    w['state'] = 'success' if v == 'Done' else 'failed'
                                    w['prog'].set(1.0)
                                    w['prog'].configure(progress_color="#34C759" if v=='Done' else "#FF3B30")
                                    self._update_group_progress(f)
                            elif k=='prog':
                                w['prog'].set(v)
                    prog_limit -= 1
            except queue.Empty: pass
            
            if self.coordinator.is_uploading:
                # Check if all uploads are complete
                current, total = self.coordinator.get_upload_progress()
                if current >= total:
                    self.finish_upload()
        except Exception as e:
            print(f"UI Loop Error: {e}")
        finally:
            self.after(_app_config.ui.update_interval_ms, self.update_ui_loop)

    def _create_row(self, fp, pil_image, group_widget):
        group_widget.add_file(fp)
        row = ctk.CTkFrame(group_widget.content_frame)
        row.pack(fill="x", pady=1)
        
        if pil_image:
            img_widget = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=_app_config.ui.thumbnail_size)
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
        """Finish the upload process using the coordinator."""
        # Delegate to coordinator (handles gallery finalization and cleanup)
        self.coordinator.finish_upload()

        # Update backward compatibility aliases
        self.is_uploading = self.coordinator.is_uploading

    def stop_upload(self):
        """Stop the current upload process."""
        self.coordinator.stop_upload()
        self.after(500, self.finish_upload)

    def generate_group_output(self, group):
        """Generate output file for a group using the coordinator."""
        # Build group context
        gal_id = getattr(group, 'gallery_id', "")
        group_context = GroupContext(
            title=group.title,
            files=group.files,
            gallery_id=gal_id
        )

        # Generate output through coordinator
        svc = self.settings.get('service', '')
        out_path = self.coordinator.generate_group_output(
            group_context,
            self.var_format.get(),
            svc,
            auto_copy=self.var_auto_copy.get()
        )

        if not out_path:
            self.log(f"Warning: No successful uploads for group '{group.title}'. Output generation skipped.")
            return

        # Update UI
        safe_title = PathValidator.safe_filename(group.title, max_length=50)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        self.lbl_eta.configure(text=f"Saved: {safe_title}_{ts}.txt")
        self.btn_open.configure(state="normal")

        # Immediate clipboard update if enabled
        if self.var_auto_copy.get():
            try:
                full_text = self.coordinator.get_clipboard_text()
                pyperclip.copy(full_text)
            except Exception as e:
                logger.error(f"Failed to copy to clipboard: {e}")

        # Log output
        self.log(f"Saved: {out_path}")

        # Generate links.txt if needed
        need_links_txt = False
        if svc == "imx.to" and self.var_imx_links.get(): need_links_txt = True
        elif svc == "pixhost.to" and self.var_pix_links.get(): need_links_txt = True
        elif svc == "turboimagehost" and self.var_turbo_links.get(): need_links_txt = True
        elif svc == "vipr.im" and self.var_vipr_links.get(): need_links_txt = True

        if need_links_txt:
            try:
                # Get group results for links
                res_map = {r[0]: (r[1], r[2]) for r in self.app_state.results.results}
                group_results = [res_map[fp] for fp in group.files if fp in res_map]

                links_filename = f"{safe_title}_{ts}_links.txt"
                links_path = PathValidator.validate_output_path(
                    os.path.join("Output", links_filename),
                    create_parent=True
                )
                raw_links = "\n".join([r[0] for r in group_results])
                with open(links_path, "w", encoding="utf-8") as f:
                    f.write(raw_links)
                self.log(f"Saved Links: {links_path}")
            except Exception as e:
                logger.error(f"Failed to create links file: {e}")

    def open_output_folder(self):
        if self.coordinator.current_output_files:
             folder = os.path.dirname(os.path.abspath(self.coordinator.current_output_files[0]))
             if platform.system() == "Windows": os.startfile(folder)
             else: subprocess.call(["xdg-open", folder])

    def toggle_log(self):
        if self.log_window_ref and self.log_window_ref.winfo_exists(): self.log_window_ref.lift()
        else: self.log_window_ref = LogWindow(self, self.log_cache)

    def show_cache_stats(self):
        """Display thumbnail cache statistics."""
        cache = get_thumbnail_cache()
        stats = cache.get_stats()

        msg = (
            f"Thumbnail Cache Performance:\n\n"
            f"Hit Rate: {stats['hit_rate_percent']}%\n"
            f"Cache Hits: {stats['hits']}\n"
            f"Cache Misses: {stats['misses']}\n"
            f"Total Requests: {stats['total_requests']}\n\n"
            f"Memory Cache Size: {stats['memory_cache_size']} / {stats['max_memory_items']} items\n\n"
            f"Higher hit rates mean better performance.\n"
            f"Cache automatically evicts oldest items when full (LRU)."
        )

        messagebox.showinfo("Thumbnail Cache Statistics", msg)
        cache.log_stats()  # Also log to execution log

    def clear_cache(self):
        """Clear the thumbnail cache."""
        if messagebox.askyesno("Clear Cache", "Clear all cached thumbnails?\n\nNext time files are added, thumbnails will be regenerated."):
            from modules.thumbnail_cache import clear_thumbnail_cache
            clear_thumbnail_cache()
            messagebox.showinfo("Success", "Thumbnail cache cleared.")
            logger.info("Thumbnail cache manually cleared by user")

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

        # Clear coordinator state
        self.coordinator.is_uploading = False
        self.coordinator.upload_count = 0
        self.coordinator.upload_total = 0
        self.coordinator.clear_results()

        # Update backward compatibility aliases
        self.is_uploading = False
        self.upload_count = 0
        self.upload_total = 0

        # Track count before clearing for GC decision
        file_count = len(self.file_widgets)

        for grp in self.groups:
            grp.destroy()
        self.groups.clear()
        self.file_widgets.clear()

        # Properly clean up image references to free memory
        self.image_refs.clear()

        # Force garbage collection to free memory immediately for large batches
        if file_count > 100:
            gc.collect()
            logger.info(f"Garbage collection triggered after clearing {file_count} files")

        self.overall_progress.set(0)
        self.lbl_eta.configure(text="Cleared.")
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")

    def _show_notification(self, notification):
        """
        Display a notification to the user based on severity.

        Args:
            notification: UserNotification object from error handler
        """
        try:
            # Determine icon type based on severity
            if notification.severity == ErrorSeverity.CRITICAL:
                icon = messagebox.ERROR
            elif notification.severity == ErrorSeverity.ERROR:
                icon = messagebox.ERROR
            elif notification.severity == ErrorSeverity.WARNING:
                icon = messagebox.WARNING
            else:
                icon = messagebox.INFO

            # Create message with optional details
            message = notification.message
            if notification.show_details_button and notification.details:
                # Truncate long details for display
                details_preview = notification.details[:200]
                if len(notification.details) > 200:
                    details_preview += "..."
                message += f"\n\nDetails:\n{details_preview}"

            # Show notification (non-blocking)
            if icon == messagebox.ERROR:
                messagebox.showerror(notification.title, message, parent=self)
            elif icon == messagebox.WARNING:
                messagebox.showwarning(notification.title, message, parent=self)
            else:
                messagebox.showinfo(notification.title, message, parent=self)

            # Log to execution log as well
            self.log(f"[{notification.severity.value.upper()}] {notification.title}: {notification.message}")

        except Exception as e:
            # Fallback if notification display fails
            logger.error(f"Failed to show notification: {e}")
            self.log(f"Error: {notification.title} - {notification.message}")

    def log(self, msg):
        config.logger.info(msg)
        if self.log_window_ref and self.log_window_ref.winfo_exists():
            self.log_window_ref.append_log(msg+"\n")
        else: self.log_cache.append(msg+"\n")

if __name__ == "__main__":
    app = UploaderApp()
    app.mainloop()
