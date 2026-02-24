"""
Admin Blueprint Package
"""
from functools import wraps
from flask_login import current_user
from flask import flash, redirect, url_for


def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.is_admin:
            flash('Sie benötigen Administratorrechte für diese Seite.', 'error')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


from .routes import admin_bp

