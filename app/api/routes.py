"""
API Blueprint Routes
RESTful API endpoints for documents, analysis, and IFAS integration
"""
from flask import Blueprint, jsonify, request, send_file, abort
from flask_login import login_required, current_user
from datetime import datetime
import json

from ..models import db, Document, Category, CategoryField, InputSource, Attachment, AuditLog

api_bp = Blueprint('api', __name__)


# ============================================================================
# DOCUMENT ENDPOINTS
# ============================================================================
@api_bp.route('/documents', methods=['GET'])
@login_required
def get_documents():
    """Get list of documents with optional filters"""
    status = request.args.get('status')
    source_id = request.args.get('source_id', type=int)
    category_id = request.args.get('category_id', type=int)
    limit = request.args.get('limit', 50, type=int)
    
    query = Document.query
    
    if status:
        query = query.filter_by(status=status)
    if source_id:
        query = query.filter_by(source_id=source_id)
    if category_id:
        query = query.filter_by(category_id=category_id)
    
    documents = query.order_by(Document.received_at.desc()).limit(limit).all()
    
    return jsonify([doc.to_dict() for doc in documents])


@api_bp.route('/documents/<int:doc_id>', methods=['GET'])
@login_required
def get_document(doc_id):
    """Get single document with full details"""
    document = Document.query.get_or_404(doc_id)
    return jsonify(document.to_dict(include_text=True))


@api_bp.route('/documents/<int:doc_id>/file', methods=['GET'])
@login_required
def get_document_file(doc_id):
    """Serve the original document file"""
    import os
    document = Document.query.get_or_404(doc_id)
    
    if not document.stored_path or not os.path.exists(document.stored_path):
        abort(404)
        
    return send_file(document.stored_path)


@api_bp.route('/attachments/<int:att_id>/file', methods=['GET'])
@login_required
def get_attachment_file(att_id):
    """Serve the attachment file"""
    import os
    attachment = Attachment.query.get_or_404(att_id)
    
    # Check if file exists in stored_path
    if attachment.stored_path and os.path.exists(attachment.stored_path):
        return send_file(attachment.stored_path)
    
    # Fallback to uploads folder construction if path not absolute/valid (legacy support)
    upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    # Try full path if stored_path is relative
    potential_path = os.path.join(upload_folder, os.path.basename(attachment.stored_path)) if attachment.stored_path else None
    
    if potential_path and os.path.exists(potential_path):
        return send_file(potential_path)
        
    abort(404)


