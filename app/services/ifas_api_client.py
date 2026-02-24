"""
IFAS API Client
Handles communication with the IFAS system API
Based on IFAS API DOC specifications
"""
import os
import uuid
import json
from datetime import datetime
from flask import current_app


class IfasApiClient:
    """
    Client for IFAS API integration
    
    In production, this would connect to the real Kisters IFAS API.
    For development/testing, it operates in mock mode.
    """
    
    def __init__(self):
        self.api_url = current_app.config.get('IFAS_API_URL', 'http://localhost:5051/api/ifas')
        self.api_key = current_app.config.get('IFAS_API_KEY', '')
        self.mock_mode = current_app.config.get('IFAS_API_MOCK', True)
        
        # Mock data store
        self._mock_betriebe = [
            {'bs_nr': 'BS-1001', 'name': 'Musterfirma GmbH & Co KG', 'ort': 'Kiel', 'plz': '24103', 'strasse': 'Hafenstr. 1', 'sachbearbeiter': 'Max Müller'},
            {'bs_nr': 'BS-1002', 'name': 'Kampmann Bauunternehmung', 'ort': 'Lübeck', 'plz': '23552', 'strasse': 'Holstentorplatz 5', 'sachbearbeiter': 'Anna Schmidt'},
            {'bs_nr': 'BS-1003', 'name': 'Nord-Event Agentur', 'ort': 'Kiel', 'plz': '24103', 'strasse': 'Kaistraße 10', 'sachbearbeiter': 'Thomas Weber'},
            {'bs_nr': 'BS-1004', 'name': 'Schleswig-Holsteiner Bau GmbH', 'ort': 'Flensburg', 'plz': '24937', 'strasse': 'Nordstr. 45', 'sachbearbeiter': 'Lisa Hansen'},
            {'bs_nr': 'BS-1005', 'name': 'Kieler Hafenbetriebe', 'ort': 'Kiel', 'plz': '24103', 'strasse': 'Werftstr. 12', 'sachbearbeiter': 'Peter Jensen'},
            {'bs_nr': 'BS-1006', 'name': 'Ostholsteiner Meierei', 'ort': 'Eutin', 'plz': '23701', 'strasse': 'Milchweg 8', 'sachbearbeiter': 'Maria Schulz'},
        ]
    
    def search_betriebsstaette(self, query, ort=None, plz=None, limit=10):
        """
        Search for Betriebsstätten by name, location, or postal code
        
        Based on: ApiBetriebsstaetteSuche.sucheBs(name, ort, plz, limit)
        """
        if self.mock_mode:
            return self._mock_search_betriebsstaette(query, ort, plz, limit)
        
        # Production API call
        import requests
        try:
            params = {'q': query, 'limit': limit}
            if ort: params['ort'] = ort
            if plz: params['plz'] = plz
            
            response = requests.get(
                f"{self.api_url}/betriebsstaetten",
                params=params,
                headers={'Authorization': f'Bearer {self.api_key}'},
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            current_app.logger.error(f"IFAS API Error (search): {e}")
            return self._mock_search_betriebsstaette(query, ort, plz, limit)
    
    def create_betriebsstaette(self, data):
        """
        Create a new Betriebsstätte in IFAS
        """
        if self.mock_mode:
            return self._mock_create_betriebsstaette(data)
            
        import requests
        try:
            # Real API call
            endpoint = f"{self.api_url}/betriebe"
            response = requests.post(
                endpoint, 
                json=data, 
                headers={'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'},
                timeout=10
            )
            
            if response.status_code in (200, 201):
                return {'success': True, 'bs_nr': response.json().get('bs_nr')}
            else:
                return {'success': False, 'error': f"IFAS Error: {response.text}"}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _mock_create_betriebsstaette(self, data):
        """Mock creation of BS"""
        # Generate a fake BS-Nr
        import random
        bs_nr = f"BS-{random.randint(5000, 9999)}"
        # Add to mock store for searchability
        self._mock_betriebe.append({
            'bs_nr': bs_nr,
            'name': data.get('name', 'Mock Betrieb'),
            'ort': data.get('ort', 'Mockstadt'),
            'plz': data.get('plz', '00000'),
            'strasse': data.get('strasse', 'Mockstr. 1'),
            'sachbearbeiter': data.get('sachbearbeiter', 'Mock User')
        })
        current_app.logger.info(f"Mock IFAS: Created Betriebsstätte {bs_nr} with data: {data}")
        return {
            'success': True,
            'bs_nr': bs_nr,
            'message': f"Betriebsstätte wurde im Mock-Modus angelegt (BS-Nr: {bs_nr})"
        }
    

    def _mock_search_betriebsstaette(self, query, ort=None, plz=None, limit=10):
        """Mock search for development/testing"""
        query_lower = query.lower() if query else ''
        
        results = []
        for b in self._mock_betriebe:
            match = False
            # Enhanced search logic (Name, BS-Nr, Ort, Straße)
            if query_lower:
                if query_lower in b['name'].lower():
                    match = True
                elif query_lower in b['bs_nr'].lower():
                    match = True
                elif query_lower in b['ort'].lower():
                    match = True
                elif query_lower in b.get('strasse', '').lower():
                    match = True
            
            if ort and ort.lower() in b['ort'].lower():
                match = True
            if plz and plz in b['plz']:
                match = True
            
            if match:
                results.append(b)
                if len(results) >= limit:
                    break
        
        return results
    
    def create_anzeige(self, anzeige_data):
        """
        Create a new Anzeige in IFAS
        
        Args:
            anzeige_data: dict with:
                - art: IFAS Art (e.g., "Mutterschutz", "Sprengstoff")
                - zusatzart: IFAS Zusatzart (optional)
                - bs_nr: Betriebsstättennummer
                - fields: dict of content_id -> value mappings
        
        Returns:
            dict with success, aktenzeichen, or error
        """
        if self.mock_mode:
            return self._mock_create_anzeige(anzeige_data)
        
        # Production API call
        import requests
        try:
            # Structuring payload matching IFAS API expectation
            
            payload = {
                'art': anzeige_data.get('art'),
                'zusatzart': anzeige_data.get('zusatzart'),
                'status': 'Entwurf',
                'bs_nr': anzeige_data.get('bs_nr'),
                'datum': datetime.now().isoformat(),
                'sonderaktion_values': anzeige_data.get('fields', {}) # Map content_id -> value
            }
            
            response = requests.post(
                f"{self.api_url}/anzeigen",
                json=payload,
                headers={
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json'
                },
                timeout=30
            )
            
            if response.status_code in (200, 201):
                result = response.json()
                return {
                    'success': True,
                    'aktenzeichen': result.get('aktenzeichen')
                }
            else:
                return {
                    'success': False,
                    'error': f'IFAS API returned {response.status_code}: {response.text}'
                }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _mock_create_anzeige(self, anzeige_data):
        """Mock Anzeige creation for development/testing"""
        # Generate mock Aktenzeichen
        prefix_map = {
            'Mutterschutz': 'MuS',
            'Sprengstoff': 'Spr',
            'Unfall': 'Unf',
            'Baustelle': 'Bau',
            'Sonderaktion': 'Sdx'
        }
        
        art = anzeige_data.get('art', 'Allg')
        # Handle cases where Art is "Sonderaktion SX..."
        if 'Sonderaktion' in art:
            prefix = 'Sdx'
        else:
            prefix = prefix_map.get(art, 'Vg')
            
        year = datetime.now().year
        number = uuid.uuid4().hex[:4].upper()
        
        aktenzeichen = f"{prefix}. {number}/{year}-SIM"
        
        # Log for debugging
        current_app.logger.info(f"Mock IFAS: Created Anzeige {aktenzeichen}")
        current_app.logger.info(f"  Art: {art}")
        current_app.logger.info(f"  BS-Nr: {anzeige_data.get('bs_nr')}")
        current_app.logger.info(f"  Fields: {json.dumps(anzeige_data.get('fields', {}), indent=2)}")
        
        return {
            'success': True,
            'aktenzeichen': aktenzeichen,
            'mock': True,
            'message': f"Anzeige {aktenzeichen} erfolgreich angelegt (Mock)."
        }
    
    def create_post(self, post_data):
        """
        Create a Posteingang document in IFAS (ApiPost)
        """
        if self.mock_mode:
            current_app.logger.info(f"Mock IFAS: Created Post {post_data.get('betreff')}")
            return {'success': True, 'post_id': uuid.uuid4().hex, 'mock': True}
             
        import requests
        try:
            response = requests.post(
                f"{self.api_url}/post",
                json=post_data,
                headers={'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'},
                timeout=10
            )
            if response.status_code in (200, 201):
                return {'success': True, 'post_id': response.json().get('post_id')}
        except Exception as e:
            current_app.logger.error(f"IFAS API Post Error: {e}")
            return {'success': False, 'error': str(e)}

    def attach_document(self, aktenzeichen, file_path, filename=None):
        """
        Attach a document/file to an existing Anzeige
        """
        if not os.path.exists(file_path):
            return {'success': False, 'error': 'Datei nicht gefunden'}
        
        if self.mock_mode:
            current_app.logger.info(f"Mock IFAS: Attached {filename or file_path} to {aktenzeichen}")
            return {'success': True, 'mock': True}
        
        import requests
        try:
            with open(file_path, 'rb') as f:
                files = {'file': (filename or os.path.basename(file_path), f)}
                response = requests.post(
                    f"{self.api_url}/anzeigen/{aktenzeichen}/dokumente",
                    files=files,
                    headers={'Authorization': f'Bearer {self.api_key}'},
                    timeout=60
                )
            
            return {'success': response.status_code in (200, 201)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_arbeitskorb(self, status='NEU'):
        """
        Get items from IFAS Arbeitskorb (inbox)
        """
        if self.mock_mode:
            return []  # Mock returns empty
        
        import requests
        try:
            response = requests.get(
                f"{self.api_url}/arbeitskorb",
                params={'status': status},
                headers={'Authorization': f'Bearer {self.api_key}'},
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            return []
        except Exception:
            return []
    
    def update_post_status(self, post_id, status='DMS'):
        """
        Update status of a Posteingang item
        """
        if self.mock_mode:
            current_app.logger.info(f"Mock IFAS: Updated post {post_id} status to {status}")
            return {'success': True, 'mock': True}
        
        import requests
        try:
            response = requests.put(
                f"{self.api_url}/post/{post_id}/status",
                json={'status': status},
                headers={
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json'
                },
                timeout=10
            )
            return {'success': response.status_code == 200}
        except Exception as e:
            return {'success': False, 'error': str(e)}
