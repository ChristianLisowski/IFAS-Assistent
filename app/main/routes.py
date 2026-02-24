"""
Main Blueprint Routes
Dashboard, Validation View, and Document Processing
"""
from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file, abort
from flask_login import login_required, current_user
import os
from datetime import date

from ..models import db, Document, Category, InputSource, AppConfig

main_bp = Blueprint('main', __name__)





@main_bp.route('/')
def index():
    """Redirect to dashboard or login"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))


@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard with overview"""
    from sqlalchemy import func
    
    # Get document statistics
    pending_count = Document.query.filter_by(status='pending').count()
    ready_count = Document.query.filter_by(status='ready').count()
    transferred_count = Document.query.filter_by(status='transferred').count()
    
    # Get recent documents
    recent_documents = Document.query.order_by(Document.received_at.desc()).limit(10).all()
    
    # Get categories with document counts
    categories = Category.query.filter_by(is_active=True).all()
    
    # Get ALL input sources with document counts per status + analytics
    input_sources = InputSource.query.all()
    sources_data = []
    for source in input_sources:
        source_docs = Document.query.filter_by(source_id=source.id)
        
        # Count per status
        pending = source_docs.filter_by(status='pending').count()
        ready = source_docs.filter_by(status='ready').count()
        transferred = source_docs.filter_by(status='transferred').count()
        rejected = source_docs.filter_by(status='rejected').count()
        total = source_docs.count()
        
        # Accuracy analytics: docs that have been analyzed
        analyzed_docs = source_docs.filter(Document.analyzed_at.isnot(None)).all()
        total_corrections = sum(d.manual_corrections or 0 for d in analyzed_docs)
        category_changes = sum(1 for d in analyzed_docs if d.ai_category_changed)
        analyzed_count = len(analyzed_docs)
        
        # Compute accuracy: use actual field counts
        total_fields = 0
        for d in analyzed_docs:
            data = d.get_extracted_data()
            if data:
                total_fields += len(data)
            else:
                total_fields += 5 # Fallback if empty but analyzed
                
        if total_fields > 0:
            accuracy = max(0, round((1 - total_corrections / total_fields) * 100, 1))
        else:
            accuracy = None  # No data yet
        
        # Average processing time (analyzed_at - analysis_started_at)
        # ONLY use actual analysis time, do not fallback to received_at (which includes wait time)
        avg_time_seconds = None
        times = []
        for d in analyzed_docs:
            if d.analysis_started_at and d.analyzed_at:
                delta = (d.analyzed_at - d.analysis_started_at).total_seconds()
                # Filter out unrealistic values (e.g. < 1s or > 1 hour for a single doc is suspicious for pure AI time)
                if delta > 1: 
                    times.append(delta)
        
        if times:
            avg_time_seconds = round(sum(times) / len(times), 1)
        
        sources_data.append({
            'source': source,
            'pending': pending,
            'ready': ready,
            'transferred': transferred,
            'rejected': rejected,
            'total': total,
            'analyzed_count': analyzed_count,
            'accuracy': accuracy,
            'category_changes': category_changes,
            'avg_time_seconds': avg_time_seconds,
        })
    
    today_total = Document.query.filter(
        Document.received_at >= date.today()
    ).count()
    
    # Get OCR Config for Dashboard
    ocr_strategy = AppConfig.get('ocr_strategy', 'standard') # standard, vision, hybrid
    ocr_model = AppConfig.get('lmstudio_ocr_model', '')
    main_model = AppConfig.get('lmstudio_model', 'Standard')
    
    return render_template('main/dashboard.html',
                          pending_count=pending_count,
                          ready_count=ready_count,
                          transferred_count=transferred_count,
                          recent_documents=recent_documents,
                          categories=categories,
                          input_sources=input_sources,
                          sources_data=sources_data,
                          today_total=today_total,
                          ocr_strategy=ocr_strategy,
                          ocr_model=ocr_model,
                          main_model=main_model)


@main_bp.route('/validation')
@login_required
def validation():
    """Side-to-Side validation view"""
    # Get filters from query params
    source_id = request.args.get('source', type=int)
    category_id = request.args.get('category', type=int)
    status = request.args.get('status', 'ready')
    search = request.args.get('q', '').strip()
    
    # Build query
    query = Document.query
    
    if source_id:
        query = query.filter_by(source_id=source_id)
    
    if category_id:
        query = query.filter_by(category_id=category_id)
    
    if status and status != 'all':
        query = query.filter_by(status=status)
    
    if search:
        query = query.filter(
            db.or_(
                Document.filename.ilike(f'%{search}%'),
                Document.email_subject.ilike(f'%{search}%'),
                Document.raw_text.ilike(f'%{search}%')
            )
        )
    
    # Order by received date
    documents = query.order_by(Document.received_at.desc()).all()
    
    # Get filter options
    categories = Category.query.filter_by(is_active=True).order_by(Category.position).all()
    input_sources = InputSource.query.filter_by(is_active=True).all()
    
    # Get selected document if specified
    selected_doc_id = request.args.get('doc', type=int)
    selected_document = None
    if selected_doc_id:
        selected_document = Document.query.get(selected_doc_id)
    elif documents:
        selected_document = documents[0]
    
    return render_template('main/validation.html',
                          documents=documents,
                          selected_document=selected_document,
                          categories=categories,
                          input_sources=input_sources,
                          current_source=source_id,
                          filter_category=str(category_id) if category_id else None,
                          filter_status=status,
                          search_query=search)


@main_bp.route('/validation/list')
@login_required
def validation_list():
    """Return only the document list HTML for dynamic updates"""
    # Get filters from query params
    source_id = request.args.get('source', type=int)
    category_id = request.args.get('category', type=int)
    status = request.args.get('status', 'ready')
    search = request.args.get('q', '').strip()
    selected_doc_id = request.args.get('doc', type=int)
    
    # Build query
    query = Document.query
    
    if source_id:
        query = query.filter_by(source_id=source_id)
    
    if category_id:
        query = query.filter_by(category_id=category_id)
    
    if status and status != 'all':
        query = query.filter_by(status=status)
    
    if search:
        query = query.filter(
            db.or_(
                Document.filename.ilike(f'%{search}%'),
                Document.email_subject.ilike(f'%{search}%'),
                Document.raw_text.ilike(f'%{search}%')
            )
        )
    
    # Order by received date
    documents = query.order_by(Document.received_at.desc()).all()
    
    # Get select doc object for highlighting
    selected_document = None
    if selected_doc_id:
        selected_document = Document.query.get(selected_doc_id)
    
    return render_template('main/validation_list_fragment.html',
                          documents=documents,
                          selected_document=selected_document,
                          filter_status=status,
                          filter_category=str(category_id) if category_id else None,
                          search_query=search)


@main_bp.route('/document/<int:doc_id>/view')
@login_required
def view_document(doc_id):
    """Serve document file for preview"""
    document = Document.query.get_or_404(doc_id)
    
    if document.stored_path and os.path.exists(document.stored_path):
        return send_file(document.stored_path, 
                        mimetype=document.mime_type or 'application/pdf')
    
    abort(404)


@main_bp.route('/document/<int:doc_id>/attachment/<int:att_id>')
@login_required
def view_attachment(doc_id, att_id):
    """Serve attachment file"""
    from ..models import Attachment
    
    attachment = Attachment.query.filter_by(id=att_id, document_id=doc_id).first_or_404()
    
    if attachment.stored_path and os.path.exists(attachment.stored_path):
        return send_file(attachment.stored_path,
                        mimetype=attachment.mime_type,
                        download_name=attachment.filename)
    
    abort(404)
