"""
Scheduler Module
Handles background tasks using Flask-APScheduler.
Includes:
- Auto-polling of input sources
- Background document analysis queue
"""
from flask_apscheduler import APScheduler
from flask import current_app
from datetime import datetime, timedelta
import threading
import time

scheduler = APScheduler()

# Lock to prevent concurrent analysis of the same document
analysis_lock = threading.Lock()

def init_scheduler(app):
    """Initialize the scheduler with the Flask app"""
    # Config
    app.config['SCHEDULER_API_ENABLED'] = True
    app.config['SCHEDULER_TIMEZONE'] = "Europe/Berlin"
    
    scheduler.init_app(app)
    
    # Register jobs
    @scheduler.task('interval', id='poll_sources', seconds=60)
    def poll_active_sources():
        """Poll all active input sources for new documents"""
        with app.app_context():
            from .models import InputSource, db
            from .services.folder_monitor import FolderMonitor
            from .services.email_connector import EmailConnector
            from .models import AppConfig, Document
            
            try:
                sources = InputSource.query.filter_by(is_active=True).all()
                total_new = 0
                
                for source in sources:
                    # Check if due for poll
                    if source.last_poll and (datetime.utcnow() - source.last_poll).total_seconds() < source.poll_interval:
                        continue
                        
                    # Poller based on type
                    new_docs = 0
                    if source.source_type in ['folder', 'network']:
                        monitor = FolderMonitor(source)
                        new_docs = monitor.poll()
                    elif source.source_type == 'imap':
                        connector = EmailConnector(source)
                        new_docs = connector.poll()
                    
                    # Update last poll
                    source.last_poll = datetime.utcnow()
                    db.session.commit()
                    
                    if new_docs > 0:
                        total_new += new_docs
                        app.logger.info(f"Source {source.name} polled: {new_docs} new documents")
                        
                    # Trigger auto-analysis if enabled AND (new docs found OR pending docs exist)
                    # This ensures we pick up where we left off or retry failed ones
                    if source.auto_analyze:
                        pending_count = source.documents.filter_by(status='pending').count()
                        if new_docs > 0:
                            app.logger.info(f"Triggering analysis for source {source.name} (New documents)")
                            trigger_background_analysis_for_source(source.id)
                        elif pending_count > 0:
                            app.logger.info(f"Triggering analysis for source {source.name} (Pending documents: {pending_count})")
                            trigger_background_analysis_for_source(source.id)
                            
                if total_new > 0:
                    app.logger.info(f"Poll cycle complete. Total new: {total_new}")
                    
                # Check for overflow (too many documents waiting for validation)
                ready_count = Document.query.filter_by(status='ready').count()
                if ready_count > 10:
                    last_alert_str = AppConfig.get('last_overflow_alert_time')
                    last_alert = datetime.fromisoformat(last_alert_str) if last_alert_str else None
                    
                    if not last_alert or (datetime.utcnow() - last_alert).total_seconds() > 14400: # 4 hours
                        app.logger.warning(f"Overflow detected: {ready_count} documents waiting for validation.")
                        from .services.email_service import send_alert_to_subscribers
                        
                        sent = send_alert_to_subscribers(
                            subject=f"Warnung: {ready_count} Dokumente warten auf Validierung",
                            body=f"Es warten aktuell {ready_count} Dokumente auf Ihre Validierung.\nBitte loggen Sie sich ein und arbeiten Sie die Warteschlange ab.",
                            alert_type='pending_overflow'
                        )
                        
                        if sent:
                            # Update last alert timestamp
                            config = AppConfig.query.filter_by(key='last_overflow_alert_time').first()
                            if not config:
                                config = AppConfig(key='last_overflow_alert_time', value=datetime.utcnow().isoformat())
                                db.session.add(config)
                            else:
                                config.value = datetime.utcnow().isoformat()
                            db.session.commit()

            except Exception as e:
                app.logger.error(f"Error in poll_sources job: {e}")

    scheduler.start()
    app.logger.info("Scheduler started")

def trigger_background_analysis_for_source(source_id):
    """Trigger background analysis for all pending documents in a source"""
    scheduler.add_job(
        id=f'analyze_source_{source_id}_{int(time.time())}',
        func=analyze_pending_documents,
        args=[source_id],
        trigger='date',
        run_date=datetime.now() + timedelta(seconds=1),
        replace_existing=False
    )

