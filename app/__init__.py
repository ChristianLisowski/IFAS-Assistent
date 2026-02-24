"""
IFAS-Assistent - Flask Application Factory
Creates and configures the Flask application with all extensions and blueprints.
"""
import os
from flask import Flask
from flask_login import LoginManager

from .models import db, User
from .config import config


login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Bitte melden Sie sich an, um auf diese Seite zuzugreifen.'
login_manager.login_message_category = 'warning'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def create_app(config_name=None):
    """Application factory pattern"""
    if config_name is None:
        config_name = os.environ.get('FLASK_CONFIG', 'development')
    
    app = Flask(__name__, 
                template_folder='templates',
                static_folder='static')
    
    # Load configuration
    app.config.from_object(config[config_name])
    
    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config.get('UPLOAD_FOLDER', 'uploads'), exist_ok=True)
    os.makedirs(app.config.get('PROCESSED_FOLDER', 'processed'), exist_ok=True)
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    
    # Register blueprints
    from .auth import auth_bp
    from .main import main_bp
    from .admin import admin_bp
    from .api import api_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(api_bp, url_prefix='/api')
    
    # Create database tables and seed data
    with app.app_context():
        db.create_all()
        _seed_initial_data()
        _update_schema_if_needed()

    # Register custom template filters
    import json
    @app.template_filter('from_json')
    def from_json_filter(value):
        try:
            return json.loads(value) if value else {}
        except:
            return {}
        
        # Reset all sources to auto_analyze=False on startup (Safety/Default)
        try:
            from .models import InputSource
            sources = InputSource.query.all()
            for s in sources:
                if s.auto_analyze:
                    s.auto_analyze = False
            db.session.commit()
        except Exception as e:
            app.logger.error(f"Error resetting auto_analyze: {e}")
            
        # Cleanup stuck documents (e.g. from crash)
        try:
            from .models import Document
            stuck_docs = Document.query.filter_by(status='analyzing').all()
            if stuck_docs:
                app.logger.warning(f"Found {len(stuck_docs)} documents stuck in 'analyzing'. Resetting to 'pending'.")
                for doc in stuck_docs:
                    doc.status = 'pending'
                    doc.analysis_started_at = None
                db.session.commit()
        except Exception as e:
            app.logger.error(f"Error cleaning up stuck documents: {e}")
        
    # Initialize Scheduler
    from .scheduler import init_scheduler
    init_scheduler(app)

    
    @app.context_processor
    def inject_config():
        """Make application configuration available in all templates"""
        from .models import AppConfig
        try:
            config_entries = AppConfig.query.all()
            config_dict = {c.key: c.value for c in config_entries}
            return dict(app_config=config_dict)
        except:
            return dict(app_config={})

    @app.context_processor
    def inject_counts():
        """Inject document counts into all templates"""
        from flask_login import current_user
        from .models import Document
        if current_user.is_authenticated:
            return {
                'pending_count': Document.query.filter_by(status='pending').count(),
                'ready_count': Document.query.filter_by(status='ready').count()
            }
        return {'pending_count': 0, 'ready_count': 0}
    
    return app


