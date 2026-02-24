"""
Admin Blueprint Routes
User management, Category configuration, Input source configuration
"""
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from functools import wraps
import json

from ..models import db, User, Category, CategoryField, InputSource, AuditLog

admin_bp = Blueprint('admin', __name__)


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


# ============================================================================
# DASHBOARD
# ============================================================================
@admin_bp.route('/')
@login_required
@admin_required
def index():
    """Admin dashboard"""
    user_count = User.query.count()
    category_count = Category.query.count()
    source_count = InputSource.query.count()
    
    recent_logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(20).all()
    
    return render_template('admin/index.html',
                          user_count=user_count,
                          category_count=category_count,
                          source_count=source_count,
                          recent_logs=recent_logs)


# ============================================================================
# USER MANAGEMENT
# ============================================================================
@admin_bp.route('/users')
@login_required
@admin_required
def users():
    """User management page"""
    users = User.query.order_by(User.username).all()
    return render_template('admin/users.html', users=users)


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_user():
    """Create new user"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        display_name = request.form.get('display_name', '').strip()
        role = request.form.get('role', 'user')
        
        if User.query.filter_by(username=username).first():
            flash('Benutzername existiert bereits.', 'error')
            return render_template('admin/user_form.html', user=None)
        
        if User.query.filter_by(email=email).first():
            flash('E-Mail-Adresse existiert bereits.', 'error')
            return render_template('admin/user_form.html', user=None)
        
        user = User(
            username=username,
            email=email,
            display_name=display_name,
            role=role,
            is_active=True
        )
        user.set_password(password)
        db.session.add(user)
        
        # Audit log
        log = AuditLog(
            user_id=current_user.id,
            action='user_created',
            entity_type='user',
            entity_id=user.id,
            details_json=json.dumps({'username': username}),
            ip_address=request.remote_addr
        )
        db.session.add(log)
        db.session.commit()
        
        flash(f'Benutzer "{username}" erfolgreich erstellt.', 'success')
        return redirect(url_for('admin.users'))
    
    return render_template('admin/user_form.html', user=None)


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    """Edit existing user"""
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        user.email = request.form.get('email', '').strip()
        user.display_name = request.form.get('display_name', '').strip()
        user.role = request.form.get('role', 'user')
        user.is_active = request.form.get('is_active') == 'on'
        
        new_password = request.form.get('password', '')
        if new_password:
            user.set_password(new_password)
        
        db.session.commit()
        flash('Benutzer aktualisiert.', 'success')
        return redirect(url_for('admin.users'))
    
    return render_template('admin/user_form.html', user=user)


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    """Delete user"""
    if user_id == current_user.id:
        flash('Sie können sich nicht selbst löschen.', 'error')
        return redirect(url_for('admin.users'))
    
    user = User.query.get_or_404(user_id)
    username = user.username
    db.session.delete(user)
    db.session.commit()
    
    flash(f'Benutzer "{username}" gelöscht.', 'success')
    return redirect(url_for('admin.users'))


# ============================================================================
# CATEGORY MANAGEMENT
# ============================================================================
@admin_bp.route('/categories')
@login_required
@admin_required
def categories():
    """Category management page"""
    categories = Category.query.order_by(Category.position, Category.name).all()
    return render_template('admin/categories.html', categories=categories)


@admin_bp.route('/categories/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_category():
    """Create new category"""
    if request.method == 'POST':
        category = Category(
            name=request.form.get('name', '').strip().lower().replace(' ', '_'),
            display_name=request.form.get('display_name', '').strip(),
            icon=request.form.get('icon', '📄'),
            color=request.form.get('color', '#6366f1'),
            ifas_art=request.form.get('ifas_art', '').strip(),
            ifas_zusatzart=request.form.get('ifas_zusatzart', '').strip(),
            keywords=request.form.get('keywords', '').strip(),
            description=request.form.get('description', '').strip(),
            is_active=True
        )
        db.session.add(category)
        db.session.commit()
        
        flash(f'Kategorie "{category.display_name}" erstellt.', 'success')
        return redirect(url_for('admin.edit_category', category_id=category.id))
    
    return render_template('admin/category_form.html', category=None)


@admin_bp.route('/categories/<int:category_id>')
@login_required
@admin_required
def edit_category(category_id):
    """Edit category and its fields"""
    category = Category.query.get_or_404(category_id)
    fields = CategoryField.query.filter_by(category_id=category_id).order_by(CategoryField.position).all()
    return render_template('admin/category_form.html', category=category, fields=fields)


@admin_bp.route('/categories/<int:category_id>/update', methods=['POST'])
@login_required
@admin_required
def update_category(category_id):
    """Update category details"""
    category = Category.query.get_or_404(category_id)
    
    category.display_name = request.form.get('display_name', '').strip()
    category.icon = request.form.get('icon', '📄')
    category.color = request.form.get('color', '#6366f1')
    category.ifas_art = request.form.get('ifas_art', '').strip()
    category.ifas_zusatzart = request.form.get('ifas_zusatzart', '').strip()
    category.keywords = request.form.get('keywords', '').strip()
    category.description = request.form.get('description', '').strip()
    category.is_active = request.form.get('is_active') == 'on'
    
    db.session.commit()
    flash('Kategorie aktualisiert.', 'success')
    return redirect(url_for('admin.edit_category', category_id=category_id))


@admin_bp.route('/categories/<int:category_id>/fields', methods=['POST'])
@login_required
@admin_required
def add_field(category_id):
    """Add a new field to category"""
    category = Category.query.get_or_404(category_id)
    
    # Get next position
    max_pos = db.session.query(db.func.max(CategoryField.position)).filter_by(category_id=category_id).scalar() or 0
    
    field = CategoryField(
        category_id=category_id,
        label=request.form.get('label', 'Neues Feld'),
        key=request.form.get('key', f'field_{max_pos + 1}'),
        content_id_ifas=request.form.get('content_id_ifas', ''),
        field_type=request.form.get('field_type', 'text'),
        options=request.form.get('options', ''),
        required=request.form.get('required') == 'on',
        show_in_validation=request.form.get('show_in_validation', 'on') == 'on',
        auto_fill=request.form.get('auto_fill', 'on') == 'on',
        position=max_pos + 1
    )
    db.session.add(field)
    db.session.commit()
    
    flash('Feld hinzugefügt.', 'success')
    return redirect(url_for('admin.edit_category', category_id=category_id))


@admin_bp.route('/categories/<int:category_id>/fields/<int:field_id>', methods=['POST'])
@login_required
@admin_required
def update_field(category_id, field_id):
    """Update a category field"""
    field = CategoryField.query.filter_by(id=field_id, category_id=category_id).first_or_404()
    
    field.label = request.form.get('label', field.label)
    field.key = request.form.get('key', field.key)
    field.content_id_ifas = request.form.get('content_id_ifas', '')
    field.field_type = request.form.get('field_type', 'text')
    field.options = request.form.get('options', '')
    field.placeholder = request.form.get('placeholder', '')
    field.required = request.form.get('required') == 'on'
    field.show_in_validation = request.form.get('show_in_validation') == 'on'
    field.auto_fill = request.form.get('auto_fill') == 'on'
    
    try:
        field.position = int(request.form.get('position', field.position))
    except ValueError:
        pass
    
    db.session.commit()
    flash('Feld aktualisiert.', 'success')
    return redirect(url_for('admin.edit_category', category_id=category_id))


@admin_bp.route('/categories/<int:category_id>/fields/<int:field_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_field(category_id, field_id):
    """Delete a category field"""
    field = CategoryField.query.filter_by(id=field_id, category_id=category_id).first_or_404()
    db.session.delete(field)
    db.session.commit()
    
    flash('Feld gelöscht.', 'success')
    return redirect(url_for('admin.edit_category', category_id=category_id))


@admin_bp.route('/categories/<int:category_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_category(category_id):
    """Delete category and all its fields"""
    category = Category.query.get_or_404(category_id)
    name = category.display_name
    db.session.delete(category)
    db.session.commit()
    
    flash(f'Kategorie "{name}" gelöscht.', 'success')
    return redirect(url_for('admin.categories'))


# ============================================================================
# INPUT SOURCE MANAGEMENT
# ============================================================================
@admin_bp.route('/inputs')
@login_required
@admin_required
def inputs():
    """Input source configuration"""
    sources = InputSource.query.all()
    return render_template('admin/inputs.html', sources=sources)


@admin_bp.route('/inputs/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_input():
    """Create new input source"""
    if request.method == 'POST':
        source_type = request.form.get('source_type', 'folder')
        name = request.form.get('name', '').strip()
        
        source = InputSource(
            name=name,
            source_type=source_type,
            is_active=request.form.get('is_active') == 'on',
            poll_interval=int(request.form.get('poll_interval', 60))
        )
        
        # Build config based on type
        config = {}
        if source_type in ('folder', 'network'):
            config = {
                'path': request.form.get('path', ''),
                'watch_subdirs': request.form.get('watch_subdirs') == 'on',
                'file_patterns': ['*.pdf', '*.PDF', '*.msg', '*.eml']
            }
            source.trash_folder = request.form.get('folder_trash', 'Trash')
            source.processed_folder = request.form.get('folder_processed', 'Processed')
            source.discarded_folder = request.form.get('folder_discarded', '')
        elif source_type == 'imap':
            config = {
                'server': request.form.get('imap_server', ''),
                'port': int(request.form.get('imap_port', 993)),
                'username': request.form.get('imap_user', ''),
                'password': request.form.get('imap_pass', ''),
                'folder': request.form.get('imap_folder', 'INBOX'),
                'ssl': request.form.get('imap_ssl') == 'on'
            }
            # Save trash/processed folder to model columns, not config json (or both? model prefers columns now)
            source.trash_folder = request.form.get('imap_trash', 'Trash')
            source.processed_folder = request.form.get('imap_processed', 'Processed')
            source.discarded_folder = request.form.get('imap_discarded', '')
            
        elif source_type == 'ifas_api':
            config = {
                'endpoint': request.form.get('api_endpoint', ''),
                'api_key': request.form.get('api_key', '')
            }
        
        source.set_config(config)
        db.session.add(source)
        db.session.commit()
        
        flash(f'Eingangslayer "{name}" erstellt.', 'success')
        return redirect(url_for('admin.inputs'))
    
    return render_template('admin/input_form.html', source=None)


@admin_bp.route('/inputs/<int:source_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_input(source_id):
    """Edit input source"""
    source = InputSource.query.get_or_404(source_id)
    
    if request.method == 'POST':
        source.name = request.form.get('name', '').strip()
        source.is_active = request.form.get('is_active') == 'on'
        source.poll_interval = int(request.form.get('poll_interval', 60))
        
        # Update config
        config = source.get_config()
        if source.source_type in ('folder', 'network'):
            config['path'] = request.form.get('path', '')
            config['watch_subdirs'] = request.form.get('watch_subdirs') == 'on'
            
            source.trash_folder = request.form.get('folder_trash', 'Trash')
            source.processed_folder = request.form.get('folder_processed', 'Processed')
            source.discarded_folder = request.form.get('folder_discarded', '')
        elif source.source_type == 'imap':
            config['server'] = request.form.get('imap_server', '')
            config['port'] = int(request.form.get('imap_port', 993))
            config['username'] = request.form.get('imap_user', '')
            if request.form.get('imap_pass'):  # Only update if new password provided
                config['password'] = request.form.get('imap_pass', '')
            config['folder'] = request.form.get('imap_folder', 'INBOX')
            config['ssl'] = request.form.get('imap_ssl') == 'on'
            
            # Update separate columns
            source.trash_folder = request.form.get('imap_trash', 'Trash')
            source.processed_folder = request.form.get('imap_processed', 'Processed')
            source.discarded_folder = request.form.get('imap_discarded', '')
            
        elif source.source_type == 'ifas_api':
            config['endpoint'] = request.form.get('api_endpoint', '')
            if request.form.get('api_key'):
                config['api_key'] = request.form.get('api_key', '')
        
        source.set_config(config)
        db.session.commit()
        
        flash('Eingangslayer aktualisiert.', 'success')
        return redirect(url_for('admin.inputs'))
    
    return render_template('admin/input_form.html', source=source)


@admin_bp.route('/inputs/<int:source_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_input(source_id):
    """Delete input source"""
    source = InputSource.query.get_or_404(source_id)
    name = source.name
    db.session.delete(source)
    db.session.commit()
    
    flash(f'Eingangslayer "{name}" gelöscht.', 'success')
    return redirect(url_for('admin.inputs'))


@admin_bp.route('/inputs/<int:source_id>/test', methods=['POST'])
@login_required
@admin_required
def test_input(source_id):
    """Test connection to input source"""
    source = InputSource.query.get_or_404(source_id)
    config = source.get_config()
    
    success = False
    message = ""
    
    if source.source_type == 'folder':
        import os
        path = config.get('path', '')
        if os.path.exists(path) and os.path.isdir(path):
            success = True
            files = [f for f in os.listdir(path) if f.endswith(('.pdf', '.PDF', '.msg', '.eml'))]
            message = f"Verbindung erfolgreich. {len(files)} Dateien gefunden."
        else:
            message = f"Ordner '{path}' existiert nicht oder ist nicht erreichbar."
    
    elif source.source_type == 'imap':
        try:
            import imaplib
            server = config.get('server', '')
            port = config.get('port', 993)
            username = config.get('username', '')
            password = config.get('password', '')
            use_ssl = config.get('ssl', True)
            
            if use_ssl:
                mail = imaplib.IMAP4_SSL(server, port)
            else:
                mail = imaplib.IMAP4(server, port)
            
            mail.login(username, password)
            mail.select(config.get('folder', 'INBOX'))
            _, messages = mail.search(None, 'UNSEEN')
            count = len(messages[0].split())
            mail.logout()
            
            success = True
            message = f"Verbindung erfolgreich. {count} ungelesene Nachrichten."
        except Exception as e:
            message = f"Verbindungsfehler: {str(e)}"
    
    return jsonify({'success': success, 'message': message})


@admin_bp.route('/imap/folders', methods=['POST'])
@login_required
@admin_required
def list_imap_folders():
    """List IMAP folders for given credentials"""
    data = request.get_json()
    
    server = data.get('server')
    port = int(data.get('port', 993))
    username = data.get('username')
    password = data.get('password')
    use_ssl = data.get('ssl', True)
    
    try:
        import imaplib
        if use_ssl:
            mail = imaplib.IMAP4_SSL(server, port)
        else:
            mail = imaplib.IMAP4(server, port)
        
        mail.login(username, password)
        status, folders = mail.list()
        mail.logout()
        
        folder_list = []
        if status == 'OK':
            for f in folders:
                try:
                    # Basic parsing: '(\HasNoChildren) "/" "INBOX"'
                    name = f.decode().split(' "|" ')[-1].strip().replace('"', '')
                    # Fallback/better parsing
                    import re
                    match = re.search(r'"([^"]+)"$', f.decode())
                    if match:
                        name = match.group(1)
                    else:
                        tokens = f.decode().split(' ')
                        name = tokens[-1].replace('"', '')
                    
                    folder_list.append(name)
                except:
                    pass
        
        return jsonify({'success': True, 'folders': sorted(folder_list)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/imap/folders/create', methods=['POST'])
@login_required
@admin_required
def create_imap_folder():
    """Create a new IMAP folder"""
    data = request.get_json()
    
    server = data.get('server')
    port = int(data.get('port', 993))
    username = data.get('username')
    password = data.get('password')
    use_ssl = data.get('ssl', True)
    folder_name = data.get('folder_name')
    
    if not folder_name:
        return jsonify({'success': False, 'error': 'Kein Ordnername angegeben'})
        
    try:
        import imaplib
        if use_ssl:
            mail = imaplib.IMAP4_SSL(server, port)
        else:
            mail = imaplib.IMAP4(server, port)
        
        mail.login(username, password)
        status, response = mail.create(folder_name)
        mail.logout()
        
        if status == 'OK':
            return jsonify({'success': True, 'message': f'Ordner "{folder_name}" erstellt'})
        else:
            return jsonify({'success': False, 'error': f'Fehler: {response}'})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})



# ============================================================================
# SETTINGS
# ============================================================================
@admin_bp.route('/appearance', methods=['GET', 'POST'])
@login_required
@admin_required
def appearance():
    """Appearance settings page"""
    from ..models import AppConfig
    
    if request.method == 'POST':
        # Save settings
        settings_map = {
            'theme_mode': request.form.get('theme_mode', 'light'),
            'theme_ambient': request.form.get('theme_ambient', '50'),
            # 'theme_color_primary': request.form.get('theme_color_primary', '#6366f1'), # Future use
        }
        
        for key, value in settings_map.items():
            config = AppConfig.query.filter_by(key=key).first()
            if config:
                config.value = value
            else:
                config = AppConfig(key=key, value=value)
                db.session.add(config)
        
        db.session.commit()
        # flash('Erscheinungsbild gespeichert.', 'success') # Removed to prevent spam
        return redirect(url_for('admin.appearance'))
    
    # Load current settings
    config_entries = AppConfig.query.all()
    config = {c.key: c.value for c in config_entries}
    
    return render_template('admin/appearance.html', config=config)

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    """System settings page"""
    from ..models import AppConfig, User, db
    import json
    
    if request.method == 'POST':
        # 1. Save System Settings
        settings_map = {
            'lmstudio_url': request.form.get('lmstudio_url', 'http://localhost:1234'),
            'lmstudio_model': request.form.get('lmstudio_model', ''),
            'ocr_strategy': request.form.get('ocr_strategy', 'standard'),
            'lmstudio_ocr_model': request.form.get('lmstudio_ocr_model', ''),
            'tesseract_cmd': request.form.get('tesseract_cmd', ''),
            'ifas_api_url': request.form.get('ifas_api_url', ''),
            'ifas_api_user': request.form.get('ifas_api_user', ''),
            'ifas_mock_mode': 'true' if request.form.get('ifas_mock_mode') else 'false',
            'upload_folder': request.form.get('upload_folder', 'uploads'),
            'processed_folder': request.form.get('processed_folder', 'processed'),
            'ai_system_prompt': request.form.get('ai_system_prompt', ''),
            'smtp_server': request.form.get('smtp_server', ''),
            'smtp_port': request.form.get('smtp_port', '587'),
            'smtp_user': request.form.get('smtp_user', ''),
            'smtp_ssl': 'true' if request.form.get('smtp_ssl') else 'false',
            'admin_email': request.form.get('admin_email', ''), # Keep for legacy/fallback
        }
        
        # Only update passwords if provided
        if request.form.get('ifas_api_password'):
            settings_map['ifas_api_password'] = request.form.get('ifas_api_password')
            
        if request.form.get('smtp_password'):
            settings_map['smtp_password'] = request.form.get('smtp_password')
        
        for key, value in settings_map.items():
            config = AppConfig.query.filter_by(key=key).first()
            if config:
                config.value = value
            else:
                db.session.add(AppConfig(key=key, value=value))
        
        # 2. Save User Notification Preferences
        # Format: user_{id}_notify_error, user_{id}_notify_pending
        users = User.query.all()
        for user in users:
            prefs = {}
            if request.form.get(f'user_{user.id}_notify_error'):
                prefs['error'] = True
            if request.form.get(f'user_{user.id}_notify_pending'):
                prefs['pending_overflow'] = True
            
            user.notification_preferences = json.dumps(prefs)
        
        db.session.commit()
        flash('Einstellungen gespeichert', 'success')
        return redirect(url_for('admin.settings'))
        
    config = {c.key: c.value for c in AppConfig.query.all()}
    users = User.query.all() # Fetch users for the list
    return render_template('admin/settings.html', config=config, users=users)


@admin_bp.route('/settings/detect-tesseract')
@login_required
def detect_tesseract():
    """Attempt to auto-detect Tesseract executable"""
    import shutil
    import os
    import shutil
    import os
    from flask import jsonify, current_app

    # 1. Check PATH
    path = shutil.which('tesseract')
    if path:
        return jsonify({'found': True, 'path': path})
        
    # 2. Check Common Windows Paths
    common_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expanduser(r"~\AppData\Local\Tesseract-OCR\tesseract.exe"),
        # Check local folder
        os.path.join(current_app.root_path, '..', 'tesseract', 'tesseract.exe'),
        os.path.join(current_app.root_path, '..', 'bin', 'tesseract', 'tesseract.exe')
    ]
    
    for p in common_paths:
        if os.path.exists(p):
             return jsonify({'found': True, 'path': os.path.abspath(p)})
             
    # 3. Try pytesseract default (if configured elsewhere/env var)
    try:
        import pytesseract
        # This usually just returns 'tesseract' if not set, but worth a try if they set it in python
        if hasattr(pytesseract.pytesseract, 'tesseract_cmd') and pytesseract.pytesseract.tesseract_cmd != 'tesseract':
             if os.path.exists(pytesseract.pytesseract.tesseract_cmd):
                 return jsonify({'found': True, 'path': pytesseract.pytesseract.tesseract_cmd})
    except:
        pass

    return jsonify({'found': False, 'path': None})


@admin_bp.route('/settings/get-last-prompt')
@login_required
@admin_required
def get_last_prompt():
    """Get the last generated AI prompt for inspection"""
    import os
    from flask import current_app, jsonify
    
    try:
        debug_path = os.path.join(current_app.instance_path, 'last_prompt.txt')
        if os.path.exists(debug_path):
            with open(debug_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return jsonify({'success': True, 'content': content})
        else:
            return jsonify({'success': False, 'error': 'Noch kein Prompt generiert (Analysieren Sie erst ein Dokument).'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})



@admin_bp.route('/settings/betriebe', methods=['GET', 'POST'])
@login_required
@admin_required
def betriebe_settings():
    """Betriebsstätten configuration page"""
    from ..models import AppConfig
    import json
    
    if request.method == 'POST':
        bs_config = request.form.get('bs_form_fields', '').strip()
        
        # Validate JSON
        try:
            json.loads(bs_config)
            AppConfig.set('bs_form_fields', bs_config)
            flash('Konfiguration gespeichert.', 'success')
        except json.JSONDecodeError:
            flash('Ungültiges JSON-Format. Änderungen nicht gespeichert.', 'error')
            
        return redirect(url_for('admin.betriebe_settings'))
    
    # Load config or default
    current_config = AppConfig.get('bs_form_fields')
    
    # Ensure current_config is a list (AppConfig.get might return dict, list, string or None)
    if not current_config:
        current_config = [
            {"key": "name", "label": "Name", "required": True, "field_type": "text", "placeholder": "Firmenname"},
            {"key": "strasse", "label": "Straße & Hausnr.", "required": False, "field_type": "text", "placeholder": "Musterstr. 1"},
            {"key": "plz", "label": "PLZ", "required": False, "field_type": "text", "placeholder": "12345", "width": "w-1/3"},
            {"key": "ort", "label": "Ort", "required": False, "field_type": "text", "placeholder": "Musterstadt", "width": "w-2/3"},
            {"key": "sachbearbeiter", "label": "Ansprechpartner", "required": False, "field_type": "text", "placeholder": "Optional"},
            {"key": "email", "label": "E-Mail", "required": False, "field_type": "email", "placeholder": "info@firma.de"}
        ]
    elif isinstance(current_config, str):
        try:
            current_config = json.loads(current_config)
        except:
            current_config = []
            
    return render_template('admin/betriebe_settings.html', bs_form_fields=current_config)





@admin_bp.route('/reset-system', methods=['POST'])
@login_required
@admin_required
def reset_system():
    """Reset system data - Delete all documents data"""
    from ..models import Document, AuditLog
    
    try:
        # Delete documents
        num_docs = Document.query.delete()
        
        # Delete logs (optional, but requested as "system reset")
        # However, keeping logs for user actions is usually safer. 
        # But if user insists on "System zurücksetzen", we might want clean slate.
        # Let's delete documents only first, or clear everything? 
        # User said "funktion 'system zurücksetzen' entfernt". I presume it clears data.
        num_logs = AuditLog.query.delete()
        
        db.session.commit()
        
        flash(f'System zurückgesetzt: {num_docs} Dokumente und {num_logs} Logs gelöscht.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler beim Zurücksetzen: {str(e)}', 'error')
        
    return redirect(url_for('main.dashboard'))
@admin_bp.route('/categories/<int:category_id>/fields/<int:field_id>/move/<direction>', methods=['POST'])
@login_required
@admin_required
def move_field(category_id, field_id, direction):
    """Move a category field up or down"""
    from ..models import CategoryField
    
    field = CategoryField.query.get_or_404(field_id)
    if field.category_id != category_id:
        abort(404)
    
    # Get all fields for this category sorted by position
    fields = CategoryField.query.filter_by(category_id=category_id).order_by(CategoryField.position).all()
    
    if field not in fields:
        return redirect(url_for('admin.edit_category', category_id=category_id))
    
    idx = fields.index(field)
    
    if direction == 'up' and idx > 0:
        # Swap with previous
        fields[idx], fields[idx-1] = fields[idx-1], fields[idx]
    elif direction == 'down' and idx < len(fields) - 1:
        # Swap with next
        fields[idx], fields[idx+1] = fields[idx+1], fields[idx]
    
    # Update positions for all fields to ensure clean sequence
    for i, f in enumerate(fields):
        f.position = i + 1
    
    db.session.commit()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True})
        
    return redirect(url_for('admin.edit_category', category_id=category_id))