@api_bp.route('/documents/reset', methods=['POST'])
@login_required
def reset_system():
    """
    RESET SYSTEM: Delete all documents and re-scan input sources
    """
    try:
        # 1. Delete all documents (cascades to attachments)
        num_deleted = Document.query.delete()
        db.session.commit()
        
        # 2. Trigger re-scan
        total_new = 0
        from ..services.folder_monitor import FolderMonitor
        
        sources = InputSource.query.filter_by(is_active=True).all()
        for source in sources:
            if source.source_type in ('folder', 'network'):
                monitor = FolderMonitor(source)
                total_new += monitor.poll()
                
        return jsonify({
            'success': True,
            'message': f'System zurückgesetzt. {num_deleted} Dokumente gelöscht, {total_new} neu importiert.',
            'deleted': num_deleted,
            'imported': total_new
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/documents/<int:doc_id>/analyze', methods=['POST'])
@login_required
def analyze_document(doc_id):
    """Trigger AI analysis of document"""
    document = Document.query.get_or_404(doc_id)
    
    # Import LMStudio service
    from ..services.lmstudio_service import LMStudioService
    from ..services.pdf_extractor import PDFExtractor
    import os
    
    # FORCE RE-EXTRACTION of text to apply latest improvements (e.g. headers)
    try:
        pdf_path = document.stored_path or document.original_path
        if pdf_path and os.path.exists(pdf_path) and document.filename.lower().endswith('.pdf'):
            # Get OCR Config
            from ..models import AppConfig
            ocr_strategy = AppConfig.get('ocr_strategy', 'standard')
            tesseract_cmd = AppConfig.get('tesseract_cmd', '')
            
            extractor = PDFExtractor()
            # Pass strategy and tesseract path
            extraction_result = extractor.extract(
                pdf_path, 
                strategy=ocr_strategy, 
                tesseract_cmd=tesseract_cmd
            )
            
            if extraction_result.get('text'):
                document.raw_text = extraction_result['text']
                db.session.commit()
    except Exception as extract_err:
        print(f"Error re-extracting text: {extract_err}")

    try:
        lm_service = LMStudioService()
        
        # Get available categories (exclude SYSTEM types)
        categories = Category.query.filter(Category.is_active == True, Category.ifas_art != 'SYSTEM').all()
        
        # Collect attachment texts
        attachment_texts = []
        for att in document.attachments:
            if att.extracted_text:
                attachment_texts.append(f"Anhang '{att.filename}':\n{att.extracted_text}")
        
        # Prepare Images for Vision/OCR (if PDF)
        images = []
        pdf_path = document.stored_path or document.original_path
        if pdf_path and os.path.exists(pdf_path) and document.filename.lower().endswith('.pdf'):
             try:
                # Need to instantiate extractor again or reuse logic
                from ..services.pdf_extractor import PDFExtractor
                extractor = PDFExtractor()
                img_b64 = extractor.get_first_page_image(pdf_path)
                if img_b64:
                    images.append(img_b64)
                    print(f"DEBUG: Added page image for Vision analysis ({len(img_b64)} chars)")
             except Exception as img_err:
                 print(f"Error extracting page image: {img_err}")

        # Track start time for stats
        document.analysis_started_at = datetime.utcnow()
        document.status = 'analyzing'
        db.session.commit()

        # Analyze with AI
        result = lm_service.analyze_document(
            text=document.raw_text or '',
            attachments=attachment_texts,
            categories=[c.to_dict() for c in categories],
            images=images 
        )
        
        # Update document with results
        if result.get('category_id'):
            document.category_id = result['category_id']
        
        if result.get('extracted_data'):
            document.set_extracted_data(result['extracted_data'])
        
        if result.get('confidence'):
            document.ai_confidence = result['confidence']
        
        document.status = 'ready'
        document.analyzed_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'category_id': document.category_id,
            'category_name': document.category.name if document.category else None,
            'extracted_data': document.get_extracted_data(),
            'confidence': document.ai_confidence
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@api_bp.route('/lmstudio/status', methods=['GET'])
@login_required
def lmstudio_status():
    """Check LMStudio connection status"""
    from ..services.lmstudio_service import LMStudioService
    try:
        lm_service = LMStudioService()
        result = lm_service.check_connection()
        return jsonify({
            'connected': result.get('connected', False),
            'model': result.get('models', [None])[0] if result.get('models') else None,
            'url': result.get('url', ''),
            'error': result.get('error')
        })
    except Exception as e:
        return jsonify({'connected': False, 'error': str(e)})


@api_bp.route('/documents/analyze-all', methods=['POST'])
@login_required
def analyze_all_documents():
    """Trigger background analysis for all pending documents"""
    from ..scheduler import scheduler, analyze_pending_documents
    import time
    from datetime import datetime, timedelta
    import os
    import json   
    # Check if scheduler is running
    if not scheduler.running:
         return jsonify({'success': False, 'error': 'Background scheduler is not running'}), 503

    # Add job to scheduler
    job_id = f'manual_analyze_all_{int(time.time())}'
    scheduler.add_job(
        id=job_id,
        func=analyze_pending_documents,
        trigger='date',
        run_date=datetime.now() + timedelta(seconds=1),
        replace_existing=False
    )
    
    return jsonify({
        'success': True,
        'message': 'Hintergrund-Analyse gestartet',
        'job_id': job_id
    })

@api_bp.route('/documents/<int:doc_id>/update', methods=['POST'])
@login_required
def update_document(doc_id):
    """Update document data (from validation form)"""
    document = Document.query.get_or_404(doc_id)
    data = request.get_json()
    
    # Track manual corrections for accuracy analytics
    corrections = 0
    
    if 'category_id' in data:
        new_cat = data['category_id']
        if document.category_id and new_cat != document.category_id:
            document.ai_category_changed = True
            corrections += 1
        document.category_id = new_cat
    
    if 'extracted_data' in data:
        old_data = document.get_extracted_data()
        new_data = data['extracted_data']
        # Count fields that differ from AI extraction
        if old_data:
            for key, new_val in new_data.items():
                old_val = old_data.get(key, '')
                if str(new_val).strip() != str(old_val).strip():
                    corrections += 1
        document.set_extracted_data(new_data)
    
    if corrections > 0:
        document.manual_corrections = (document.manual_corrections or 0) + corrections
    
    if 'ifas_bs_nr' in data:
        document.ifas_bs_nr = data['ifas_bs_nr']
    
    if 'status' in data:
        document.status = data['status']
        
    db.session.commit()
    return jsonify({'success': True})





@api_bp.route('/documents/<int:doc_id>/transfer', methods=['POST'])
@login_required
def transfer_document(doc_id):
    """Transfer document to IFAS"""
    document = Document.query.get_or_404(doc_id)
    data = request.get_json() or {}
    
    # Import IFAS client
    from ..services.ifas_api_client import IfasApiClient
    from flask import current_app
    
    try:
        ifas_client = IfasApiClient()
        
        # Get category and fields
        category = document.category
        if not category:
            return jsonify({'success': False, 'error': 'Keine Kategorie zugewiesen'}), 400
        
        extracted_data = document.get_extracted_data()
        
        # Prepare IFAS data
        anzeige_data = {
            'art': category.ifas_art,
            'zusatzart': category.ifas_zusatzart,
            'bs_nr': document.ifas_bs_nr or data.get('bs_nr'),
            'fields': {}
        }
        
        # Map fields using content_id_ifas
        for field in category.fields:
            if field.content_id_ifas and field.key in extracted_data:
                anzeige_data['fields'][field.content_id_ifas] = extracted_data[field.key]
        
        # Create Anzeige in IFAS
        result = ifas_client.create_anzeige(anzeige_data)
        
        if result.get('success'):
            # Attach the document file
            if document.stored_path:
                res_attach = ifas_client.attach_document(
                    result.get('aktenzeichen'), 
                    document.stored_path, 
                    document.filename
                )
                if not res_attach.get('success'):
                    current_app.logger.warning(f"Failed to attach document to IFAS: {res_attach.get('error')}")

            # Update document status
            document.status = 'transferred'
            document.ifas_aktenzeichen = result.get('aktenzeichen')
            document.transferred_at = datetime.utcnow()
            document.transferred_by_id = current_user.id
            
            # Post-processing for emails: Move to 'Processed' folder
            if document.source and document.source.source_type == 'imap' and document.imap_uid:
                processed_folder = document.source.processed_folder or 'Processed'
                try:
                    from ..services.email_connector import EmailConnector
                    connector = EmailConnector(document.source)
                    if connector.move_to_folder(document, processed_folder):
                        current_app.logger.info(f"Moved email {document.imap_uid} to {processed_folder}")
                    else:
                        current_app.logger.warning(f"Failed to move email {document.imap_uid} to {processed_folder}")
                except Exception as e:
                    current_app.logger.error(f"Error moving email during transfer: {e}")
            elif document.source and document.source.source_type in ('folder', 'network'):
                # Handle local files
                try:
                    from ..services.folder_monitor import FolderMonitor
                    monitor = FolderMonitor(document.source)
                    res = monitor.move_to_processed(document)
                    if res['success']:
                        current_app.logger.info(f"Moved file to processed: {res['message']}")
                        if 'new_path' in res:
                            document.original_path = res['new_path']
                    else:
                         current_app.logger.warning(f"Failed to move file to processed: {res['message']}")
                except Exception as e:
                    current_app.logger.error(f"Error moving file during transfer: {e}")
            
            
            # Audit log
            log = AuditLog(
                user_id=current_user.id,
                action='transfer',
                entity_type='document',
                entity_id=document.id,
                details_json=json.dumps({
                    'aktenzeichen': result.get('aktenzeichen'),
                    'category': category.name
                }),
                ip_address=request.remote_addr
            )
            db.session.add(log)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'aktenzeichen': result.get('aktenzeichen'),
                'message': 'Vorgang erfolgreich nach IFAS übertragen'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unbekannter Fehler bei IFAS-Übertragung')
            }), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/documents/<int:doc_id>/reject', methods=['POST'])
