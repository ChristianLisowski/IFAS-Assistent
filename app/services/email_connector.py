"""
Email Connector Service
Connects to IMAP mailboxes to fetch emails with attachments
"""
import os
import uuid
import imaplib
import email
import hashlib
from email import policy
from email.utils import parsedate_to_datetime
from datetime import datetime
from flask import current_app


class EmailConnector:
    """
    Service for connecting to IMAP email servers and importing emails
    """
    
    def _calculate_content_hash(self, content_bytes):
        """Calculate SHA256 hash of content"""
        return hashlib.sha256(content_bytes).hexdigest()

    
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
            
    def _get_connection(self):
        """Helper to establish IMAP connection"""
        server = self.config.get('server')
        port = self.config.get('port', 993)
        username = self.config.get('username')
        password = self.config.get('password')
        use_ssl = self.config.get('ssl', True)
        
        try:
            if use_ssl:
                mail = imaplib.IMAP4_SSL(server, port)
            else:
                mail = imaplib.IMAP4(server, port)
            
            mail.login(username, password)
            return mail
        except Exception as e:
            current_app.logger.error(f"IMAP Connection Error: {e}")
            raise

    def get_folders(self):
        """
        List all available folders on the IMAP server
        """
        try:
            mail = self._get_connection()
            status, folders = mail.list()
            mail.logout()
            
            folder_list = []
            if status == 'OK':
                for f in folders:
                    # Parse folder info (flags, delimiter, name)
                    # Example check: b'(\HasNoChildren) "/" "INBOX"'
                    try:
                        name = f.decode().split(' "|" ')[-1].strip().replace('"', '')
                        # Better parsing might be needed for quoted names with spaces
                        import re
                        match = re.search(r'"([^"]+)"$', f.decode())
                        if match:
                            name = match.group(1)
                        else:
                             # Fallback if no quotes
                             name = f.decode().split(' ')[-1].strip()
                        
                        folder_list.append(name)
                    except:
                        pass
                        
            return sorted(folder_list)
        except Exception as e:
            current_app.logger.error(f"Error listing folders: {e}")
            return []

    def create_folder(self, folder_name):
        """
        Create a new folder on the IMAP server
        """
        try:
            mail = self._get_connection()
            status, response = mail.create(folder_name)
            mail.logout()
            return status == 'OK'
        except Exception as e:
            current_app.logger.error(f"Error creating folder {folder_name}: {e}")
            return False

    def poll(self):
        """
        Poll the IMAP mailbox for new emails using UIDs
        Returns: number of new emails imported
        """
        from ..models import db, Document
        
        folder = self.config.get('folder', 'INBOX')
        
        try:
            mail = self._get_connection()
            mail.select(folder)
            
            # Search for unseen emails using UID
            status, response = mail.uid('search', None, 'UNSEEN')
            
            if status != 'OK':
                mail.logout()
                return 0
            
            # Get list of UIDs
            uids = response[0].split()
            new_count = 0
            
            for uid_bytes in uids:
                try:
                    uid = int(uid_bytes)
                    
                    # Fetch the email by UID
                    status, msg_data = mail.uid('fetch', uid_bytes, '(RFC822)')
                    if status != 'OK' or not msg_data:
                        continue
                    
                    # msg_data[0] is usually a tuple (header, body)
                    # We need to find the element that contains the RFC822 data
                    raw_email = None
                    for part in msg_data:
                        if isinstance(part, tuple):
                            raw_email = part[1]
                            break
                    
                    if not raw_email:
                        continue
                        
                    # Parse email
                    msg = email.message_from_bytes(raw_email, policy=policy.default)
                    
                    # Import the email
                    doc_id = self._import_email(msg, uid)
                    if doc_id:
                        new_count += 1
                        current_app.logger.info(f"Imported email UID {uid}: {msg.get('Subject', 'No Subject')}")
                    
                except Exception as e:
                    current_app.logger.error(f"Error processing email UID {uid_bytes}: {e}")
            
            mail.logout()
            return new_count
            
        except imaplib.IMAP4.error as e:
            current_app.logger.error(f"IMAP error: {e}")
            return 0
        except Exception as e:
            current_app.logger.error(f"Email connection error: {e}")
            return 0
    
    def _import_email(self, msg, uid):
        """
        Import a single email into the system
        """
        from ..models import db, Document
        
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        
        # Check if already imported by UID and Source
        existing = Document.query.filter_by(
            imap_uid=uid,
            source_id=self.source_id
        ).first()
        
        if existing:
            return None
            
        # Extract email metadata
        subject = msg.get('Subject', 'Kein Betreff')
        sender = msg.get('From', '')
        date_str = msg.get('Date', '')
        
        # Calculate hash of raw email content
        raw_content = msg.as_bytes()
        file_hash = self._calculate_content_hash(raw_content)
        
        # Check global hash duplicate (optional: duplicate/idempotency check)
        # Note: If we rely on UIDs, this is less critical, but good for safety
        if file_hash:
            existing_hash = Document.query.filter_by(content_hash=file_hash).first()
            if existing_hash:
                current_app.logger.info(f"Skipping duplicate email (hash match) UID {uid}")
                # We still might want to track it, but for now skip
                return None
        
        email_date = None
        if date_str:
            try:
                email_date = parsedate_to_datetime(date_str)
            except:
                email_date = datetime.utcnow()
        
        # Extract body
        body = self._extract_body(msg)
        
        # Create unique filename from subject
        safe_subject = "".join(c for c in subject[:50] if c.isalnum() or c in ' -_').strip()
        filename = f"Email_{safe_subject}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.eml"
        
        # Save raw email
        external_id = str(uuid.uuid4())
        stored_filename = f"{external_id}.eml"
        stored_path = os.path.join(upload_folder, stored_filename)
        
        with open(stored_path, 'wb') as f:
            f.write(msg.as_bytes())
        
        # Create document record
        document = Document(
            external_id=external_id,
            filename=filename,
            stored_path=stored_path,
            mime_type='message/rfc822',
            file_size=os.path.getsize(stored_path),
            content_hash=file_hash,
            source_id=self.source_id,
            imap_uid=uid,  # Save the UID
            email_subject=subject,
            email_from=sender,
            email_date=email_date,
            raw_text=f"Betreff: {subject}\nVon: {sender}\nDatum: {date_str}\n\n{body}",
            status='pending'
        )
        
        db.session.add(document)
        db.session.flush()  # Get document ID
        
        # Process attachments
        self._process_attachments(document, msg)
        
        db.session.commit()
        return document.id
    
    def _extract_body(self, msg):
        """Extract the email body text"""
        body_parts = []
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get('Content-Disposition', ''))
                
                # Skip attachments
                if 'attachment' in content_disposition:
                    continue
                
                if content_type == 'text/plain':
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        try:
                            body_parts.append(payload.decode(charset, errors='replace'))
                        except:
                            body_parts.append(payload.decode('utf-8', errors='replace'))
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or 'utf-8'
                try:
                    body_parts.append(payload.decode(charset, errors='replace'))
                except:
                    body_parts.append(payload.decode('utf-8', errors='replace'))
        
        return "\\n".join(body_parts)
    
    def _process_attachments(self, document, msg):
        """Process and save email attachments"""
        from ..models import db, Attachment
        from .pdf_extractor import PDFExtractor
        
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        
        for part in msg.walk():
            content_disposition = str(part.get('Content-Disposition', ''))
            
            if 'attachment' not in content_disposition:
                continue
            
            filename = part.get_filename()
            if not filename:
                continue
            
            # Decode filename if needed
            if isinstance(filename, bytes):
                filename = filename.decode('utf-8', errors='replace')
            
            # Get attachment content
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            
            # Generate storage path
            att_id = str(uuid.uuid4())
            ext = os.path.splitext(filename)[1]
            stored_filename = f"att_{att_id}{ext}"
            stored_path = os.path.join(upload_folder, stored_filename)
            
            # Save attachment
            with open(stored_path, 'wb') as f:
                f.write(payload)
            
            # Create attachment record
            attachment = Attachment(
                document_id=document.id,
                filename=filename,
                stored_path=stored_path,
                mime_type=part.get_content_type(),
                file_size=len(payload)
            )
            
            # Extract text from PDF attachments
            if ext.lower() == '.pdf':
                extractor = PDFExtractor()
                try:
                    result = extractor.extract(stored_path)
                    attachment.extracted_text = result.get('text', '')
                except Exception as e:
                    current_app.logger.error(f"Error extracting text from attachment {filename}: {e}")
            
            db.session.add(attachment)
    
    def move_to_folder(self, document, target_folder):
        """
        Move email to a specific folder and delete from original folder
        """
        if not document.imap_uid or not target_folder:
            return False
            
        folder = self.config.get('folder', 'INBOX')
        
        try:
            mail = self._get_connection()
            mail.select(folder)
            
            uid_str = str(document.imap_uid)
            
            # 1. Copy to Target
            try:
                res, data = mail.uid('COPY', uid_str, target_folder)
                if res != 'OK':
                    current_app.logger.warning(f"Could not copy to {target_folder}. Attempting to create.")
                    mail.create(target_folder)
                    res, data = mail.uid('COPY', uid_str, target_folder)
                    
            except Exception as copy_err:
                 current_app.logger.error(f"Error copying to {target_folder}: {copy_err}")
                 # If copy failed, DO NOT DELETE
                 mail.logout()
                 return False
            
            # 2. Mark as Deleted in Inbox
            mail.uid('STORE', uid_str, '+FLAGS', '(\\Deleted)')
            
            # 3. Expunge
            mail.expunge()
            
            mail.logout()
            current_app.logger.info(f"Moved email UID {uid_str} to {target_folder}")
            return True
            
        except Exception as e:
            current_app.logger.error(f"Error moving email to {target_folder}: {e}")
            return False

    def move_to_trash(self, document):
        """
        Move email to Trash folder (legacy wrapper)
        """
        # Get configured trash folder or default 'Trash'
        trash_folder = None
        if self.input_source:
             trash_folder = self.input_source.trash_folder
        
        if not trash_folder:
            trash_folder = 'Trash'
            
        return self.move_to_folder(document, trash_folder)

    def check_connection(self):
        """
        Simple boolean check if connection works
        """
        try:
            res = self.test_connection()
            return res.get('success', False)
        except:
            return False

    def get_stats(self):
        """
        Get mailbox statistics
        """
        folder = self.config.get('folder', 'INBOX')
        stats = {'total': 0, 'unseen': 0}
        
        try:
            mail = self._get_connection()
            mail.select(folder, readonly=True)
            
            # Count total
            status, messages = mail.search(None, 'ALL')
            if status == 'OK' and messages[0]:
                stats['total'] = len(messages[0].split())
                
            # Count unseen
            status, messages = mail.search(None, 'UNSEEN')
            if status == 'OK' and messages[0]:
                stats['unseen'] = len(messages[0].split())
                
            mail.logout()
            return stats
        except Exception as e:
            current_app.logger.error(f"Error getting IMAP stats: {e}")
            return stats

    def test_connection(self):
        """
        Test the IMAP connection
        Returns: dict with 'success', 'message', 'unseen_count'
        """
        folder = self.config.get('folder', 'INBOX')
        
        try:
            mail = self._get_connection()
            mail.select(folder)
            
            status, messages = mail.search(None, 'UNSEEN')
            unseen_count = len(messages[0].split()) if status == 'OK' and messages[0] else 0
            
            mail.logout()
            
            return {
                'success': True,
                'message': f'Verbindung erfolgreich. {unseen_count} ungelesene Nachrichten.',
                'unseen_count': unseen_count
            }
            
        except imaplib.IMAP4.error as e:
            return {'success': False, 'message': f'IMAP-Fehler: {e}'}
        except Exception as e:
            return {'success': False, 'message': f'Verbindungsfehler: {e}'}