def analyze_pending_documents(source_id=None):
    """
    Background job to analyze pending documents.
    If source_id is provided, only analyze documents from that source.
    """
    # We need the app context since this runs in a separate thread/job
    # The 'scheduler' object keeps a ref to 'app' if initialized with init_app.
    
    app = scheduler.app
    with app.app_context():
        from .models import Document, Category, db, InputSource
        from .services.lmstudio_service import LMStudioService
        from .services.email_service import send_alert_to_subscribers
        
        # Check if we can run analysis (lock)
        if not analysis_lock.acquire(blocking=False):
            return
            
        try:
            # Check source auto-analyze status if source_id is provided
            if source_id:
                source = InputSource.query.get(source_id)
                if not source or not source.auto_analyze:
                    return

            query = Document.query.filter_by(status='pending')
            if source_id:
                query = query.filter_by(source_id=source_id)
                
            docs = query.limit(10).all() # Process in smaller batches
            
            if not docs:
                return
                
            app.logger.info(f"Starting background analysis for {len(docs)} documents...")
            
            # Check connection first
            lm_service = LMStudioService()
            connection = lm_service.check_connection()
            if not connection.get('connected'):
                app.logger.warning("LMStudio not reachable. Skipping analysis.")
                return

            categories = Category.query.filter(Category.is_active == True, Category.ifas_art != 'SYSTEM').all()
            
            consecutive_errors = 0
            max_consecutive_errors = 3
            
            for doc in docs:
                # GRACEFUL STOP CHECK:
                # Re-check if source auto-analyze is still enabled
                if source_id:
                    # Refresh source object to get latest DB state
                    # We use a fresh query or refresh the existing object if bound
                    try:
                        current_source = InputSource.query.get(source_id)
                        if not current_source or not current_source.auto_analyze:
                            app.logger.info(f"Auto-analysis disabled for source {source_id}. Stopping batch gracefully.")
                            break
                    except Exception:
                        pass

                try:
                    # Double check status (race condition)
                    db.session.refresh(doc)
                    if doc.status != 'pending':
                        continue
                        
                    # Mark as analyzing
                    doc.status = 'analyzing'
                    doc.analysis_started_at = datetime.now()
                    db.session.commit()
                    
                    app.logger.info(f"Analyzing document {doc.id} ({doc.filename})")
                    
                    # Collect attachment texts
                    attachment_texts = []
                    for att in doc.attachments:
                        if att.extracted_text:
                            attachment_texts.append(f"Anhang '{att.filename}':\n{att.extracted_text}")
                    
                    # Analyze with retry mechanism for reliability
                    max_retries = 1
                    retry_count = 0
                    
                    success = False
                    
                    while retry_count <= max_retries:
                        try:
                            result = lm_service.analyze_document(
                                text=doc.raw_text or '',
                                attachments=attachment_texts,
                                categories=[c.to_dict() for c in categories]
                            )
                            # Success - process result
                            
                            # Update document with results
                            if result.get('category_id'):
                                doc.category_id = result['category_id']
                            
                            if result.get('extracted_data'):
                                doc.set_extracted_data(result['extracted_data'])
                            
                            if result.get('confidence'):
                                doc.ai_confidence = result['confidence']
                            
                            doc.status = 'ready'
                            doc.analyzed_at = datetime.now()
                            
                            # Count detected fields
                            if result.get('extracted_data'):
                                 doc.total_fields_detected = len(result['extracted_data'])
                            
                            db.session.commit()
                            success = True
                            consecutive_errors = 0 # Reset error counter on success
                            break # Break retry loop
                            
                        except Exception as e:
                            # Network error / crash
                            if retry_count < max_retries:
                                app.logger.warning(f"Analysis failed for {doc.filename}: {e}. Attempting model reload...")
                                if lm_service.reload_model():
                                    retry_count += 1
                                    time.sleep(5) # Wait for model to load
                                    continue
                            
                            app.logger.error(f"Analysis failed for {doc.filename} (Network/Crash): {e}")
                            doc.status = 'failed' # valid state for manual intervention? Or reset to pending?
                            # User wants "stagnation" fixed. If we set to 'failed', it won't be picked up again continuously.
                            # But if it's a specific file crashing the model, we shouldn't retry it forever in 'pending'.
                            # Let's set to 'failed' to avoid infinite loops on bad files.
                            doc.analysis_started_at = None
                            db.session.commit()
                            
                            consecutive_errors += 1
                            break # Break retry loop
                            
                    if not success and consecutive_errors >= max_consecutive_errors:
                        # Stop the batch loop if we failed multiple times in a row (system outage)
                        error_msg = f"Analyse-Batch gestoppt nach {consecutive_errors} aufeinanderfolgenden Fehlern."
                        app.logger.error(error_msg)
                        
                        # Send admin alert
                        send_alert_to_subscribers(
                            subject="Analyse-Batch gestoppt (Systemfehler)",
                            body=f"Der Analyse-Batch wurde gestoppt.\nGrund: {consecutive_errors} Dokumente in Folge konnten nicht analysiert werden.\n\nBitte prüfen Sie LM Studio.",
                            alert_type='error'
                        )
                        break

                except Exception as e:
                    app.logger.error(f"Error processing document {doc.id} outer loop: {e}")
                    # Ensure we don't leave it in 'analyzing'
                    try:
                        doc.status = 'failed'
                        doc.analysis_started_at = None
                        db.session.commit()
                    except:
                        db.session.rollback()
                    
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        break

            # Check if there are more pending documents AND we didn't break due to error/stop
            if consecutive_errors < max_consecutive_errors:
                # Only re-trigger if source is still active
                should_continue = True
                if source_id:
                    s = InputSource.query.get(source_id)
                    if not s or not s.auto_analyze:
                        should_continue = False
                
                if should_continue:
                    # Check count
                    current_pending = Document.query.filter_by(status='pending')
                    if source_id:
                        current_pending = current_pending.filter_by(source_id=source_id)
                        
                    if current_pending.count() > 0:
                        app.logger.info(f"Batch complete, re-triggering for remaining documents.")
                        trigger_background_analysis_for_source(source_id)
                    
        finally:
            analysis_lock.release()

    @scheduler.task('interval', id='cleanup_stuck', seconds=120)
    def cleanup_stuck_documents():
        """Watchdog: Reset documents stuck in 'analyzing' for too long"""
        with app.app_context():
            from .models import Document, db
            # Find docs analyzing > 5 mins
            cutoff = datetime.now() - timedelta(minutes=5)
            stuck = Document.query.filter(
                Document.status == 'analyzing',
                Document.analysis_started_at < cutoff
            ).all()
            
            if stuck:
                app.logger.warning(f"Watchdog found {len(stuck)} stuck documents. Resetting.")
                for d in stuck:
                    d.status = 'pending'
                    d.analysis_started_at = None
                db.session.commit()
