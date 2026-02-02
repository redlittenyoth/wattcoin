#!/usr/bin/env python3
"""
WattNode GUI - Windows Desktop Application
Earn WATT by running a light node

Color Palette (matching wattcoin.org):
- Background: #0f0f0f (near black)
- Surface: #1a1a1a (dark gray)
- Border: #2a2a2a (medium gray)
- Text: #ffffff (white)
- Text muted: #888888 (gray)
- Accent: #39ff14 (neon green)
- Accent hover: #32e512
- Error: #ff4444
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import json
import os
import sys
import time
import requests
from datetime import datetime

# === COLORS ===
BG_DARK = "#0f0f0f"
BG_SURFACE = "#1a1a1a"
BG_BORDER = "#2a2a2a"
TEXT_WHITE = "#ffffff"
TEXT_MUTED = "#888888"
ACCENT_GREEN = "#39ff14"
ACCENT_HOVER = "#32e512"
ERROR_RED = "#ff4444"

# === CONFIG ===
API_BASE = "https://wattcoin-production-81a7.up.railway.app"
CONFIG_FILE = "wattnode_config.json"
HEARTBEAT_INTERVAL = 60
POLL_INTERVAL = 5

class WattNodeGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("WattNode")
        self.root.geometry("480x620")
        self.root.configure(bg=BG_DARK)
        self.root.resizable(False, False)
        
        # Try to set icon
        try:
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.dirname(__file__)
            icon_path = os.path.join(base_path, 'assets', 'icon.ico')
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except:
            pass
        
        # State
        self.running = False
        self.node_id = None
        self.wallet = ""
        self.node_name = ""
        self.jobs_completed = 0
        self.total_earned = 0
        self.daemon_thread = None
        
        # Load saved config
        self.load_config()
        
        # Build UI
        self.create_widgets()
        
        # Update status on start
        self.update_status_display()
        
    def load_config(self):
        """Load saved configuration"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    self.wallet = config.get('wallet', '')
                    self.node_name = config.get('name', '')
                    self.node_id = config.get('node_id')
            except:
                pass
    
    def save_config(self):
        """Save configuration"""
        config = {
            'wallet': self.wallet,
            'name': self.node_name,
            'node_id': self.node_id
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    
    def create_widgets(self):
        """Build the UI"""
        # Main container with padding
        main = tk.Frame(self.root, bg=BG_DARK, padx=20, pady=15)
        main.pack(fill=tk.BOTH, expand=True)
        
        # === HEADER ===
        header = tk.Frame(main, bg=BG_DARK)
        header.pack(fill=tk.X, pady=(0, 15))
        
        # Logo placeholder (text for now, will be image)
        logo_frame = tk.Frame(header, bg=BG_DARK)
        logo_frame.pack(side=tk.LEFT)
        
        # Try to load logo
        try:
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.dirname(__file__)
            logo_path = os.path.join(base_path, 'assets', 'logo.png')
            if os.path.exists(logo_path):
                from PIL import Image, ImageTk
                img = Image.open(logo_path).resize((40, 40), Image.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(img)
                logo_label = tk.Label(logo_frame, image=self.logo_img, bg=BG_DARK)
                logo_label.pack(side=tk.LEFT, padx=(0, 10))
        except:
            # Fallback: lightning emoji
            tk.Label(logo_frame, text="⚡", font=("Segoe UI", 24), 
                    fg=ACCENT_GREEN, bg=BG_DARK).pack(side=tk.LEFT, padx=(0, 5))
        
        title_frame = tk.Frame(logo_frame, bg=BG_DARK)
        title_frame.pack(side=tk.LEFT)
        tk.Label(title_frame, text="WattNode", font=("Segoe UI", 18, "bold"),
                fg=TEXT_WHITE, bg=BG_DARK).pack(anchor=tk.W)
        tk.Label(title_frame, text="Earn WATT by running a light node",
                font=("Segoe UI", 9), fg=TEXT_MUTED, bg=BG_DARK).pack(anchor=tk.W)
        
        # === STATUS CARD ===
        status_card = tk.Frame(main, bg=BG_SURFACE, padx=15, pady=15)
        status_card.pack(fill=tk.X, pady=(0, 15))
        
        # Status indicator
        status_row = tk.Frame(status_card, bg=BG_SURFACE)
        status_row.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(status_row, text="Status", font=("Segoe UI", 10),
                fg=TEXT_MUTED, bg=BG_SURFACE).pack(side=tk.LEFT)
        
        self.status_indicator = tk.Label(status_row, text="● Stopped", 
                                         font=("Segoe UI", 10, "bold"),
                                         fg=TEXT_MUTED, bg=BG_SURFACE)
        self.status_indicator.pack(side=tk.RIGHT)
        
        # Stats grid
        stats_frame = tk.Frame(status_card, bg=BG_SURFACE)
        stats_frame.pack(fill=tk.X)
        
        # Jobs completed
        stat1 = tk.Frame(stats_frame, bg=BG_BORDER, padx=12, pady=10)
        stat1.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
        self.jobs_label = tk.Label(stat1, text="0", font=("Segoe UI", 20, "bold"),
                                   fg=ACCENT_GREEN, bg=BG_BORDER)
        self.jobs_label.pack()
        tk.Label(stat1, text="Jobs Done", font=("Segoe UI", 9),
                fg=TEXT_MUTED, bg=BG_BORDER).pack()
        
        # WATT earned
        stat2 = tk.Frame(stats_frame, bg=BG_BORDER, padx=12, pady=10)
        stat2.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))
        self.earned_label = tk.Label(stat2, text="0", font=("Segoe UI", 20, "bold"),
                                     fg=ACCENT_GREEN, bg=BG_BORDER)
        self.earned_label.pack()
        tk.Label(stat2, text="WATT Earned", font=("Segoe UI", 9),
                fg=TEXT_MUTED, bg=BG_BORDER).pack()
        
        # === CONFIG SECTION ===
        config_card = tk.Frame(main, bg=BG_SURFACE, padx=15, pady=15)
        config_card.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(config_card, text="Configuration", font=("Segoe UI", 11, "bold"),
                fg=TEXT_WHITE, bg=BG_SURFACE).pack(anchor=tk.W, pady=(0, 10))
        
        # Wallet address
        tk.Label(config_card, text="Wallet Address", font=("Segoe UI", 9),
                fg=TEXT_MUTED, bg=BG_SURFACE).pack(anchor=tk.W)
        self.wallet_entry = tk.Entry(config_card, font=("Consolas", 10),
                                     bg=BG_BORDER, fg=TEXT_WHITE,
                                     insertbackground=TEXT_WHITE,
                                     relief=tk.FLAT, width=50)
        self.wallet_entry.pack(fill=tk.X, pady=(3, 10), ipady=8)
        self.wallet_entry.insert(0, self.wallet)
        
        # Node name
        tk.Label(config_card, text="Node Name", font=("Segoe UI", 9),
                fg=TEXT_MUTED, bg=BG_SURFACE).pack(anchor=tk.W)
        self.name_entry = tk.Entry(config_card, font=("Segoe UI", 10),
                                   bg=BG_BORDER, fg=TEXT_WHITE,
                                   insertbackground=TEXT_WHITE,
                                   relief=tk.FLAT)
        self.name_entry.pack(fill=tk.X, pady=(3, 10), ipady=8)
        self.name_entry.insert(0, self.node_name or "my-wattnode")
        
        # Node ID (if registered)
        if self.node_id:
            tk.Label(config_card, text="Node ID", font=("Segoe UI", 9),
                    fg=TEXT_MUTED, bg=BG_SURFACE).pack(anchor=tk.W)
            node_id_frame = tk.Frame(config_card, bg=BG_BORDER)
            node_id_frame.pack(fill=tk.X, pady=(3, 0))
            tk.Label(node_id_frame, text=self.node_id, font=("Consolas", 10),
                    fg=ACCENT_GREEN, bg=BG_BORDER, pady=8, padx=8).pack(side=tk.LEFT)
        
        # === BUTTONS ===
        btn_frame = tk.Frame(main, bg=BG_DARK)
        btn_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Start/Stop button
        self.start_btn = tk.Button(btn_frame, text="▶  Start Node", 
                                   font=("Segoe UI", 11, "bold"),
                                   bg=ACCENT_GREEN, fg=BG_DARK,
                                   activebackground=ACCENT_HOVER,
                                   activeforeground=BG_DARK,
                                   relief=tk.FLAT, cursor="hand2",
                                   command=self.toggle_node)
        self.start_btn.pack(fill=tk.X, ipady=12)
        
        # Register button (if not registered)
        if not self.node_id:
            self.register_btn = tk.Button(btn_frame, text="Register Node (requires 10,000 WATT stake)",
                                          font=("Segoe UI", 10),
                                          bg=BG_SURFACE, fg=TEXT_WHITE,
                                          activebackground=BG_BORDER,
                                          relief=tk.FLAT, cursor="hand2",
                                          command=self.show_register_dialog)
            self.register_btn.pack(fill=tk.X, pady=(10, 0), ipady=10)
        
        # === LOG ===
        log_frame = tk.Frame(main, bg=BG_SURFACE)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(log_frame, text="Activity Log", font=("Segoe UI", 10),
                fg=TEXT_MUTED, bg=BG_SURFACE, pady=8, padx=10).pack(anchor=tk.W)
        
        self.log_text = tk.Text(log_frame, font=("Consolas", 9),
                                bg=BG_BORDER, fg=TEXT_MUTED,
                                relief=tk.FLAT, height=8, wrap=tk.WORD,
                                state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # Configure log colors
        self.log_text.tag_configure("success", foreground=ACCENT_GREEN)
        self.log_text.tag_configure("error", foreground=ERROR_RED)
        self.log_text.tag_configure("info", foreground=TEXT_WHITE)
        
        self.log("WattNode GUI initialized")
        if self.node_id:
            self.log(f"Loaded node: {self.node_id}", "success")
    
    def log(self, message, tag="info"):
        """Add message to log"""
        self.log_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] ", "info")
        self.log_text.insert(tk.END, f"{message}\n", tag)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def update_status_display(self):
        """Update status indicator and stats"""
        if self.running:
            self.status_indicator.config(text="● Running", fg=ACCENT_GREEN)
            self.start_btn.config(text="■  Stop Node", bg=ERROR_RED)
        else:
            self.status_indicator.config(text="● Stopped", fg=TEXT_MUTED)
            self.start_btn.config(text="▶  Start Node", bg=ACCENT_GREEN)
        
        self.jobs_label.config(text=str(self.jobs_completed))
        self.earned_label.config(text=str(self.total_earned))
    
    def toggle_node(self):
        """Start or stop the node"""
        if self.running:
            self.stop_node()
        else:
            self.start_node()
    
    def start_node(self):
        """Start the node daemon"""
        # Validate
        self.wallet = self.wallet_entry.get().strip()
        self.node_name = self.name_entry.get().strip()
        
        if not self.wallet:
            messagebox.showerror("Error", "Please enter your wallet address")
            return
        
        if not self.node_id:
            messagebox.showwarning("Not Registered", 
                "Node not registered. Please register first by staking 10,000 WATT.")
            return
        
        # Save config
        self.save_config()
        
        # Start daemon thread
        self.running = True
        self.update_status_display()
        self.log("Starting node...", "info")
        
        self.daemon_thread = threading.Thread(target=self.daemon_loop, daemon=True)
        self.daemon_thread.start()
    
    def stop_node(self):
        """Stop the node daemon"""
        self.running = False
        self.update_status_display()
        self.log("Node stopped", "info")
    
    def daemon_loop(self):
        """Main daemon loop (runs in background thread)"""
        last_heartbeat = 0
        
        self.log("Node started!", "success")
        self.log(f"Node ID: {self.node_id}")
        self.log("Listening for jobs...")
        
        while self.running:
            try:
                # Heartbeat
                if time.time() - last_heartbeat > HEARTBEAT_INTERVAL:
                    self.send_heartbeat()
                    last_heartbeat = time.time()
                
                # Poll for jobs
                jobs = self.poll_jobs()
                
                for job in jobs:
                    if not self.running:
                        break
                    self.process_job(job)
                
                time.sleep(POLL_INTERVAL)
                
            except Exception as e:
                self.log(f"Error: {e}", "error")
                time.sleep(10)
        
        self.log("Daemon stopped")
    
    def send_heartbeat(self):
        """Send heartbeat to keep node active"""
        try:
            resp = requests.post(f"{API_BASE}/api/v1/nodes/heartbeat",
                               json={"node_id": self.node_id}, timeout=15)
            if resp.status_code == 200:
                # Silently succeed
                pass
            else:
                self.log(f"Heartbeat failed: {resp.status_code}", "error")
        except Exception as e:
            self.log(f"Heartbeat error: {e}", "error")
    
    def poll_jobs(self):
        """Poll for available jobs"""
        try:
            resp = requests.get(f"{API_BASE}/api/v1/nodes/jobs",
                              params={"node_id": self.node_id}, timeout=15)
            if resp.status_code == 200:
                return resp.json().get("jobs", [])
        except:
            pass
        return []
    
    def process_job(self, job):
        """Process a single job"""
        job_id = job.get("job_id")
        job_type = job.get("type")
        reward = job.get("reward", 0)
        payload = job.get("payload", {})
        
        self.log(f"Job received: {job_id[:20]}...")
        self.log(f"  Type: {job_type}, Reward: {reward} WATT")
        
        # Claim job
        try:
            resp = requests.post(f"{API_BASE}/api/v1/nodes/jobs/{job_id}/claim",
                               json={"node_id": self.node_id}, timeout=15)
            if resp.status_code != 200:
                self.log(f"  Could not claim (already taken?)", "error")
                return
        except Exception as e:
            self.log(f"  Claim error: {e}", "error")
            return
        
        # Execute job
        result = self.execute_job(job_type, payload)
        
        # Submit result
        try:
            resp = requests.post(f"{API_BASE}/api/v1/nodes/jobs/{job_id}/complete",
                               json={"node_id": self.node_id, "result": result}, 
                               timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                self.jobs_completed += 1
                self.total_earned += reward
                
                # Update UI (from main thread)
                self.root.after(0, self.update_status_display)
                
                if data.get("payout_tx"):
                    self.log(f"  ✓ Completed! +{reward} WATT", "success")
                else:
                    self.log(f"  ✓ Completed! Payout pending", "success")
            else:
                self.log(f"  Submit failed: {resp.status_code}", "error")
        except Exception as e:
            self.log(f"  Submit error: {e}", "error")
    
    def execute_job(self, job_type, payload):
        """Execute a job locally"""
        if job_type == "scrape":
            return self.do_scrape(payload)
        else:
            return {"success": False, "error": f"Unknown job type: {job_type}"}
    
    def do_scrape(self, payload):
        """Execute a scrape job"""
        url = payload.get("url", "")
        fmt = payload.get("format", "text")
        
        try:
            from bs4 import BeautifulSoup
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            
            if fmt == "html":
                content = resp.text
            elif fmt == "json":
                content = resp.json()
            else:
                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer"]):
                    tag.decompose()
                content = soup.get_text(separator=" ", strip=True)
            
            return {
                "success": True,
                "content": content[:50000],  # Limit size
                "status_code": resp.status_code
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def show_register_dialog(self):
        """Show registration dialog"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Register Node")
        dialog.geometry("420x300")
        dialog.configure(bg=BG_DARK)
        dialog.transient(self.root)
        dialog.grab_set()
        
        frame = tk.Frame(dialog, bg=BG_DARK, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(frame, text="Register Your Node", font=("Segoe UI", 14, "bold"),
                fg=TEXT_WHITE, bg=BG_DARK).pack(pady=(0, 15))
        
        tk.Label(frame, text="1. Send 10,000 WATT to treasury wallet:",
                font=("Segoe UI", 10), fg=TEXT_MUTED, bg=BG_DARK).pack(anchor=tk.W)
        
        treasury_frame = tk.Frame(frame, bg=BG_BORDER)
        treasury_frame.pack(fill=tk.X, pady=(5, 15))
        treasury_addr = tk.Label(treasury_frame, 
                                text="Atu5phbGGGFogbKhi259czz887dSdTfXwJxwbuE5aF5q",
                                font=("Consolas", 9), fg=ACCENT_GREEN, bg=BG_BORDER,
                                padx=10, pady=8)
        treasury_addr.pack(side=tk.LEFT)
        
        def copy_treasury():
            self.root.clipboard_clear()
            self.root.clipboard_append("Atu5phbGGGFogbKhi259czz887dSdTfXwJxwbuE5aF5q")
            copy_btn.config(text="Copied!")
            dialog.after(1500, lambda: copy_btn.config(text="Copy"))
        
        copy_btn = tk.Button(treasury_frame, text="Copy", font=("Segoe UI", 9),
                            bg=BG_SURFACE, fg=TEXT_WHITE, relief=tk.FLAT,
                            command=copy_treasury)
        copy_btn.pack(side=tk.RIGHT, padx=5)
        
        tk.Label(frame, text="2. Paste your transaction signature:",
                font=("Segoe UI", 10), fg=TEXT_MUTED, bg=BG_DARK).pack(anchor=tk.W, pady=(10, 0))
        
        tx_entry = tk.Entry(frame, font=("Consolas", 9), bg=BG_BORDER, fg=TEXT_WHITE,
                           insertbackground=TEXT_WHITE, relief=tk.FLAT, width=50)
        tx_entry.pack(fill=tk.X, pady=(5, 15), ipady=8)
        
        def do_register():
            tx_sig = tx_entry.get().strip()
            wallet = self.wallet_entry.get().strip()
            name = self.name_entry.get().strip() or "my-wattnode"
            
            if not tx_sig:
                messagebox.showerror("Error", "Please enter transaction signature")
                return
            if not wallet:
                messagebox.showerror("Error", "Please enter wallet address first")
                return
            
            try:
                resp = requests.post(f"{API_BASE}/api/v1/nodes/register",
                                   json={
                                       "wallet": wallet,
                                       "stake_tx": tx_sig,
                                       "capabilities": ["scrape"],
                                       "name": name
                                   }, timeout=30)
                data = resp.json()
                
                if data.get("success"):
                    self.node_id = data.get("node_id")
                    self.wallet = wallet
                    self.node_name = name
                    self.save_config()
                    
                    messagebox.showinfo("Success", 
                        f"Node registered!\n\nNode ID: {self.node_id}\nStake: {data.get('stake_amount')} WATT")
                    dialog.destroy()
                    
                    # Refresh main window
                    self.root.destroy()
                    main()
                else:
                    messagebox.showerror("Error", data.get("error", "Registration failed"))
            except Exception as e:
                messagebox.showerror("Error", str(e))
        
        register_btn = tk.Button(frame, text="Register", font=("Segoe UI", 11, "bold"),
                                bg=ACCENT_GREEN, fg=BG_DARK, relief=tk.FLAT,
                                command=do_register)
        register_btn.pack(fill=tk.X, ipady=10)


def main():
    root = tk.Tk()
    app = WattNodeGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
