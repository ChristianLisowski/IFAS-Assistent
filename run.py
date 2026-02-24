#!/usr/bin/env python
"""
IFAS-Assistent - Application Entry Point
Run this script to start the Flask application.
"""
import os
import sys
import webbrowser
from threading import Timer

# Ensure the app directory is in the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

# Create the Flask application
app = create_app()


def open_browser():
    """Open the default web browser after a short delay"""
    webbrowser.open('http://localhost:5050')


if __name__ == '__main__':
    # Print startup message
    print("=" * 60)
    print("  IFAS-Assistent v2.0")
    print("  Intelligente Posteingangsverarbeitung")
    print("=" * 60)
    print()
    print("  Server startet auf: http://localhost:5050")
    print("  Drücken Sie STRG+C zum Beenden")
    print()
    print("  Standard-Login:")
    print("    Admin:         admin / admin123")
    print("    Sachbearbeiter: sachbearbeiter / user123")
    print("=" * 60)
    print()
    
    # Open browser after 1.5 seconds
    Timer(1.5, open_browser).start()
    
    # Run the Flask development server
    app.run(
        host='0.0.0.0',
        port=5050,
        debug=True,
        use_reloader=False  # Disable reloader to prevent double browser open
    )
