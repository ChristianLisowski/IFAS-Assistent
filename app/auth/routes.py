"""
Authentication Blueprint
Handles login, logout, and user session management.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime

from ..models import db, User, AuditLog

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            if not user.is_active:
                flash('Ihr Benutzerkonto ist deaktiviert.', 'error')
                return render_template('auth/login.html')
            
            login_user(user, remember=remember)
            user.last_login = datetime.utcnow()
            
            # Audit log
            log = AuditLog(
                user_id=user.id,
                action='login',
                ip_address=request.remote_addr
            )
            db.session.add(log)
            db.session.commit()
            
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('main.dashboard'))
        else:
            flash('Ungültiger Benutzername oder Passwort.', 'error')
    
    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """Handle user logout"""
    # Audit log
    log = AuditLog(
        user_id=current_user.id,
        action='logout',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    logout_user()
    flash('Sie wurden erfolgreich abgemeldet.', 'success')
    return redirect(url_for('auth.login'))
