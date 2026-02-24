import sys
import os
import subprocess
import threading
import time
import webbrowser
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item

# Global variables
server_process = None
icon = None

def create_image(width, height, color1, color2):
    """Generate a simple, clean tray icon - blue circle with white 'I'"""
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)
    # Draw filled blue circle
    dc.ellipse([2, 2, width - 3, height - 3], fill='#0284c7', outline='#0369a1', width=1)
    # Draw white "I" letter in center
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("arial.ttf", int(width * 0.55))
    except Exception:
        font = ImageFont.load_default()
    dc.text((width / 2, height / 2), "I", fill='white', font=font, anchor='mm')
    return image

def start_server():
    """Start the Flask server subprocess"""
    global server_process
    if server_process:
        stop_server()
    
    print("Starting IFAS-Assistent Server...")
    # Run run.py using the same python interpreter
    server_process = subprocess.Popen([sys.executable, 'run.py'])

def stop_server():
    """Stop the Flask server subprocess"""
    global server_process
    if server_process:
        print("Stopping Server...")
        server_process.terminate()
        try:
            server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_process.kill()
        server_process = None

def on_open(icon, item):
    """Open the web interface"""
    webbrowser.open('http://localhost:5050')

def on_restart(icon, item):
    """Restart the server"""
    print("Restarting...")
    stop_server()
    time.sleep(1)
    start_server()

def on_quit(icon, item):
    """Quit the application"""
    print("Quitting...")
    stop_server()
    icon.stop()

def setup(icon):
    """Setup function called when icon is ready"""
    icon.visible = True
    start_server()

def main():
    # Helper to find run.py if we are in a different cwd
    if not os.path.exists('run.py'):
        # Try to change to script directory
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    if not os.path.exists('run.py'):
        print("Error: run.py not found in current directory.")
        return

    # Create system tray icon
    icon_path = os.path.join('app', 'static', 'img', 'logo.png')
    if os.path.exists(icon_path):
        try:
            image = Image.open(icon_path)
        except Exception as e:
            print(f"Error loading icon: {e}")
            image = create_image(64, 64, 'blue', 'white')
    else:
        image = create_image(64, 64, 'blue', 'white')
    
    menu = (
        item('IFAS-Assistent öffnen', on_open, default=True),
        item('Server neustarten', on_restart),
        item('Beenden', on_quit)
    )
    
    global icon
    icon = pystray.Icon("name", image, "IFAS-Assistent", menu)
    icon.run(setup)

if __name__ == '__main__':
    main()
