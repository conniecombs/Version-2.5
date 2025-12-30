# modules/template_manager.py
import re
import json
import os
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, colorchooser
import urllib.parse
import webbrowser
import tempfile
from loguru import logger

# Local imports
from . import config
from .widgets import MouseWheelComboBox

# ==========================================
# PART 1: THE LOGIC (TemplateManager)
# ==========================================

class TemplateManager:
    def __init__(self):
        # 1. Standard Defaults
        self.defaults = {
            "BBCode": "[center]\n[if gallery_link][url=#gallery_link#]Click here for Gallery[/url]\n\n[/if]#all_images#\n[/center]",
            "Markdown": "[if gallery_link][Click here for Gallery](#gallery_link#)\n\n[/if]#all_images#",
            "HTML": "[if gallery_link]<center><a href=\"#gallery_link#\">Click here for Gallery</a></center><br><br>[/if]#all_images#"
        }

        # 2. Add the "Presets" as valid defaults
        self.presets = {
            "Basic List": "#all_images#",
            "Vipr Forum (Center)": "[center][url=#gallery_link#][b]📂 Open Full Gallery[/b][/url][/center]\n\n#all_images#",
            "Vipr Forum (Simple)": "[b]Gallery:[/b] [url=#gallery_link#]#gallery_name#[/url]\n\n#all_images#",
            "Reddit Markdown": "[📂 View Gallery](#gallery_link#)\n\n#all_images#",
            "HTML Page Wrapper": "<html>\n<body>\n<h3><a href='#gallery_link#'>View Gallery</a></h3>\n<hr>\n#all_images#\n</body>\n</html>",
            "Cover + Gallery ID": "[center][img]#cover_url#[/img]\n\n[b]Gallery ID:[/b] #gallery_id#\n[url=#gallery_link#]Click to View Gallery[/url][/center]\n\n#all_images#"
        }
        self.defaults.update(self.presets)
        
        # Defines how a single image line looks
        self.image_formats = {
            "BBCode": "[url=#image_url#][img]#thumb_url#[/img][/url]",
            "Markdown": "[![Image](#thumb_url#)](#image_url#)",
            "HTML": "<a href=\"#image_url#\"><img src=\"#thumb_url#\"></a>"
        }
        
        self.if_pattern = re.compile(r'\[if\s+(\w+)(?:=([^\]]+))?\]((?:(?!\[if).)*?)\[/if\]', re.IGNORECASE | re.DOTALL)
        
        self.templates = self.defaults.copy()
        self.filepath = "user_templates.json"
        self.load()

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r') as f:
                    saved = json.load(f)
                    self.templates.update(saved)
            except Exception as e:
                logger.warning(f"Error loading templates: {e}")

    def save(self):
        try:
            with open(self.filepath, 'w') as f:
                json.dump(self.templates, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving templates: {e}")

    def get_template(self, fmt):
        return self.templates.get(fmt, self.defaults.get(fmt, ""))

    def set_template(self, fmt, content):
        self.templates[fmt] = content
        self.save()
        
    def get_all_keys(self):
        keys = list(self.templates.keys())
        standards = ["BBCode", "Markdown", "HTML"]
        others = sorted([k for k in keys if k not in standards])
        
        final_list = []
        for s in standards:
            if s in keys:
                final_list.append(s)
        
        for o in others:
            if o not in final_list:
                final_list.append(o)
                
        return final_list

    def process_conditionals(self, template_content, data):
        max_iterations = 1000 
        iteration = 0
        
        while iteration < max_iterations:
            match = self.if_pattern.search(template_content)
            if not match: break

            key = match.group(1)
            expected_val = match.group(2)
            block = match.group(3)
            actual_val = data.get(key, '')

            if expected_val is not None:
                condition_met = (str(actual_val).strip() == expected_val.strip())
            else:
                condition_met = bool(str(actual_val).strip())

            if '[else]' in block:
                parts = block.split('[else]', 1)
                true_block = parts[0]
                false_block = parts[1]
            else:
                true_block = block
                false_block = ''

            replacement = true_block if condition_met else false_block
            start_idx, end_idx = match.span()
            template_content = template_content[:start_idx] + replacement + template_content[end_idx:]
            iteration += 1
            
        return template_content

    def apply(self, format_mode, data, images):
        img_fmt = self.image_formats.get(format_mode, self.image_formats["BBCode"])
        processed_images = []
        for img in images:
            img_url = img[0] if len(img) > 0 else ""
            thumb_url = img[1] if len(img) > 1 else img_url
            img_data = {"image_url": img_url, "thumb_url": thumb_url}
            item_str = img_fmt
            for k, v in img_data.items():
                item_str = item_str.replace(f"#{k}#", str(v))
            processed_images.append(item_str)
            
        data['all_images'] = " ".join(processed_images)
        template = self.get_template(format_mode)
        content = self.process_conditionals(template, data)
        for k, v in data.items():
            content = content.replace(f"#{k}#", str(v))
        return content

# ==========================================
# PART 2: THE UI (TemplateEditor)
# ==========================================

class TemplateEditor(ctk.CTkToplevel):
    def __init__(self, parent, template_mgr, current_mode="BBCode", data_callback=None, update_callback=None):
        super().__init__(parent)
        self.mgr = template_mgr
        self.data_callback = data_callback
        self.update_callback = update_callback # Callback to update Main Window
        self.initial_mode = current_mode
        
        self.title("Template Editor")
        self.geometry("800x700") 
        self.transient(parent)
        
        try:
            icon_path = config.resource_path("logo.ico")
            if os.path.exists(icon_path): self.iconbitmap(icon_path)
        except: pass
        
        self._init_ui()

    def _init_ui(self):
        main = ctk.CTkFrame(self)
        main.pack(fill="both", expand=True, padx=15, pady=15)
        
        # Top Bar
        top = ctk.CTkFrame(main, fg_color="transparent")
        top.pack(fill="x", pady=(0, 10))
        
        ctk.CTkLabel(top, text="Edit Format:", font=("Segoe UI", 12, "bold")).pack(side="left")
        
        # --- FIX: Set variable to the mode passed from Main Window ---
        self.fmt = ctk.StringVar(value=self.initial_mode)
        
        all_keys = self.mgr.get_all_keys()
        self.cb_fmt = MouseWheelComboBox(top, variable=self.fmt, values=all_keys, state="readonly", command=self.load_curr)
        self.cb_fmt.pack(side="left", padx=10)
        
        # Saved Templates Dropdown
        preset_frame = ctk.CTkFrame(main)
        preset_frame.pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(preset_frame, text="Saved Templates:", font=("Segoe UI", 11, "bold")).pack(side="left", padx=5)
        
        self.saved_tmpl_var = ctk.StringVar()
        self.cb_saved = MouseWheelComboBox(preset_frame, variable=self.saved_tmpl_var, values=all_keys, state="readonly")
        self.cb_saved.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        
        ctk.CTkButton(preset_frame, text="Load", width=60, command=self.load_saved_template).pack(side="left", padx=5)

        # Formatting Toolbar
        toolbar = ctk.CTkFrame(main, height=35)
        toolbar.pack(fill="x", pady=(5, 0))
        
        styles = [("B", "Bold"), ("I", "Italic"), ("U", "Underline")]
        for text, mode in styles:
            ctk.CTkButton(toolbar, text=text, width=30, command=lambda m=mode: self.format_text(m)).pack(side="left", padx=2, pady=2)
            
        ctk.CTkButton(toolbar, text="Color", width=50, command=lambda: self.format_complex("Color")).pack(side="left", padx=2, pady=2)

        ctk.CTkFrame(toolbar, width=2, height=20, fg_color="gray").pack(side="left", padx=5)
        
        ctk.CTkLabel(toolbar, text="Size:", width=30).pack(side="left", padx=(5,2))
        self.cb_size = MouseWheelComboBox(toolbar, width=60, values=["10", "12", "14", "18", "24", "36", "48"], command=lambda v: self.apply_from_combo("Size", v))
        self.cb_size.pack(side="left", padx=2)
        self.cb_size.set("") 

        ctk.CTkLabel(toolbar, text="Font:", width=30).pack(side="left", padx=(5,2))
        self.cb_font = MouseWheelComboBox(toolbar, width=120, values=["Arial", "Courier New", "Times New Roman", "Verdana", "Segoe UI", "Helvetica"], command=lambda v: self.apply_from_combo("Font", v))
        self.cb_font.pack(side="left", padx=2)
        self.cb_font.set("")

        # Variable Insertion Bar
        var_bar = ctk.CTkFrame(main, fg_color="transparent")
        var_bar.pack(fill="x", pady=(5, 5))
        vars_to_add = [
            ("Images", "#all_images#"), 
            ("Gal Link", "#gallery_link#"), 
            ("Gal Name", "#gallery_name#"), 
            ("Gal ID", "#gallery_id#"), 
            ("Cover", "[img]#cover_url#[/img]") 
        ]
        for t, v in vars_to_add:
            ctk.CTkButton(var_bar, text=t, width=70, height=24, command=lambda v=v: self.ins(v)).pack(side="left", padx=2)

        # Editor
        self.txt = ctk.CTkTextbox(main, wrap="word", font=("Consolas", 12))
        self.txt.pack(fill="both", expand=True, pady=(0, 15))
        
        # Footer
        btn = ctk.CTkFrame(main, fg_color="transparent")
        btn.pack(fill="x")
        ctk.CTkButton(btn, text="Preview in Browser", command=self.generate_preview).pack(side="left")
        
        ctk.CTkButton(btn, text="Save As New...", command=self.save_as_new, fg_color="green").pack(side="right", padx=(5,0))
        ctk.CTkButton(btn, text="Save Current", command=self.save).pack(side="right")
        
        self.load_curr()

    # --- Formatting Logic ---
    def get_tags(self, mode, value=None):
        fmt = self.fmt.get()
        if mode == "Bold":
            return ("[b]", "[/b]") if fmt == "BBCode" else ("**", "**") if fmt == "Markdown" else ("<b>", "</b>")
        elif mode == "Italic":
            return ("[i]", "[/i]") if fmt == "BBCode" else ("*", "*") if fmt == "Markdown" else ("<i>", "</i>")
        elif mode == "Underline":
            return ("[u]", "[/u]") if fmt == "BBCode" else ("<u>", "</u>")
        elif mode == "Color":
            if fmt == "BBCode": return (f"[color={value}]", "[/color]")
            else: return (f'<span style="color:{value}">', "</span>")
        elif mode == "Size":
            if fmt == "BBCode": return (f"[size={value}]", "[/size]")
            else: return (f'<span style="font-size:{value}px">', "</span>")
        elif mode == "Font":
            if fmt == "BBCode": return (f"[font={value}]", "[/font]")
            else: return (f'<span style="font-family:{value}">', "</span>")
        return ("", "")

    def format_text(self, mode):
        try:
            start = self.txt.index("sel.first")
            end = self.txt.index("sel.last")
            selected_text = self.txt.get(start, end)
            s_tag, e_tag = self.get_tags(mode)
            self.txt.delete(start, end)
            self.txt.insert(start, f"{s_tag}{selected_text}{e_tag}")
        except tk.TclError:
            s_tag, e_tag = self.get_tags(mode)
            self.txt.insert("insert", f"{s_tag}{e_tag}")

    def format_complex(self, mode):
        value = None
        if mode == "Color":
            color = colorchooser.askcolor(title="Select Color")
            if color and color[1]: value = color[1]
        
        if value: self.apply_from_combo(mode, value)

    def apply_from_combo(self, mode, value):
        if not value: return
        try:
            start = self.txt.index("sel.first")
            end = self.txt.index("sel.last")
            selected_text = self.txt.get(start, end)
            s_tag, e_tag = self.get_tags(mode, value)
            self.txt.delete(start, end)
            self.txt.insert(start, f"{s_tag}{selected_text}{e_tag}")
        except tk.TclError:
            s_tag, e_tag = self.get_tags(mode, value)
            self.txt.insert("insert", f"{s_tag}{e_tag}")

    def ins(self, v): 
        self.txt.insert("insert", v)
        self.txt.focus()

    def load_curr(self, _=None): 
        selection = self.fmt.get()
        self.txt.delete("0.0", "end")
        self.txt.insert("0.0", self.mgr.get_template(selection))

    def load_saved_template(self):
        selection = self.saved_tmpl_var.get()
        if not selection: return

        content = self.mgr.get_template(selection)
        self.txt.delete("0.0", "end")
        self.txt.insert("0.0", content)
        
        current_values = self.cb_fmt._values
        if selection not in current_values:
            new_values = current_values + [selection]
            self.cb_fmt.configure(values=new_values)
            
        self.cb_fmt.set(selection)
        self.fmt.set(selection)

    def save(self): 
        name = self.fmt.get()
        self.mgr.set_template(name, self.txt.get("0.0", "end").strip())
        messagebox.showinfo("Saved", f"Template '{name}' updated.")
        # --- FIX: Update Main Window ---
        if self.update_callback:
            self.update_callback(name)

    def save_as_new(self):
        dialog = ctk.CTkInputDialog(text="Enter name for new template:", title="Save As New")
        new_name = dialog.get_input()
        
        if new_name:
            new_name = new_name.strip()
            self.mgr.set_template(new_name, self.txt.get("0.0", "end").strip())
            
            keys = self.mgr.get_all_keys()
            self.cb_saved.configure(values=keys)
            self.cb_fmt.configure(values=keys)
            
            self.cb_fmt.set(new_name)
            self.cb_saved.set(new_name)
            self.fmt.set(new_name)
            
            messagebox.showinfo("Success", f"Created new template: {new_name}")
            # --- FIX: Update Main Window ---
            if self.update_callback:
                self.update_callback(new_name)

    def generate_preview(self):
        if not self.data_callback: return
        files, group_title, thumb_size = self.data_callback()
        if not files:
            return messagebox.showwarning("Preview", "Please add files first.")

        if not thumb_size or not str(thumb_size).isdigit(): thumb_size = "200"

        mock_results = []
        for f in files:
            safe_path = "file:///" + urllib.parse.quote(f.replace("\\", "/"))
            mock_results.append((safe_path, safe_path))

        current_format = self.fmt.get()
        current_template_text = self.txt.get("0.0", "end").strip()
        
        original_tmpl = self.mgr.get_template(current_format)
        self.mgr.set_template(current_format, current_template_text)

        ctx = {
            "gallery_link": "http://localhost/preview",
            "gallery_name": group_title,
            "gallery_id": "PREV_123",
            "cover_url": mock_results[0][1] if mock_results else ""
        }
        
        try:
            raw_output = self.mgr.apply(current_format, ctx, mock_results)
        finally:
            self.mgr.set_template(current_format, original_tmpl)

        html_content = ""
        if current_format == "HTML":
            html_content = raw_output
        else:
            converted = raw_output.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
            converted = converted.replace("[center]", "<div style='text-align:center'>").replace("[/center]", "</div>")
            converted = converted.replace("[b]", "<b>").replace("[/b]", "</b>")
            converted = converted.replace("[i]", "<i>").replace("[/i]", "</i>")
            converted = converted.replace("[u]", "<u>").replace("[/u]", "</u>")
            
            converted = re.sub(r'\[color=(.*?)\](.*?)\[/color\]', r'<span style="color:\1">\2</span>', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\[size=(.*?)\](.*?)\[/size\]', r'<span style="font-size:\1px">\2</span>', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\[font=(.*?)\](.*?)\[/font\]', r'<span style="font-family:\1">\2</span>', converted, flags=re.IGNORECASE)
            
            img_style = f'max-width: {thumb_size}px; border: 1px solid #ccc; margin: 2px;'
            converted = re.sub(r'\[img\](.*?)\[/img\]', f'<img src="\\1" style="{img_style}">', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\[url=(.*?)\]', r'<a href="\1" target="_blank">', converted, flags=re.IGNORECASE)
            converted = converted.replace("[/url]", "</a>")

            html_content = f"""<html><body style='font-family: sans-serif; padding: 20px; background: #f0f0f0;'>
            <div style='background: white; padding: 20px; border: 1px solid #ddd;'>{converted}</div>
            <hr><h3>Raw Code:</h3><textarea style='width:100%; height:200px;'>{raw_output}</textarea></body></html>"""

        try:
            with tempfile.NamedTemporaryFile('w', delete=False, suffix='.html', encoding='utf-8') as f:
                f.write(html_content)
                temp_path = f.name
            webbrowser.open('file://' + temp_path)
        except Exception as e:
            messagebox.showerror("Preview Error", str(e))