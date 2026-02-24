"""
LMStudio Service
Handles communication with LMStudio local LLM for document analysis
"""
import requests
import json
import re
from flask import current_app
from ..models import AppConfig


class LMStudioService:
    """Service for interacting with LMStudio LLM"""
    
    def __init__(self, base_url=None):
        self.base_url = base_url or current_app.config.get('LMSTUDIO_URL', 'http://localhost:1234/api/v1')
        self.model = current_app.config.get('LMSTUDIO_MODEL', 'local-model')
    
    def check_connection(self):
        """Check if LMStudio is running and responsive"""
        try:
            # 1. Get all available models
            models_resp = requests.get(f"{self.base_url}/models", timeout=5)
            # LMStudio API: GET /api/v1/models
            available_models = []
            if models_resp.status_code == 200:
                data = models_resp.json().get('data', [])
                available_models = [m.get('id') for m in data]

            # 2. Determine currently loaded model (Ping)
            loaded_model = None
            try:
                # Send a request WITHOUT model parameter to see who answers
                # LMStudio API: POST /api/v1/chat
                ping_resp = requests.post(
                    f"{self.base_url}/chat",
                    json={
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1
                    },
                    timeout=3
                )
                if ping_resp.status_code == 200:
                    loaded_model = ping_resp.json().get('model')
            except:
                pass
            
            return {
                'connected': True,
                'models': available_models, 
                'loaded_model': loaded_model,
                'url': self.base_url
            }
        except requests.exceptions.ConnectionError:
            return {'connected': False, 'error': 'LMStudio nicht erreichbar. Bitte starten Sie LMStudio.'}
        except Exception as e:
            return {'connected': False, 'error': str(e)}

    def load_model(self, model_id):
        """Force load a specific model using LMStudio's model load endpoint"""
        try:
            # LMStudio API: POST /api/v1/models/load
            current_app.logger.info(f"Loading model '{model_id}' via /models/load...")
            response = requests.post(
                f"{self.base_url}/models/load",
                json={"model": model_id},
                timeout=120  # Loading can take a while
            )
            
            if response.status_code == 200:
                current_app.logger.info(f"Model '{model_id}' loaded successfully.")
                return {
                    'success': True,
                    'loaded_model': model_id
                }
            else:
                return {
                    'success': False,
                    'error': f"Fehler Code {response.status_code}: {response.text}"
                }
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': 'LMStudio nicht erreichbar. Bitte starten Sie LMStudio.'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def analyze_document(self, text, attachments=None, categories=None, images=None):
        """
        Analyze document text and extract structured data
        
        Args:
            text: The main document text
            attachments: List of attachment text content
            categories: List of category dicts with fields info
            images: List of base64 encoded image strings (for Vision models)
        
        Returns:
            dict with category_id, extracted_data, confidence
        """
        if not categories:
            categories = []
        
        # Build the prompt
        prompt = self._build_analysis_prompt(text, attachments or [], categories)
        
        # Helper to get config
        ocr_model = current_app.config.get('LMSTUDIO_OCR_MODEL')
        
        # --- STAGE 1: OCR (if enabled and images present) ---
        if images and ocr_model and ocr_model.strip():
            print(f"DEBUG: Starting OCR Stage with model {ocr_model} for {len(images)} images")
            
            ocr_text_parts = []
            for idx, img_b64 in enumerate(images):
                try:
                    # Request strict OCR from vision model
                    ocr_messages = [
                        {
                            "role": "system",
                            "content": "Du bist ein OCR-System. Extrahiere den gesamten Text aus dem Bild exakt so wie er dort steht. Antworte NUR bedingungslos mit dem erkannten Text, ohne Kommentare."
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "OCR Text extraction:"},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                            ]
                        }
                    ]
                    
                    ocr_resp = requests.post(
                        f"{self.base_url}/chat",
                        json={
                            "model": ocr_model,
                            "messages": ocr_messages,
                            "temperature": 0.0,
                            "max_tokens": 2000
                        },
                        timeout=120
                    )
                    
                    if ocr_resp.status_code == 200:
                        ocr_content = ocr_resp.json()['choices'][0]['message']['content']
                        ocr_text_parts.append(f"--- SEITE {idx+1} (OCR) ---\n{ocr_content}")
                    else:
                        print(f"OCR Error Page {idx+1}: {ocr_resp.text}")
                        
                except Exception as ocr_e:
                     print(f"OCR Exception Page {idx+1}: {str(ocr_e)}")

            if ocr_text_parts:
                # Append OCR results to main text
                text = (text or "") + "\n\n" + "\n\n".join(ocr_text_parts)
                # Clear images so main model doesn't get them (it gets the text instead)
                images = None 


        messages = [
            {
                "role": "system",
                "content": """Du bist ein KI-Assistent für die Dokumentenanalyse in einer Behörde. 
Deine Aufgabe ist es, eingehende Dokumente zu klassifizieren und relevante Daten zu extrahieren.
Falls ein Bild bereitgestellt wird, nutze OCR-Fähigkeiten, um Text zu lesen, der im reinen Textformat fehlt (z.B. Kopfzeilen, Stempel).
Antworte IMMER im JSON-Format wie angegeben. Sei präzise und extrahiere nur Informationen, die eindeutig im Dokument stehen."""
            }
        ]

        if images:
            # Construct User Message with Text AND Images (Vision API format)
            content_parts = [{"type": "text", "text": prompt}]
            for img_b64 in images:
                content_parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{img_b64}"
                    }
                })
            messages.append({"role": "user", "content": content_parts})
        else:
            # Standard Text-Only Message
            messages.append({"role": "user", "content": prompt})
        
        try:
            response = requests.post(
                f"{self.base_url}/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": 4000
                },
                timeout=300
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # Debug: save raw response for inspection
                try:
                    import os, logging
                    debug_resp_path = os.path.join(current_app.instance_path, 'last_response.json')
                    with open(debug_resp_path, 'w', encoding='utf-8') as f:
                        json.dump(result, f, indent=2, ensure_ascii=False)
                    logging.info(f"LMStudio raw response saved to {debug_resp_path}")
                except Exception as dbg_err:
                    logging.error(f"Debug save failed: {dbg_err}")
                
                message = result.get('choices', [{}])[0].get('message', {})
                content = message.get('content', '') or ''
                
                # Handle tool_calls format (newer models like Gemma return data this way)
                if not content.strip() and message.get('tool_calls'):
                    tool_calls = message['tool_calls']
                    logging.info(f"LMStudio returned tool_calls ({len(tool_calls)} calls), extracting arguments...")
                    for tc in tool_calls:
                        fn = tc.get('function', {})
                        args = fn.get('arguments', '')
                        if args:
                            # The arguments might be a JSON string or already parsed
                            if isinstance(args, str):
                                content = args
                            else:
                                content = json.dumps(args)
                            logging.info(f"Extracted tool_call content: {content[:200]}...")
                            break
                
                if not content.strip():
                    raise Exception(f"LMStudio returned empty response. Keys in message: {list(message.keys())}")
                
                return self._parse_response(content, categories, text)
            else:
                raise Exception(f"LMStudio returned status {response.status_code}")
                
        except requests.exceptions.ConnectionError:
            raise Exception("LMStudio nicht erreichbar. Bitte starten Sie LMStudio.")
        except requests.exceptions.Timeout:
            raise Exception("LMStudio-Anfrage Timeout. Das Modell benötigt zu lange.")

    def reload_model(self):
        """
        Attempt to reload the configured model in LM Studio.
        Uses: POST /api/v1/models/load
        Useful if the model was unloaded or crashed.
        """
        try:
            current_app.logger.info(f"Attempting to reload model '{self.model}' via /models/load...")
            
            # LMStudio API: POST /api/v1/models/load
            response = requests.post(
                f"{self.base_url}/models/load",
                json={"model": self.model},
                timeout=120  # Loading takes considerable time
            )
            
            if response.status_code == 200:
                current_app.logger.info("Model reload command successful.")
                return True
                
            current_app.logger.warning(f"Model reload returned status {response.status_code}: {response.text}")
            return False
            
        except requests.exceptions.ConnectionError:
            current_app.logger.error("LMStudio nicht erreichbar beim Reload.")
            return False
        except Exception as e:
            current_app.logger.error(f"Error reloading model: {e}")
            return False
            
    def _build_analysis_prompt(self, text, attachments, categories):
        """Build the analysis prompt for LMStudio"""
        
        # Helper to get field details
        def get_field_info(cat):
            return "\n".join([f"    - {f.get('key')}: {f.get('label')} ({f.get('field_type')})" for f in cat.get('fields', [])])

        cat_descriptions = []
        for cat in categories:
            fields_info = get_field_info(cat)
            # FORCE EMPLOYER FIELDS into the schema description
            fields_info += "\n    - betrieb_name: Voller juristischer Name des Arbeitgebers (inkl. GmbH etc.) (text)"
            fields_info += "\n    - betrieb_strasse: Straße des Arbeitgebers (text)"
            fields_info += "\n    - betrieb_plz: PLZ des Arbeitgebers (text)"
            fields_info += "\n    - betrieb_ort: Ort des Arbeitgebers (text)"
            fields_info += "\n    - betrieb_email: E-Mail Adresse des Unternehmens/Ansprechpartners (email)"
            fields_info += "\n    - betrieb_ansprechpartner: Name des Ansprechpartners/Sachbearbeiters (text)"
            
            cat_descriptions.append(
                f"KATEGORIE ID {cat.get('id')}: {cat.get('display_name', cat.get('name'))}\n"
                f"  Keywords: {cat.get('keywords', '')}\n"
                f"  Erwartete Felder:\n{fields_info}"
            )
        
        categories_text = "\n\n".join(cat_descriptions) if cat_descriptions else "Keine Kategorien verfügbar"
        
        # Truncate text to avoid token limit issues (approx 3000 tokens ~ 12000 chars)
        max_text_len = 12000
        if len(text) > max_text_len:
            text = text[:max_text_len] + "\n... [Text gekürzt für KI-Analyse]"
            
        # Attachment texts
        attachments_text = ""
        if attachments:
            # Further limit attachments if main text is long
            remaining_len = 14000 - len(text)
            if remaining_len > 500:
                att_content = "\n\n".join(attachments)
                if len(att_content) > remaining_len:
                    att_content = att_content[:remaining_len] + "\n... [Anhänge gekürzt]"
                attachments_text = "\n\n--- ANHÄNGE ---\n" + att_content
        
        # Default Prompt Template
        default_prompt = """Du bist ein intelligenter Assistent für die Posteingangsverarbeitung ("IFAS-Assistent").
Deine Aufgabe ist es, Dokumente zu analysieren und relevante Daten als JSON zu extrahieren.

--- VERFÜGBARE KATEGORIEN ---
{categories}

--- DOKUMENT TEXT ---
{text}
{attachments}

--- ANWEISUNGEN ---
1. Analysiere den Dokumententext genau.
2. Wähle die passendste Kategorie aus der Liste oben.
   - Wenn der Text eine "Unfallanzeige" ist, wähle KEIN "Mutterschutz".
   - Wenn es um "Schwangerschaft" oder "Mutterschutz" geht, wähle "Mutterschutzmeldung".
3. Extrahiere die Daten für die Felder dieser Kategorie.
   - Gib NIEMALS Keys zurück, die nicht in der Felddefinition stehen.
   - Formatiere Daten sauber (z.B. Datum als DD.MM.YYYY).
   - Extrahiere "Unfallzeit" oder andere Uhrzeiten immer im Format "HH:MM" (z.B. "14:30").
   - ACHTUNG BEI ZAHLEN: Extrahiere "wöchentliche Arbeitszeit" oder Stundenangaben immer als reine Zahl oder Dezimalzahl (z.B. "38.5" statt "38,5 Std").
   - WICHTIG: Extrahiere IMMER die Daten des Arbeitgebers/Unternehmens, unabhängig von der Kategorie:
     - "betrieb_name": Der VOLLE juristische Name des Unternehmens (inkl. Rechtsform wie GmbH, AG, e.V.). Nimm NICHT nur den Kurznamen (z.B. "Mustermann GmbH & Co. KG" statt "Mustermann").
     - "betrieb_strasse": Straße und Hausnummer des Betriebs (Suche in Kopfzeilen, Fußzeilen, Absenderfeld).
     - "betrieb_plz": Postleitzahl des Betriebs.
     - "betrieb_ort": Ort des Betriebs.
     - Unterscheide dies von der Wohnadresse der versicherten Person! Wenn keine explizite Betriebsadresse gefunden wird, suche nach dem Absender des Dokuments.
4. Bestimme die Konfidenz (0.0 bis 1.0).
   - Sei kritisch. Wenn wichtige Keywords fehlen, gib eine niedrige Konfidenz (< 0.6).
   - Wenn das Dokument sehr schlecht lesbar ist oder keinen Sinn ergibt, setze Konfidenz < 0.3.

Antworte AUSSCHLIESSLICH mit einem JSON-Objekt in diesem Format:
{
    "category_id": <ID der Kategorie oder null>,
    "confidence": <float 0.0-1.0>,
    "summary": "<Kurze Zusammenfassung des Inhalts>",
    "extracted_data": {
        "betrieb_name": "Musterfirma GmbH",
        "betrieb_strasse": "Musterstraße 1",
        "betrieb_plz": "12345",
        "betrieb_ort": "Musterstadt",
        "<feld_key>": "<wert>",
        ...
    }
}"""

        # Load from config or use default
        import logging
        try:
            stored_prompt = AppConfig.get('ai_system_prompt')
            if stored_prompt and len(stored_prompt.strip()) > 10:
                prompt_template = stored_prompt
            else:
                prompt_template = default_prompt
        except Exception as e:
            logging.error(f"Error loading system prompt: {e}")
            prompt_template = default_prompt

        # Replace placeholders
        prompt = prompt_template.replace('{categories}', categories_text)
        prompt = prompt.replace('{text}', text)
        prompt = prompt.replace('{attachments}', attachments_text)
        
        # Save last prompt for inspection
        try:
            import os
            debug_path = os.path.join(current_app.instance_path, 'last_prompt.txt')
            os.makedirs(os.path.dirname(debug_path), exist_ok=True)
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write(prompt)
        except Exception as e:
            print(f"Error saving last prompt: {e}")
        
        return prompt
    
    def _parse_response(self, content, categories, original_text=""):
        """Parse LLM response and extract structured data"""
        
        # Try to find JSON in the response
        json_match = re.search(r'\{[\s\S]*\}', content)
        
        if not json_match:
            # Fallback: try keyword matching
            return self._fallback_analysis(content, categories)
        
        try:
            data = json.loads(json_match.group())
            
            result = {
                'category_id': data.get('category_id'),
                'confidence': float(data.get('confidence', 0.5)),
                'extracted_data': data.get('extracted_data', {}),
                'reasoning': data.get('reasoning', '')
            }
            
            # Validate category_id exists
            if result['category_id']:
                valid_ids = [c.get('id') for c in categories]
                if result['category_id'] not in valid_ids:
                    # Try to match by name
                    cat_name = str(result['category_id']).lower()
                    for cat in categories:
                        if cat_name in cat.get('name', '').lower() or cat_name in cat.get('display_name', '').lower():
                            result['category_id'] = cat.get('id')
                            result['category_id'] = cat.get('id')
                            break
            
            # Normalize extracted keys against category fields
            # and format dates for HTML input (YYYY-MM-DD)
            normalized_data = {}
            if result['category_id'] and categories:
                # Find category
                category = next((c for c in categories if c.get('id') == result['category_id']), None)
                if category:
                    for field in category.get('fields', []):
                        key = field.get('key')
                        val = result['extracted_data'].get(key)
                        
                        # Case insensitive match if missing
                        if val is None:
                            for k, v in result['extracted_data'].items():
                                if k.lower() == key.lower():
                                    val = v
                                    break
                        
                        if val is not None:
                            # Date normalization (DD.MM.YYYY -> YYYY-MM-DD)
                            if field.get('field_type') == 'date' and isinstance(val, str):
                                try:
                                    # Try DD.MM.YYYY
                                    if '.' in val:
                                        parts = val.split('.')
                                        if len(parts) == 3:
                                            # specific fix for 2-digit years if needed, but assuming 4
                                            d, m, y = parts[0].strip(), parts[1].strip(), parts[2].strip()
                                            if len(d) == 1: d = '0' + d
                                            if len(m) == 1: m = '0' + m
                                            normalized_data[key] = f"{y}-{m}-{d}"
                                        else:
                                            normalized_data[key] = val # Keep original if not DD.MM.YYYY
                                    else:
                                        normalized_data[key] = val # Keep original if no dot (e.g., already ISO)
                                except:
                                    normalized_data[key] = val # On error, keep original
                            else:
                                normalized_data[key] = val

            # Explicitly preserve forced employer fields (betrieb_*)
            # because they are not part of the category whitelist
            for k, v in result['extracted_data'].items():
                if k.startswith('betrieb_') and v:
                    normalized_data[k] = v
                    # Also map to simple keys if not already present (convenience)
                    simple_key = k.replace('betrieb_', '')
                    if simple_key not in normalized_data:
                        normalized_data[simple_key] = v
            
            if normalized_data:
                result['extracted_data'] = normalized_data

                # Derivation logic for Beschaeftigungsart
                # Derive if missing OR if value is likely wrong
                art_key = 'beschaeftigungsart'
                current_art = normalized_data.get(art_key, '')
                valid_arts = ["Vollzeit", "Teilzeit", "Geringfügig", "Ausbildung"]
                
                # Check for working hours to derive type
                hours_key = next((k for k in normalized_data.keys() if 'wochentliche_arbeitszeit' in k.lower() or 'stunden' in k.lower()), None)
                
                if hours_key and normalized_data[hours_key]:
                    try:
                        hours_str = str(normalized_data[hours_key]).replace(',', '.').replace('Std', '').strip()
                        hours = float(hours_str)
                        
                        # Derive based on hours if current_art is empty or confusing
                        if not current_art or current_art not in valid_arts:
                            if hours >= 35:
                                result['extracted_data'][art_key] = "Vollzeit"
                            elif hours < 35 and hours > 0:
                                result['extracted_data'][art_key] = "Teilzeit"
                    except:
                        pass

                    # Add uncertainty metadata to the data (hidden field)
                    uncertain_fields = data.get('uncertain_fields', [])
                    if uncertain_fields:
                        # Normalize uncertain keys too
                        normalized_uncertain = []
                        for u_key in uncertain_fields:
                             lower_u_key = u_key.lower().strip()
                             if lower_u_key in expected_keys:
                                 normalized_uncertain.append(expected_keys[lower_u_key])
                             else:
                                 normalized_uncertain.append(u_key)
                                 
                        normalized_data['_meta'] = {'uncertain_fields': normalized_uncertain}
                        
                    result['extracted_data'] = normalized_data
                    
                    # --- HYBRID CONFIDENCE CALCULATION ---
                    # Calculate keyword overlap to verify AI confidence
                    # This prevents "Hallucinations" where AI is 95% confident on empty/wrong docs
                    
                    keywords = category.get('keywords', '').lower().split(',')
                    keywords = [k.strip() for k in keywords if k.strip()]
                    
                    if keywords:
                        text_lower = original_text.lower() if original_text else content.lower()
                        
                        found_keywords = sum(1 for k in keywords if k in text_lower)
                        keyword_score = found_keywords / len(keywords) if keywords else 0.0
                        
                        # Logic: If AI is very confident (>0.8) but we found very few keywords (<20%),
                        # then likely the AI is hallucinating or the document is a bad scan (no OCR).
                        if result['confidence'] > 0.8 and keyword_score < 0.2:
                            old_conf = result['confidence']
                            # Reduce confidence drastically
                            result['confidence'] = max(0.1, keyword_score * 2) 
                            result['reasoning'] += f" [System-Korrektur: Konfidenz von {old_conf:.2f} auf {result['confidence']:.2f} reduziert, da kaum Keywords gefunden wurden.]"
                        
                        # Add derivation debug to reasoning
                        if art_key in normalized_data:
                             with open('debug_derivation.log', 'a') as f:
                                f.write(f"FINAL: beschaeftigungsart ({art_key}) set to '{normalized_data[art_key]}'\\n")
            
            return result
            
        except json.JSONDecodeError:
            return self._fallback_analysis(content, categories)
    
    def _fallback_analysis(self, text, categories):
        """Fallback keyword-based analysis"""
        text_lower = text.lower()
        
        best_match = None
        best_score = 0
        
        for cat in categories:
            keywords = cat.get('keywords', '').lower().split(',')
            score = sum(1 for kw in keywords if kw.strip() and kw.strip() in text_lower)
            
            if score > best_score:
                best_score = score
                best_match = cat
        
        return {
            'category_id': best_match.get('id') if best_match else None,
            'confidence': min(0.3 + (best_score * 0.1), 0.7) if best_match else 0.0,
            'extracted_data': {},
            'reasoning': 'Fallback-Analyse basierend auf Schlüsselwörtern'
        }