@login_required
def reject_document(doc_id):
    """Reject/discard a document"""
    document = Document.query.get_or_404(doc_id)
    data = request.get_json() or {}
    
    if 'mode' in data and data['mode'] == 'delete':
        # Peristent deletion logic
        if document.source and document.source.source_type in ('folder', 'network'):
            from ..services.folder_monitor import FolderMonitor
            monitor = FolderMonitor(document.source)
            res = monitor.delete_original(document)
            
            # Note: We proceed even if file deletion fails (maybe already gone), 
            # but we log the error.
            if not res['success']:
                current_app.logger.warning(f"File deletion failed: {res['message']}")
            
            # Additional log detail
            log_action = 'delete'
            message = 'Dokument und Originaldatei gelöscht'
        elif document.source and document.source.source_type == 'imap':
            from ..services.email_connector import EmailConnector
            connector = EmailConnector(document.source)
            if connector.move_to_trash(document):
                message = 'E-Mail in Papierkorb verschoben und Dokument gelöscht'
            else:
                message = 'Dokument gelöscht (Verschieben in Papierkorb fehlgeschlagen)'
            
            log_action = 'delete'
        else:
            # For network/manual: Just delete from DB
            log_action = 'delete' 
            message = 'Dokument aus Datenbank gelöscht'

        # HARD DELETE from DB
        # remove attachments first? Cascade should handle it if configured, 
        # but let's be safe if no cascade.
        # Check model: cascade='all, delete-orphan' is usually on relationships.
        # Assuming relationship is set up correctly.
        
        # Log before deleting
        log = AuditLog(
            user_id=current_user.id,
            action=log_action,
            entity_type='document',
            entity_id=document.id, # ID might be kept in log even if doc deleted? No, foreign key...
            # If AuditLog has foreign key to document, we can't delete document!
            # AuditLog definition: entity_id = db.Column(db.Integer) (No FK usually for this pattern)
            # Checked models.py earlier: entity_id is just Integer. Good.
            details_json=json.dumps({'mode': 'delete', 'filename': document.filename}),
            ip_address=request.remote_addr
        )
        db.session.add(log)
        
        db.session.delete(document)
        db.session.commit()
        return jsonify({'success': True, 'message': message})

    else:
        # DISCARD: Move to _rejected folder
        # DISCARD: Move to _rejected folder (or configured discarded folder)
        if document.source and document.source.source_type in ('folder', 'network'):
            from ..services.folder_monitor import FolderMonitor
            monitor = FolderMonitor(document.source)
            # Now uses configured folder internally
            res = monitor.move_to_discarded(document) 
            if res['success']:
                message = f'Dokument verworfen: {res["message"]}'
                # CRITICAL: Update path so future delete works!
                if 'new_path' in res:
                    document.original_path = res['new_path']
            else:
                message = f'Dokument verworfen (Verschieben fehlgeschlagen: {res["message"]})'
        
        elif document.source and document.source.source_type == 'imap' and document.imap_uid:
            # Handle IMAP Discard
            discarded_folder = document.source.discarded_folder
            if discarded_folder:
                # Move to configured folder
                try:
                    from ..services.email_connector import EmailConnector
                    connector = EmailConnector(document.source)
                    if connector.move_to_folder(document, discarded_folder):
                        message = f'Dokument verworfen und E-Mail nach "{discarded_folder}" verschoben'
                    else:
                        message = f'Dokument verworfen (Verschieben nach "{discarded_folder}" fehlgeschlagen)'
                except Exception as e:
                    current_app.logger.error(f"Error moving discarded email: {e}")
                    message = 'Dokument verworfen (Fehler beim Verschieben der E-Mail)'
            else:
                # Default: Do nothing (keep in Inbox)
                message = 'Dokument verworfen (E-Mail verbleibt im Posteingang)'
        
        else:
            message = 'Dokument verworfen'
            
        log_action = 'reject'
        document.status = 'rejected'
        
        # Audit log
        log = AuditLog(
            user_id=current_user.id,
            action=log_action,
            entity_type='document',
            entity_id=document.id,
            details_json=json.dumps({'mode': data.get('mode', 'discard')}),
            ip_address=request.remote_addr
        )
        db.session.add(log)
        db.session.commit()
        
        return jsonify({'success': True, 'message': message})
    
    # Audit log
    log = AuditLog(
        user_id=current_user.id,
        action=log_action,
        entity_type='document',
        entity_id=document.id,
        details_json=json.dumps({'mode': data.get('mode', 'discard')}),
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    return jsonify({'success': True, 'message': message})


@api_bp.route('/documents/<int:doc_id>', methods=['DELETE'])
@login_required
def delete_document(doc_id):
    """Permanently delete a document and its files"""
    import os
    document = Document.query.get_or_404(doc_id)
    
    try:
        # Delete physical files
        files_to_delete = []
        if document.stored_path:
            files_to_delete.append(document.stored_path)
        
        # Delete attachments
        for att in document.attachments:
            if att.stored_path:
                files_to_delete.append(att.stored_path)
        
        # Also clean up original path if it's in our upload folder (basic check)
        # Avoid deleting from user's source folders unless configured (too risky for now)
        
        for file_path in files_to_delete:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Error deleting file {file_path}: {e}")
        
        # Audit log before deletion
        log = AuditLog(
            user_id=current_user.id,
            action='delete',
            entity_type='document',
            entity_id=document.id,
            details_json=json.dumps({'filename': document.filename}),
            ip_address=request.remote_addr
        )
        db.session.add(log)
        
        # Delete from DB
        db.session.delete(document)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Dokument wurde gelöscht'})
        
    except Exception as e:
        import traceback
        with open('server_error.log', 'a') as f:
            f.write(f"[{datetime.now()}] Error deleting document {doc_id}:\n")
            f.write(traceback.format_exc())
            f.write("\n" + "="*50 + "\n")
        print(f"ERROR: {str(e)}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@api_bp.route('/logs', methods=['POST'])
@login_required 
def log_client_error():
    """Receive client-side logs/errors"""
    import json
    from datetime import datetime
    try:
        data = request.get_json() or {}
        level = data.get('level', 'info').upper()
        message = data.get('message', 'No message')
        context = data.get('context', {})
        
        # Format log entry
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] CLIENT_LOG [{level}] {message} | Context: {json.dumps(context)}\n"
        
        # Write to file
        with open('client_debug.log', 'a', encoding='utf-8') as f:
            f.write(log_entry)
            
        # Print to console
        print(log_entry.strip())
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# CATEGORY ENDPOINTS
# ============================================================================
@api_bp.route('/categories', methods=['GET'])
@login_required
def get_categories():
    """Get all active categories"""
    categories = Category.query.filter_by(is_active=True).order_by(Category.position).all()
    return jsonify([c.to_dict() for c in categories])


@api_bp.route('/categories/<int:cat_id>/fields', methods=['GET'])
@login_required
def get_category_fields(cat_id):
    """Get fields for a specific category"""
    category = Category.query.get_or_404(cat_id)
    fields = [f.to_dict() for f in category.fields if f.show_in_validation]
    return jsonify(fields)


# ============================================================================
# BETRIEBSSTÄTTEN SEARCH
# ============================================================================
@api_bp.route('/betriebe/search', methods=['GET'])
@login_required
def search_betriebe():
    """Search for Betriebsstätten (mock or via IFAS API)"""
    query = request.args.get('q', '').strip()
    
    if len(query) < 2:
        return jsonify([])
    
    from flask import current_app
    from ..services.ifas_api_client import IfasApiClient
    
    try:
        ifas_client = IfasApiClient()
        results = ifas_client.search_betriebsstaette(query)
        return jsonify(results)
    except Exception as e:
        # Return mock data on error
        mock_results = [
            {'bs_nr': 'BS-1001', 'name': f'Musterfirma für "{query}"', 'ort': 'Kiel', 'plz': '24103', 'strasse': 'Hafenstr. 1'},
            {'bs_nr': 'BS-1002', 'name': f'{query} GmbH', 'ort': 'Lübeck', 'plz': '23552', 'strasse': 'Hauptstr. 5'},
        ]
        return jsonify(mock_results)


@api_bp.route('/betriebe', methods=['POST'])
@login_required
def create_betrieb():
    """Create a new Betriebsstätte"""
    data = request.get_json()
    
    from ..services.ifas_api_client import IfasApiClient
    
    try:
        client = IfasApiClient()
        # You might want to validate 'data' against the 'Betriebsstätte' category fields here
        # But for now we pass it through to the client
        
        result = client.create_betriebsstaette(data)
        
        if result.get('success'):
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/betriebe/form-config', methods=['GET'])
@login_required
def get_bs_form_config():
    """Get configuration for Betriebsstätte creation form"""
    from ..models import AppConfig
    import json
    
    # Default configuration
    default_fields = [
        {"key": "name", "label": "Name", "required": True, "field_type": "text", "placeholder": "Firmenname"},
        {"key": "strasse", "label": "Straße & Hausnr.", "required": False, "field_type": "text", "placeholder": "Musterstr. 1"},
        {"key": "plz", "label": "PLZ", "required": False, "field_type": "text", "placeholder": "12345", "width": "w-1/3"},
        {"key": "ort", "label": "Ort", "required": False, "field_type": "text", "placeholder": "Musterstadt", "width": "w-2/3"},
        {"key": "sachbearbeiter", "label": "Ansprechpartner", "required": False, "field_type": "text", "placeholder": "Optional"},
        {"key": "email", "label": "E-Mail", "required": False, "field_type": "email", "placeholder": "info@firma.de"}
    ]
    
    try:
        # Try to load from AppConfig
        config_json = AppConfig.get('bs_form_fields')
        if config_json:
            fields = json.loads(config_json)
            return jsonify(fields)
    except Exception as e:
        print(f"Error loading BS config: {e}")
        
    return jsonify(default_fields)


# ============================================================================
# INPUT SOURCES
# ============================================================================
@api_bp.route('/sources', methods=['GET'])
@login_required
def get_sources():
    """Get all input sources"""
    sources = InputSource.query.all()
    return jsonify([s.to_dict() for s in sources])


@api_bp.route('/sources/<int:source_id>/toggle', methods=['PATCH'])
@login_required
def toggle_source(source_id):
    """Toggle is_active on an input source"""
    source = InputSource.query.get_or_404(source_id)
    source.is_active = not source.is_active
    db.session.commit()
    return jsonify({
        'success': True,
        'is_active': source.is_active,
        'message': f"Eingangslayer '{source.name}' {'aktiviert' if source.is_active else 'deaktiviert'}"
    })


@api_bp.route('/sources/<int:source_id>/check', methods=['GET'])
@login_required
def check_source(source_id):
    """Check if a source's configured path/server is reachable"""
    import os
    source = InputSource.query.get_or_404(source_id)
    config = source.get_config()
    
    if source.source_type in ('folder', 'network'):
        path = config.get('path', '')
        if not path:
            return jsonify({'reachable': False, 'error': 'Kein Pfad konfiguriert'})
        if os.path.exists(path):
            try:
                files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
                return jsonify({'reachable': True, 'files': len(files), 'path': path})
            except PermissionError:
                return jsonify({'reachable': False, 'error': f'Zugriff verweigert: {path}'})
            except Exception as e:
                return jsonify({'reachable': False, 'error': str(e)})
        else:
            return jsonify({'reachable': False, 'error': f'Pfad nicht erreichbar: {path}'})
    elif source.source_type == 'imap':
        try:
            from ..services.email_connector import EmailConnector
            connector = EmailConnector(source)
            # Use test_connection to get detailed error message
            result = connector.test_connection()
            
            if result.get('success'):
                # Count messages in Inbox
                stats = connector.get_stats()
                return jsonify({
                    'reachable': True, 
                    'host': config.get('host', ''),
                    'files': stats.get('total', 0) if stats else '?',
                    'info': result.get('message', f"Verbunden mit {config.get('host')}")
                })
            else:
                 return jsonify({
                     'reachable': False, 
                     'error': result.get('message', 'Verbindung fehlgeschlagen')
                 })
        except Exception as e:
            return jsonify({'reachable': False, 'error': str(e)})
    
    return jsonify({'reachable': True, 'info': 'Prüfung nicht verfügbar'})

    return jsonify({'reachable': True, 'info': 'Prüfung nicht verfügbar'})


@api_bp.route('/sources/<int:source_id>', methods=['DELETE'])
@login_required
def delete_source(source_id):
    """Delete an input source"""
    source = InputSource.query.get_or_404(source_id)
    
    try:
        db.session.delete(source)
        db.session.commit()
        return jsonify({'success': True, 'message': f"Eingangslayer '{source.name}' gelöscht"})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/sources/<int:source_id>/poll', methods=['POST'])
@login_required
def poll_source(source_id):
    """Manually trigger polling of an input source"""
    source = InputSource.query.get_or_404(source_id)
    
    from ..services.folder_monitor import FolderMonitor
    from ..services.email_connector import EmailConnector
    
    try:
        new_docs = 0
        
        if source.source_type in ('folder', 'network'):
            monitor = FolderMonitor(source)
            new_docs = monitor.poll()
        elif source.source_type == 'imap':
            connector = EmailConnector(source)
            new_docs = connector.poll()
        
        source.last_poll = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'new_documents': new_docs,
            'message': f'{new_docs} neue Dokumente importiert'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# LLM STATUS
# ============================================================================
@api_bp.route('/llm/status', methods=['GET'])
@login_required
def llm_status():
    """Check LMStudio connection status"""
    from ..services.lmstudio_service import LMStudioService
    try:
        service = LMStudioService()
        status = service.check_connection()
        return jsonify(status)
    except Exception as e:
        return jsonify({
            'connected': False,
            'error': str(e)
        })


@api_bp.route('/llm/load', methods=['POST'])
@login_required
def load_llm_model():
    """Force load a specific LMStudio model"""
    from ..services.lmstudio_service import LMStudioService
    
    data = request.get_json()
    model_id = data.get('model')
    
    if not model_id:
        return jsonify({'success': False, 'error': 'Kein Modell angegeben'}), 400
        
    try:
        service = LMStudioService()
        result = service.load_model(model_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# FOLDER BROWSER ENDPOINTS
# ============================================================================
@api_bp.route('/folders/browse', methods=['GET'])
@login_required
def browse_folders():
    """Browse folders for input source configuration"""
    import os
    import string
    
    path = request.args.get('path', '')
    
    result = {
        'current_path': path,
        'parent_path': '',
        'folders': [],
        'drives': []
    }
    
    # Get available drives on Windows
    if os.name == 'nt':
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                result['drives'].append({
                    'letter': letter,
                    'path': drive,
                    'label': f"Laufwerk {letter}:"
                })
    
    # If no path, return common user folders
    if not path:
        user_home = os.path.expanduser('~')
        common_folders = [
            {'name': 'Benutzerordner', 'path': user_home},
            {'name': 'Desktop', 'path': os.path.join(user_home, 'Desktop')},
            {'name': 'Dokumente', 'path': os.path.join(user_home, 'Documents')},
            {'name': 'Downloads', 'path': os.path.join(user_home, 'Downloads')},
            {'name': 'OneDrive', 'path': os.path.join(user_home, 'OneDrive')},
        ]
        for folder in common_folders:
            if os.path.exists(folder['path']):
                result['folders'].append({
                    'name': folder['name'],
                    'path': folder['path'],
                    'is_common': True
                })
        return jsonify(result)
    
    # Normalize path
    path = os.path.normpath(path)
    result['current_path'] = path
    
    # Get parent path
    parent = os.path.dirname(path)
    if parent != path:
        result['parent_path'] = parent
    
    # Folders to skip (system/hidden)
    skip_folders = {'$Recycle.Bin', '$RECYCLE.BIN', 'System Volume Information', 
                    'Recovery', 'ProgramData', 'All Users', 'Default', 'Default User',
                    'AppData', 'Application Data', 'Local Settings'}
    
    # List folders in current path
    try:
        if os.path.exists(path) and os.path.isdir(path):
            items = []
            try:
                items = os.listdir(path)
            except PermissionError:
                result['error'] = 'Zugriff verweigert'
                return jsonify(result)
            
            for item in sorted(items):
                # Skip hidden and system folders
                if item.startswith('.') or item.startswith('$') or item in skip_folders:
                    continue
                
                item_path = os.path.join(path, item)
                try:
                    if os.path.isdir(item_path):
                        # Check if we can access it
                        try:
                            os.listdir(item_path)
                            result['folders'].append({
                                'name': item,
                                'path': item_path,
                                'is_common': False
                            })
                        except PermissionError:
                            # Skip folders we can't access
                            pass
                except (PermissionError, OSError):
                    pass
    except PermissionError:
        result['error'] = 'Zugriff verweigert'
    except Exception as e:
        result['error'] = str(e)
    
    return jsonify(result)






@api_bp.route('/folders/create', methods=['POST'])
@login_required  
def create_folder():
    """Create a new folder"""
    import os
    
    data = request.get_json()
    path = data.get('path', '')
    
    if not path:
        return jsonify({'success': False, 'error': 'Kein Pfad angegeben'})
    
    try:
        os.makedirs(path, exist_ok=True)
        return jsonify({'success': True, 'path': path})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ============================================================================
# DASHBOARD STATS & ACTIONS
# ============================================================================

@api_bp.route('/stats', methods=['GET'])
@login_required
def get_stats():
    """Get dashboard statistics"""
    # Global counts
    stats = {
        'pending': Document.query.filter_by(status='pending').count(),
        'ready': Document.query.filter_by(status='ready').count(),
        'transferred': Document.query.filter_by(status='transferred').count()
    }
    
    # Source stats
    sources = InputSource.query.all()
    source_stats = []
    
    # Recalculate globals to ensure sync
    g_pending = 0
    g_ready = 0
    g_transferred = 0
    
    for s in sources:
        doc_count = s.documents.filter(Document.status != 'rejected').count()
        pending_count = s.documents.filter(Document.status == 'pending').count()
        analyzing_count = s.documents.filter(Document.status == 'analyzing').count()
        ready_count = s.documents.filter(Document.status == 'ready').count()
        transferred_count = s.documents.filter(Document.status == 'transferred').count()
        rejected_count = s.documents.filter(Document.status == 'rejected').count() 
        
        g_pending += pending_count
        g_ready += ready_count
        g_transferred += transferred_count
        
        # Calculate accuracy/analytics
        analyzed_docs = s.documents.filter(Document.analyzed_at.isnot(None)).all()
        analyzed_count = len(analyzed_docs)
        
        total_fields = 0
        total_corrections = 0
        category_changes = 0
        times = []
        
        for d in analyzed_docs:
            if d.manual_corrections:
                total_corrections += d.manual_corrections
            if d.ai_category_changed:
                category_changes += 1
            
            # Field count approximation
            data = d.get_extracted_data()
            if data:
                total_fields += len(data)
            else:
                total_fields += 5
            
            # Time
            start = d.analysis_started_at or d.received_at
            if start and d.analyzed_at:
                delta = (d.analyzed_at - start).total_seconds()
                if delta > 0:
                    times.append(delta)

        accuracy = None
        if total_fields > 0:
            accuracy = max(0, round((1 - total_corrections / total_fields) * 100, 1))
            
        avg_time = round(sum(times) / len(times), 1) if times else None

        source_stats.append({
            'id': s.id,
            'is_active': s.is_active,
            'auto_analyze': s.auto_analyze,
            'doc_count': doc_count,
            'pending': pending_count,
            'analyzing_count': analyzing_count,
            'ready': ready_count,
            'transferred': transferred_count,
            'rejected': rejected_count,
            'accuracy': accuracy,
            'analyzed_count': analyzed_count,
            'category_changes': category_changes,
            'avg_time_seconds': avg_time
        })
        
    global_stats = {
        'pending': g_pending,
        'ready': g_ready,
        'transferred': g_transferred
    }
        
    return jsonify({
        'global': global_stats,
        'sources': source_stats
    })


@api_bp.route('/sources/<int:source_id>/auto-analyze', methods=['PATCH'])
@login_required
def toggle_auto_analyze(source_id):
    """Toggle auto-analyze flag for a source"""
    source = InputSource.query.get_or_404(source_id)
    data = request.get_json()
    
    if 'enabled' in data:
        source.auto_analyze = bool(data['enabled'])
        db.session.commit()
        
        # Trigger analysis if enabled
        if source.auto_analyze:
             try:
                from ..scheduler import trigger_background_analysis_for_source
                trigger_background_analysis_for_source(source.id)
             except ImportError:
                pass # Scheduler might run independently
        
        return jsonify({
            'success': True,
            'source_id': source.id,
            'auto_analyze': source.auto_analyze,
            'message': f"Auto-Analyse für '{source.name}' {'aktiviert' if source.auto_analyze else 'deaktiviert'}"
        })
    
    return jsonify({'success': False, 'error': 'Missing "enabled" parameter'}), 400

