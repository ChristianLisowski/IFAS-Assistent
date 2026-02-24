"""
PDF Extractor Service
Extracts text and metadata from PDF documents using PyMuPDF (fitz)
"""
import os


class PDFExtractor:
    """
    Service for extracting text and metadata from PDF files
    Uses PyMuPDF (fitz) for reliable text extraction
    """
    
    def __init__(self):
        pass
    
    def extract(self, file_path, strategy='standard', tesseract_cmd=None, ocr_lang='deu'):
        """
        Extract text and metadata from a PDF file
        
        Args:
            file_path: Path to the PDF file
            strategy: 'standard' (text layer) or 'tesseract' (OCR)
            tesseract_cmd: Path to tesseract executable (required for 'tesseract' strategy)
            ocr_lang: Language for OCR (default: 'deu')
        
        Returns:
            dict with 'text', 'pages', 'metadata'
        """
        if not os.path.exists(file_path):
            return {'text': '', 'pages': 0, 'error': 'File not found'}
        
        try:
            import fitz  # PyMuPDF
            
            doc = fitz.open(file_path)
            
            full_text = ""
            
            # --- STRATEGY: TESSERACT OCR ---
            if strategy == 'tesseract':
                try:
                    import pytesseract
                    from PIL import Image
                    import io
                    
                    if tesseract_cmd:
                        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
                        
                    ocr_parts = []
                    print(f"DEBUG: Starting Tesseract OCR for {file_path} (Pages: {len(doc)})")
                    
                    for page_num in range(len(doc)):
                        page = doc[page_num]
                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) # Zoom for better quality
                        img_data = pix.tobytes("png")
                        image = Image.open(io.BytesIO(img_data))
                        
                        # Run Tesseract
                        text = pytesseract.image_to_string(image, lang=ocr_lang)
                        ocr_parts.append(f"--- SEITE {page_num+1} (OCR) ---\n{text}")
                        
                    full_text = "\n\n".join(ocr_parts)
                    
                except ImportError:
                    return {'text': '', 'pages': 0, 'error': 'pytesseract or PIL not installed'}
                except Exception as e:
                    print(f"Tesseract Error: {e}")
                    return {'text': '', 'pages': 0, 'error': f'Tesseract Failed: {str(e)}'}

            # --- STRATEGY: STANDARD (Text Layer) ---
            else:
                text_parts = []
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    
                    # Use "blocks" to get text segments with coordinates
                    blocks = list(page.get_text("blocks")) # Ensure it's a list we can append to
                    
                    # NEW: Extract form fields (widgets) and add them as text blocks
                    try:
                        for widget in page.widgets():
                            if widget.field_value:
                                val = str(widget.field_value).strip()
                                if val:
                                    r = widget.rect
                                    blocks.append((r.x0, r.y0, r.x1, r.y1, val, -1, 0))
                    except Exception:
                        pass
    
                    # Filter for text blocks (type 0) and sort by vertical position (y0)
                    text_blocks = [b for b in blocks if b[6] == 0]
                    text_blocks.sort(key=lambda b: (b[1], b[0]))
                    
                    page_text = "\n".join([b[4] for b in text_blocks])
                    
                    if page_text.strip():
                        text_parts.append(page_text)
                
                full_text = "\n\n".join(text_parts)
            
            # Get metadata
            metadata = doc.metadata or {}
            
            result = {
                'text': full_text,
                'pages': len(doc),
                'metadata': {
                    'title': metadata.get('title', ''),
                    'author': metadata.get('author', ''),
                    'subject': metadata.get('subject', ''),
                    'creator': metadata.get('creator', ''),
                    'creation_date': metadata.get('creationDate', ''),
                    'mod_date': metadata.get('modDate', '')
                }
            }
            
            doc.close()
            return result
            
        except ImportError:
            # Fallback if PyMuPDF not installed
            return self._fallback_extract(file_path)
        except Exception as e:
            return {
                'text': '',
                'pages': 0,
                'error': str(e)
            }
    
    def _fallback_extract(self, file_path):
        """
        Fallback extraction using pdfplumber if available
        """
        try:
            import pdfplumber
            
            text_parts = []
            page_count = 0
            
            with pdfplumber.open(file_path) as pdf:
                page_count = len(pdf.pages)
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
            
            return {
                'text': "\n\n".join(text_parts),
                'pages': page_count,
                'metadata': {}
            }
        except ImportError:
            return {
                'text': '',
                'pages': 0,
                'error': 'No PDF extraction library available (PyMuPDF or pdfplumber required)'
            }
        except Exception as e:
            return {
                'text': '',
                'pages': 0,
                'error': str(e)
            }
    
    def get_text_by_page(self, file_path, page_number):
        """
        Get text from a specific page
        
        Args:
            file_path: Path to PDF
            page_number: 0-indexed page number
        
        Returns:
            str: Text content of the page
        """
        try:
            import fitz
            
            doc = fitz.open(file_path)
            if page_number < 0 or page_number >= len(doc):
                return ''
            
            text = doc[page_number].get_text()
            doc.close()
            return text
            
        except Exception:
            return ''
    
    def extract_tables(self, file_path):
        """
        Extract tables from PDF (useful for structured forms)
        Uses pdfplumber for table detection
        
        Returns:
            list of tables (each table is a list of rows)
        """
        try:
            import pdfplumber
            
            tables = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_tables = page.extract_tables()
                    if page_tables:
                        tables.extend(page_tables)
            
            return tables
            
        except ImportError:
            return []
        except Exception:
            return []
    
    def get_page_count(self, file_path):
        """Get the number of pages in a PDF"""
        try:
            import fitz
            doc = fitz.open(file_path)
            count = len(doc)
            doc.close()
            return count
        except Exception:
            return 0
