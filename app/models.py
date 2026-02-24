"""
IFAS-Assistent Database Models
Defines all database tables for users, categories, documents, and input sources.
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import json

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """User model with role-based access control"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='user')  # 'admin' or 'user'
    display_name = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    notification_preferences = db.Column(db.Text, default='{}')  # JSON: {'error': bool, 'pending_overflow': bool}
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    @property
    def is_admin(self):
        return self.role == 'admin'
    
    def __repr__(self):
        return f'<User {self.username}>'


class Category(db.Model):
    """Document categories (e.g., Mutterschutz, Pyroanzeige)"""
    __tablename__ = 'categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    display_name = db.Column(db.String(150))
    icon = db.Column(db.String(10), default='📄')  # Emoji icon
    color = db.Column(db.String(20), default='#6366f1')
    ifas_art = db.Column(db.String(100))  # IFAS Vorgangsart
    ifas_zusatzart = db.Column(db.String(100))  # IFAS Zusatzart
    keywords = db.Column(db.Text)  # Comma-separated keywords for AI matching
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    position = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship to fields
    fields = db.relationship('CategoryField', backref='category', lazy='dynamic', 
                            order_by='CategoryField.position', cascade='all, delete-orphan')
    
    def get_keywords_list(self):
        if not self.keywords:
            return []
        return [k.strip().lower() for k in self.keywords.split(',') if k.strip()]
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'display_name': self.display_name or self.name,
            'icon': self.icon,
            'color': self.color,
            'ifas_art': self.ifas_art,
            'ifas_zusatzart': self.ifas_zusatzart,
            'keywords': self.keywords,
            'fields': [f.to_dict() for f in self.fields]
        }
    
    def __repr__(self):
        return f'<Category {self.name}>'


class CategoryField(db.Model):
    """Form fields for each category"""
    __tablename__ = 'category_fields'
    
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    label = db.Column(db.String(100), nullable=False)  # Display label
    key = db.Column(db.String(50), nullable=False)  # Internal key for data mapping
    content_id_ifas = db.Column(db.String(100))  # IFAS API Content-ID for Sonderaktion
    field_type = db.Column(db.String(20), default='text')  # text, number, date, select, textarea
    options = db.Column(db.Text)  # JSON array for select options
    placeholder = db.Column(db.String(200))
    required = db.Column(db.Boolean, default=False)
    show_in_validation = db.Column(db.Boolean, default=True)  # Show in side-to-side view
    auto_fill = db.Column(db.Boolean, default=True)  # Let AI auto-fill this field
    position = db.Column(db.Integer, default=0)
    
    def get_options_list(self):
        if not self.options:
            return []
        try:
            return json.loads(self.options)
        except:
            return []
    
    def to_dict(self):
        return {
            'id': self.id,
            'label': self.label,
            'key': self.key,
            'content_id_ifas': self.content_id_ifas,
            'field_type': self.field_type,
            'options': self.get_options_list(),
            'placeholder': self.placeholder,
            'required': self.required,
            'show_in_validation': self.show_in_validation,
            'auto_fill': self.auto_fill,
            'position': self.position
        }
    
    def __repr__(self):
        return f'<CategoryField {self.label}>'


class InputSource(db.Model):
    """Configuration for document input sources (Email, Folder, API)"""
    __tablename__ = 'input_sources'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    source_type = db.Column(db.String(20), nullable=False)  # 'imap', 'folder', 'network', 'ifas_api'
    config_json = db.Column(db.Text)  # JSON configuration specific to source type
    is_active = db.Column(db.Boolean, default=True)
    auto_analyze = db.Column(db.Boolean, default=False)  # Automatically start analysis on ingestion
    poll_interval = db.Column(db.Integer, default=60)  # Seconds between polls
    trash_folder = db.Column(db.String(100), default='Trash')  # Target folder for deleted emails
    processed_folder = db.Column(db.String(100), default='Processed')  # Target folder for processed emails (after IFAS transfer)
    discarded_folder = db.Column(db.String(100))  # Target folder for discarded emails (optional, default: keep in Inbox)
    last_poll = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    documents = db.relationship('Document', backref='source', lazy='dynamic')
    
    def get_config(self):
        if not self.config_json:
            return {}
        try:
            return json.loads(self.config_json)
        except:
            return {}
    
    def set_config(self, config_dict):
        self.config_json = json.dumps(config_dict)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'source_type': self.source_type,
            'config': self.get_config(),
            'is_active': self.is_active,
            'auto_analyze': self.auto_analyze if self.auto_analyze is not None else False,
            'poll_interval': self.poll_interval,
            'last_poll': self.last_poll.isoformat() if self.last_poll else None
        }
    
    def __repr__(self):
        return f'<InputSource {self.name} ({self.source_type})>'


