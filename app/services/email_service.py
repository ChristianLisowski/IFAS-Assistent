
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app
from ..models import AppConfig, User

def send_alert_to_subscribers(subject, body, alert_type='error'):
    """
    Send an alert email to all users who have subscribed to this alert type.
    alert_type: 'error' | 'pending_overflow'
    """
    try:
        # Get configuration
        smtp_server = AppConfig.get('smtp_server')
        smtp_port = int(AppConfig.get('smtp_port', 587))
        smtp_user = AppConfig.get('smtp_user')
        smtp_password = AppConfig.get('smtp_password')
        smtp_sender = AppConfig.get('smtp_sender', smtp_user)
        
        # Admin fallback (legacy)
        admin_email = AppConfig.get('admin_email')
        
        if not all([smtp_server, smtp_user, smtp_password]):
            current_app.logger.warning("SMTP configuration incomplete. Cannot send alert.")
            return False
            
        # Find recipients
        recipients = []
        
        # 1. Users with preference enabled
        users = User.query.all()
        for user in users:
            if user.email and user.notification_preferences:
                try:
                    prefs = json.loads(user.notification_preferences)
                    if prefs.get(alert_type):
                        recipients.append(user.email)
                except:
                    pass
        
        # 2. Fallback to admin_email if no users subscribed AND it's an error
        if not recipients and admin_email and alert_type == 'error':
            recipients.append(admin_email)
            
        if not recipients:
            current_app.logger.info(f"No subscribers for alert type '{alert_type}'. Skipping email.")
            return True # Not a failure, just no targets

        # Connect once
        if AppConfig.get('smtp_ssl') == 'true':
            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            
        server.login(smtp_user, smtp_password)
        
        # Send to each recipient
        for recipient in set(recipients): # dedup
            msg = MIMEMultipart()
            msg['From'] = smtp_sender
            msg['To'] = recipient
            msg['Subject'] = f"[IFAS-Assistent] {subject}"
            
            msg.attach(MIMEText(body, 'plain'))
            
            text = msg.as_string()
            server.sendmail(smtp_sender, recipient, text)
            
        server.quit()
        
        current_app.logger.info(f"Alert '{subject}' sent to {len(set(recipients))} recipients.")
        return True
        
    except Exception as e:
        current_app.logger.error(f"Failed to send alert: {e}")
        return False