def _seed_initial_data():
    """Create initial admin user and default categories if database is empty"""
    from .models import User, Category, CategoryField, InputSource
    
    # Create admin user if not exists
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            email='admin@ifas-assist.local',
            display_name='Administrator',
            role='admin',
            is_active=True
        )
        admin.set_password('admin123')
        db.session.add(admin)
        
        # Create demo user
        user = User(
            username='sachbearbeiter',
            email='user@ifas-assist.local',
            display_name='Max Mustermann',
            role='user',
            is_active=True
        )
        user.set_password('user123')
        db.session.add(user)
        db.session.commit()
        print("[OK] Standard-Benutzer erstellt (admin/admin123, sachbearbeiter/user123)")
    
    # Create default categories if not exist
    if not Category.query.first():
        categories_data = [
            {
                'name': 'mutterschutz',
                'display_name': 'Mutterschutzmeldung',
                'icon': '👶',
                'color': '#8b5cf6',
                'ifas_art': 'Mutterschutz',
                'keywords': 'mutterschutz, schwanger, entbindung, mutter, schwangerschaft, geburt',
                'fields': [
                    {'label': 'Nachname', 'key': 'nachname', 'content_id_ifas': 'musch_nachname', 'required': True},
                    {'label': 'Vorname', 'key': 'vorname', 'content_id_ifas': 'musch_vorname', 'required': True},
                    {'label': 'Geburtsdatum', 'key': 'geburtsdatum', 'content_id_ifas': 'musch_gebdat', 'field_type': 'date', 'required': True},
                    {'label': 'Voraussichtlicher Entbindungstermin', 'key': 'entbindungstermin', 'content_id_ifas': 'musch_entbindung', 'field_type': 'date', 'required': True},
                    {'label': 'Arbeitgeber', 'key': 'arbeitgeber', 'content_id_ifas': 'musch_ag', 'required': True},
                    {'label': 'Wöchentliche Arbeitszeit (Std)', 'key': 'wochentliche_arbeitszeit', 'content_id_ifas': 'musch_zeit', 'field_type': 'number'},
                    {'label': 'Beschäftigungsart', 'key': 'beschaeftigungsart', 'content_id_ifas': 'musch_beschart', 'field_type': 'select', 
                     'options': '["Vollzeit", "Teilzeit", "Geringfügig", "Ausbildung"]'}
                ]
            },
            {
                'name': 'pyroanzeige',
                'display_name': 'Pyroanzeige (Feuerwerk)',
                'icon': '🎆',
                'color': '#f59e0b',
                'ifas_art': 'Sprengstoff',
                'ifas_zusatzart': 'Pyrotechnik',
                'keywords': 'feuerwerk, pyro, sprengstoff, abbrennen, raketen, silvester, neujahr, veranstaltung',
                'fields': [
                    {'label': 'Verantwortlicher', 'key': 'verantwortlich', 'content_id_ifas': 'pyro_verantw', 'required': True},
                    {'label': 'Datum der Veranstaltung', 'key': 'datum', 'content_id_ifas': 'pyro_datum', 'field_type': 'date', 'required': True},
                    {'label': 'Uhrzeit Beginn', 'key': 'uhrzeit', 'content_id_ifas': 'pyro_uhrzeit', 'field_type': 'text'},
                    {'label': 'Abbrennort', 'key': 'ort', 'content_id_ifas': 'pyro_ort', 'required': True},
                    {'label': 'Sicherheitsabstand (m)', 'key': 'sicherheitsabstand', 'content_id_ifas': 'pyro_abstand', 'field_type': 'number'},
                    {'label': 'Art des Feuerwerks', 'key': 'feuerwerk_art', 'content_id_ifas': 'pyro_art', 'field_type': 'select',
                     'options': '["Kleinfeuerwerk (Kat. 1-2)", "Großfeuerwerk (Kat. 3-4)", "Bühnenfeuerwerk"]'}
                ]
            },
            {
                'name': 'unfallanzeige',
                'display_name': 'Unfallanzeige',
                'icon': '🚨',
                'color': '#ef4444',
                'ifas_art': 'Unfall',
                'keywords': 'unfall, arbeitsunfall, verletzung, betriebsunfall, sturz, arbeitsplatz',
                'fields': [
                    {'label': 'Name Verletzte/r', 'key': 'name_verletzt', 'content_id_ifas': 'unf_name', 'required': True},
                    {'label': 'Unfalldatum', 'key': 'unfalldatum', 'content_id_ifas': 'unf_datum', 'field_type': 'date', 'required': True},
                    {'label': 'Unfallort', 'key': 'unfallort', 'content_id_ifas': 'unf_ort', 'required': True},
                    {'label': 'Unfallzeit', 'key': 'unfallzeit', 'content_id_ifas': 'unf_zeit', 'field_type': 'time', 'placeholder': 'hh:mm'},
                    {'label': 'Unfallhergang', 'key': 'hergang', 'content_id_ifas': 'unf_hergang', 'field_type': 'textarea'},
                    {'label': 'Art der Verletzung', 'key': 'verletzung', 'content_id_ifas': 'unf_verletzung'},
                    {'label': 'Arbeitgeber', 'key': 'arbeitgeber', 'content_id_ifas': 'unf_ag', 'required': True}
                ]
            },
            {
                'name': 'bauvoranzeige',
                'display_name': 'Bauvoranzeige',
                'icon': '🏗️',
                'color': '#3b82f6',
                'ifas_art': 'Baustelle',
                'keywords': 'baustelle, bauvorhaben, bauprojekt, rohbau, abriss, tiefbau',
                'fields': [
                    {'label': 'Bauherr', 'key': 'bauherr', 'content_id_ifas': 'bau_bauherr', 'required': True},
                    {'label': 'Bauort/Adresse', 'key': 'bauort', 'content_id_ifas': 'bau_ort', 'required': True},
                    {'label': 'Baubeginn', 'key': 'baubeginn', 'content_id_ifas': 'bau_beginn', 'field_type': 'date', 'required': True},
                    {'label': 'Geplantes Bauende', 'key': 'bauende', 'content_id_ifas': 'bau_ende', 'field_type': 'date'},
                    {'label': 'Art der Baumaßnahme', 'key': 'bauart', 'content_id_ifas': 'bau_art'},
                    {'label': 'SiGeKo vorhanden', 'key': 'sigeko', 'content_id_ifas': 'bau_sigeko', 'field_type': 'select',
                     'options': '["Ja", "Nein", "Nicht erforderlich"]'}
                ]
            }
        ]
        
        for cat_data in categories_data:
            fields_data = cat_data.pop('fields', [])
            category = Category(**cat_data)
            db.session.add(category)
            db.session.flush()  # Get category ID
            
            for idx, field_data in enumerate(fields_data):
                field_data['category_id'] = category.id
                field_data['position'] = idx
                field = CategoryField(**field_data)
                db.session.add(field)
        
        db.session.commit()
        print("[OK] Standard-Kategorien erstellt (Mutterschutz, Pyroanzeige, Unfallanzeige, Bauvoranzeige)")
    
    # Create default input source if not exists
    if not InputSource.query.first():
        local_source = InputSource(
            name='Lokaler Posteingang',
            source_type='folder',
            is_active=True,
            poll_interval=30
        )
        local_source.set_config({
            'path': 'C:/IFAS_Posteingang',
            'watch_subdirs': False,
            'file_patterns': ['*.pdf', '*.PDF', '*.msg', '*.eml']
        })
        db.session.add(local_source)
        db.session.commit()
        print("[OK] Standard-Eingangslayer erstellt (Lokaler Ordner)")


def _update_schema_if_needed():
    """Ensure specific new fields exist in existing database"""
    from .models import Category, CategoryField
    
    # 1. Add 'unfallzeit' to 'unfallanzeige'
    cat = Category.query.filter_by(name='unfallanzeige').first()
    if cat:
        field = CategoryField.query.filter_by(category_id=cat.id, key='unfallzeit').first()
        if not field:
            print("[INFO] Füge fehlendes Feld 'unfallzeit' zu 'unfallanzeige' hinzu...")
            new_field = CategoryField(
                category_id=cat.id,
                label='Unfallzeit',
                key='unfallzeit',
                content_id_ifas='unf_zeit',
                field_type='time',
                placeholder='hh:mm',
                position=3 # After date (pos 0, 1)
            )
            db.session.add(new_field)
            db.session.commit()
