# IFAS-Assistent Configuration
import os
from datetime import timedelta

class Config:
    """Base configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'ifas-assistant-secret-key-2026'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_TYPE = 'filesystem'
    
    # LMStudio API
    LMSTUDIO_URL = os.environ.get('LMSTUDIO_URL') or 'http://localhost:1234/v1'
    LMSTUDIO_MODEL = os.environ.get('LMSTUDIO_MODEL') or 'local-model'
    
    # IFAS API (Mock by default)
    IFAS_API_URL = os.environ.get('IFAS_API_URL') or 'http://localhost:5051/api/ifas'
    IFAS_API_KEY = os.environ.get('IFAS_API_KEY') or 'mock-api-key'
    IFAS_API_MOCK = os.environ.get('IFAS_API_MOCK', 'true').lower() == 'true'
    
    # File storage
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
    PROCESSED_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'processed')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB max upload
    
    # Watched folder for local input
    WATCH_FOLDER = os.environ.get('WATCH_FOLDER') or 'C:/IFAS_Posteingang'
    
    # IMAP defaults (to be configured in admin)
    IMAP_DEFAULT_PORT = 993
    IMAP_DEFAULT_SSL = True


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance', 'ifas_assistent.db')


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance', 'ifas_assistent.db')


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
