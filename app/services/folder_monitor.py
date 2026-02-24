"""
Folder Monitor Service
Watches local and network folders for new documents
"""
import os
import time
import hashlib
import uuid
import shutil
from datetime import datetime
from flask import current_app


class FolderMonitor:
    """
    Service for monitoring folders for new documents
    Supports both local and network paths
    """
    
    SUPPORTED_EXTENSIONS = {'.pdf', '.docx', '.doc', '.odt', '.msg', '.eml'}
    
    def _calculate_file_hash(self, filepath):
        """Calculate SHA256 hash of file"""
        import hashlib
        sha256_hash = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                # Read and update hash string value in blocks of 4K
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except:
            return None
    
    def __init__(self, input_source=None):
        """
        Initialize with an InputSource model instance
        """
        self.input_source = input_source
        if input_source:
            self.config = input_source.get_config()
            self.source_id = input_source.id
        else:
            self.config = {}
            self.source_id = None
    
    def poll(self):
        """
        Poll the configured folder for new documents
        Returns: number of new documents imported
        """
        from ..models import db, Document, Attachment
        from .document_extractor import DocumentExtractor
        
        watch_path = self.config.get('path', '')
        watch_path = self.config.get('path', '')
        if not watch_path:
            return 0
            
        if not os.path.exists(watch_path):
            current_app.logger.warning(f"Watch path does not exist: {watch_path}")
            return 0
        
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        
        new_count = 0
        
        # Get list of files
        try:
            files = os.listdir(watch_path)
        except PermissionError:
            current_app.logger.error(f"Permission denied for folder: {watch_path}")
            return 0
        
        for filename in files:
            file_path = os.path.join(watch_path, filename)
            
            # Skip directories and unsupported files
            if os.path.isdir(file_path):
                continue
            
            ext = os.path.splitext(filename)[1].lower()
            if ext not in self.SUPPORTED_EXTENSIONS:
                continue
            
            # Calculate hash
            file_hash = self._calculate_file_hash(file_path)
            
            # Check if already imported (by filename OR hash)
            # First check filename in this source
            existing_name = Document.query.filter_by(
                filename=filename,
                source_id=self.source_id
            ).first()
            
            if existing_name:
                continue
                
            # Then check hash globally (avoid duplicates across sources or re-imports)
            if file_hash:
                existing_hash = Document.query.filter_by(content_hash=file_hash).first()
                if existing_hash:
                    current_app.logger.info(f"Skipping duplicate file (hash match): {filename}")
                    continue
            
            # Import the document
            try:
                doc_id = self._import_document(file_path, filename, file_hash)
                if doc_id:
                    new_count += 1
                    current_app.logger.info(f"Imported document: {filename}")
            except Exception as e:
                current_app.logger.error(f"Error importing {filename}: {e}")
        
        return new_count

    def delete_original(self, document):
        """
        Delete the original file from the source folder
        """
        if not document.original_path:
            return {'success': False, 'message': 'Kein Originalpfad vorhanden'}
            
        try:
            if os.path.exists(document.original_path):
                os.remove(document.original_path)
                return {'success': True, 'message': 'Originaldatei gelöscht'}
            else:
                return {'success': False, 'message': 'Originaldatei nicht gefunden (bereits gelöscht?)'}
        except Exception as e:
            current_app.logger.error(f"Error deleting original file {document.original_path}: {e}")
            return {'success': False, 'message': f'Fehler beim Löschen: {str(e)}'}
            
    def move_to_rejected(self, document):
        """
        Move the original file to configured discarded folder or '_rejected'
        """
        folder_name = getattr(self.source, 'discarded_folder', '')
        if not folder_name:
            folder_name = '_rejected'
            
        return self._move_file(document, folder_name)

    def move_to_processed(self, document):
        """
        Move the original file to configured processed folder
        """
        folder_name = getattr(self.source, 'processed_folder', '')
        if not folder_name:
            return {'success': False, 'message': 'Kein "Verarbeitet"-Ordner konfiguriert'}
            
        return self._move_file(document, folder_name)

    def move_to_trash(self, document):
        """
        Move the original file to configured trash folder
        """
        folder_name = getattr(self.source, 'trash_folder', '')
        if not folder_name:
            folder_name = '_trash'
            
        return self._move_file(document, folder_name)

    def _move_file(self, document, target_folder_name):
        """Helper to move file to a subfolder"""
        if not document.original_path or not os.path.exists(document.original_path):
            return {'success': False, 'message': 'Originaldatei nicht gefunden'}
            
        try:
            # Determine target directory
            # If absolute path, use it. Else, relative to source root (or file dir?)
            # Source config 'path' is the root.
            source_path = self.source.get_config().get('path')
            
            if os.path.isabs(target_folder_name):
                target_dir = target_folder_name
            elif source_path:
                target_dir = os.path.join(source_path, target_folder_name)
            else:
                # Fallback to relative to file
                target_dir = os.path.join(os.path.dirname(document.original_path), target_folder_name)
            
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)
                
            # Move file
            filename = os.path.basename(document.original_path)
            target_path = os.path.join(target_dir, filename)
            
            # Handle duplicates
            if os.path.exists(target_path):
                base, ext = os.path.splitext(filename)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                target_path = os.path.join(target_dir, f"{base}_{timestamp}{ext}")
                
            shutil.move(document.original_path, target_path)
            
            # Update document path? 
            # If we move it, we should probably update the record so we know where it is.
            # But FolderMonitor might re-index it if it's in a watched subfolder?
            # Implementation choice: Update to point to new location.
            # document.original_path = target_path # Caller should save this?
            
            return {'success': True, 'message': f'Datei nach {target_folder_name} verschoben', 'new_path': target_path}
            
        except Exception as e:
            current_app.logger.error(f"Error moving file {document.original_path}: {e}")
            return {'success': False, 'message': f'Fehler beim Verschieben: {str(e)}'}

    def _import_document(self, file_path, filename, file_hash=None):
        """
        Import a single document into the system
        """
        from ..models import db, Document
        from .document_extractor import DocumentExtractor
        
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        
        # Generate unique ID and storage path
        external_id = str(uuid.uuid4())
        ext = os.path.splitext(filename)[1]
        stored_filename = f"{external_id}{ext}"
        stored_path = os.path.join(upload_folder, stored_filename)
        
        # Copy file to storage
        shutil.copy2(file_path, stored_path)
        
        # Determine MIME type
        mime_types = {
            '.pdf': 'application/pdf',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.doc': 'application/msword',
            '.odt': 'application/vnd.oasis.opendocument.text',
            '.msg': 'application/vnd.ms-outlook',
            '.eml': 'message/rfc822'
        }
        mime_type = mime_types.get(ext.lower(), 'application/octet-stream')
        
        # Get file size
        file_size = os.path.getsize(file_path)
        
        # Create document record
        document = Document(
            external_id=external_id,
            filename=filename,
            original_path=file_path,
            stored_path=stored_path,
            mime_type=mime_type,
            file_size=file_size,
            content_hash=file_hash,
            source_id=self.source_id,
            status='pending'
        )
        
        # Extract text using DocumentExtractor
        extractor = DocumentExtractor()
        result = extractor.extract(stored_path)
        
        if result.get('success'):
            document.raw_text = result.get('text', '')
            # Handle page count if available in metadata
            if 'page_count' in result.get('metadata', {}):
                document.page_count = result['metadata']['page_count']
            # Handle email-specific metadata
            metadata = result.get('metadata', {})
            if metadata.get('subject'):
                document.email_subject = metadata['subject']
            if metadata.get('sender'):
                document.email_from = metadata['sender']
        else:
            current_app.logger.warning(f"Text extraction failed for {filename}: {result.get('error')}")
            document.raw_text = ''
        
        db.session.add(document)
        db.session.commit()
        
        # Move logic DISABLED to support explicit process flow
        # Original logic moved file immediately, but now we wait for 'transfer' or 'reject' status
        # processed_folder = current_app.config.get('PROCESSED_FOLDER')
        # if processed_folder and os.path.exists(processed_folder):
        # ...
        
        return document.id
    
    def _extract_msg(self, document, file_path):
        """Extract content from Outlook .msg file"""
        try:
            import extract_msg
            
            msg = extract_msg.Message(file_path)
            
            document.email_subject = msg.subject
            document.email_from = msg.sender
            document.email_date = msg.date
            document.raw_text = f"Betreff: {msg.subject}\nVon: {msg.sender}\n\n{msg.body}"
            
            # Handle attachments
            self._save_attachments(document, msg.attachments)
            
            msg.close()
        except ImportError:
            current_app.logger.warning("extract-msg not installed, skipping MSG extraction")
        except Exception as e:
            current_app.logger.error(f"Error extracting MSG: {e}")
    
    def _extract_eml(self, document, file_path):
        """Extract content from .eml email file"""
        try:
            import email
            from email import policy
            
            with open(file_path, 'rb') as f:
                msg = email.message_from_binary_file(f, policy=policy.default)
            
            document.email_subject = msg.get('Subject', '')
            document.email_from = msg.get('From', '')
            
            # Get email date
            date_str = msg.get('Date', '')
            if date_str:
                from email.utils import parsedate_to_datetime
                try:
                    document.email_date = parsedate_to_datetime(date_str)
                except:
                    pass
            
            # Extract body and attachments
            body_parts = []
            attachments = []
            
            for part in msg.walk():
                if part.get_content_maintype() == 'multipart':
                    continue
                    
                content_type = part.get_content_type()
                filename = part.get_filename()
                
                if filename:
                    # It's an attachment
                    attachments.append(part)
                elif content_type == 'text/plain':
                    payload = part.get_payload(decode=True)
                    if payload:
                        body_parts.append(payload.decode('utf-8', errors='replace'))
            
            document.raw_text = f"Betreff: {document.email_subject}\nVon: {document.email_from}\n\n" + "\n".join(body_parts)
            
            # Save attachments
            if attachments:
                # Adapter for _save_attachments (expects list of objects with .filename and .data or .save)
                # EML parts have .get_payload(decode=True)
                class EmlAttachment:
                    def __init__(self, part):
                        self.filename = part.get_filename()
                        self.data = part.get_payload(decode=True)
                
                wrapped_atts = [EmlAttachment(a) for a in attachments]
                self._save_attachments(document, wrapped_atts)
            
        except Exception as e:
            current_app.logger.error(f"Error extracting EML: {e}")
    
    def _save_attachments(self, document, attachments):
        """Save email attachments"""
        from ..models import db, Attachment
        from .pdf_extractor import PDFExtractor
        
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        
        for att in attachments:
            try:
                if hasattr(att, 'longFilename'):
                    filename = att.longFilename or att.shortFilename or 'attachment'
                else:
                    filename = getattr(att, 'filename', 'attachment')
                
                # Generate storage path
                att_id = str(uuid.uuid4())
                ext = os.path.splitext(filename)[1]
                stored_filename = f"att_{att_id}{ext}"
                stored_path = os.path.join(upload_folder, stored_filename)
                
                # Save attachment
                if hasattr(att, 'save'):
                    att.save(customPath=upload_folder, customFilename=stored_filename)
                elif hasattr(att, 'data'):
                    with open(stored_path, 'wb') as f:
                        f.write(att.data)
                
                if os.path.exists(stored_path):
                    # Create attachment record
                    attachment = Attachment(
                        document_id=document.id,
                        filename=filename,
                        stored_path=stored_path,
                        file_size=os.path.getsize(stored_path)
                    )
                    
                    # Determine MIME type
                    if ext.lower() == '.pdf':
                        attachment.mime_type = 'application/pdf'
                        # Extract text from PDF attachment
                        extractor = PDFExtractor()
                        result = extractor.extract(stored_path)
                        attachment.extracted_text = result.get('text', '')
                    
                    db.session.add(attachment)
                    
            except Exception as e:
                current_app.logger.error(f"Error saving attachment: {e}")