class Document(db.Model):
    """Incoming documents to be processed"""
    __tablename__ = 'documents'
    
    id = db.Column(db.Integer, primary_key=True)
    external_id = db.Column(db.String(100), unique=True)  # UUID or external reference
    filename = db.Column(db.String(255), nullable=False)
    original_path = db.Column(db.String(500))
    stored_path = db.Column(db.String(500))  # Path to stored file
    mime_type = db.Column(db.String(100))
    file_size = db.Column(db.Integer)
    
    # Source information
    source_id = db.Column(db.Integer, db.ForeignKey('input_sources.id'))
    received_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Processing status
    status = db.Column(db.String(20), default='pending')  # pending, analyzing, ready, transferred, rejected
    
    # Email-specific fields
    email_subject = db.Column(db.String(500))
    email_from = db.Column(db.String(255))
    email_date = db.Column(db.DateTime)
    
    # Extracted content
    raw_text = db.Column(db.Text)
    page_count = db.Column(db.Integer)
    
    # AI analysis results
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    category = db.relationship('Category', backref='documents')
    ai_confidence = db.Column(db.Float)  # 0.0 - 1.0
    extracted_data_json = db.Column(db.Text)  # JSON of extracted field values
    
    # Correction tracking for accuracy analytics
    manual_corrections = db.Column(db.Integer, default=0)  # Number of fields manually corrected
    ai_category_changed = db.Column(db.Boolean, default=False)  # Whether user changed AI category
    analysis_started_at = db.Column(db.DateTime)  # When AI analysis started
    analyzed_at = db.Column(db.DateTime)  # When AI analysis completed
    total_fields_detected = db.Column(db.Integer, default=0)  # Total fields detected by AI (denominator for accuracy)
    
    # Default Columns
    content_hash = db.Column(db.String(64), index=True)
    imap_uid = db.Column(db.Integer)  # IMAP UID for emails
    ifas_aktenzeichen = db.Column(db.String(100))
    ifas_bs_nr = db.Column(db.String(50))  # Betriebsstättennummer
    transferred_at = db.Column(db.DateTime)
    transferred_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    transferred_by = db.relationship('User', backref='transferred_documents')
    
    # Relationships
    attachments = db.relationship('Attachment', backref='document', lazy='dynamic', cascade='all, delete-orphan')
    
    def get_extracted_data(self):
        if not self.extracted_data_json:
            return {}
        try:
            return json.loads(self.extracted_data_json)
        except:
            return {}
    
    def set_extracted_data(self, data_dict):
        self.extracted_data_json = json.dumps(data_dict)
    
    def to_dict(self, include_text=False):
        result = {
            'id': self.id,
            'external_id': self.external_id,
            'filename': self.filename,
            'mime_type': self.mime_type,
            'file_size': self.file_size,
            'source_id': self.source_id,
            'source_name': self.source.name if self.source else None,
            'received_at': self.received_at.isoformat() if self.received_at else None,
            'status': self.status,
            'email_subject': self.email_subject,
            'email_from': self.email_from,
            'category_id': self.category_id,
            'category_name': self.category.name if self.category else None,
            'ai_confidence': self.ai_confidence,
            'extracted_data': self.get_extracted_data(),
            'page_count': self.page_count,
            'ifas_aktenzeichen': self.ifas_aktenzeichen,
            'attachment_count': self.attachments.count()
        }
        if include_text:
            result['raw_text'] = self.raw_text
            result['attachments'] = [a.to_dict() for a in self.attachments]
        return result
    
    def __repr__(self):
        return f'<Document {self.filename}>'


class Attachment(db.Model):
    """Attachments belonging to a document (e.g., email attachments)"""
    __tablename__ = 'attachments'
    
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('documents.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.String(500))
    mime_type = db.Column(db.String(100))
    file_size = db.Column(db.Integer)
    extracted_text = db.Column(db.Text)  # Text extracted from attachment
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'mime_type': self.mime_type,
            'file_size': self.file_size,
            'has_text': bool(self.extracted_text)
        }
    
    def __repr__(self):
        return f'<Attachment {self.filename}>'


class AuditLog(db.Model):
    """Audit trail for important actions"""
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    user = db.relationship('User', backref='audit_logs')
    action = db.Column(db.String(50), nullable=False)  # login, transfer, reject, config_change
    entity_type = db.Column(db.String(50))  # document, category, user, etc.
    entity_id = db.Column(db.Integer)
    details_json = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<AuditLog {self.action} by {self.user_id}>'


class AppConfig(db.Model):
    """Application-wide configuration key-value store"""
    __tablename__ = 'app_config'
    
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @staticmethod
    def get(key, default=None):
        config = AppConfig.query.get(key)
        if config:
            try:
                return json.loads(config.value)
            except:
                return config.value
        return default
    
    @staticmethod
    def set(key, value):
        config = AppConfig.query.get(key)
        if config:
            config.value = json.dumps(value) if not isinstance(value, str) else value
        else:
            config = AppConfig(key=key, value=json.dumps(value) if not isinstance(value, str) else value)
            db.session.add(config)
        db.session.commit()
