from flask import render_template, redirect, url_for, request, jsonify, current_app, send_file
from app.routes import main_bp
from app import db
from app.models.book import Book, Chapter
from app.services.claude_api import ClaudeClient
from app.services.book_generator import BookGenerator
from app.services.docx_exporter import DocxExporter
import threading
from datetime import datetime
import logging
import os
import time

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Diccionario para rastrear los hilos activos de generación
active_generation_threads = {}

@main_bp.route('/')
def index():
    """Página principal con lista de libros generados"""
    books = Book.query.order_by(Book.created_at.desc()).all()
    return render_template('index.html', books=books)

@main_bp.route('/generate', methods=['GET', 'POST'])
def generate():
    """Página para generar un nuevo libro"""
    if request.method == 'POST':
        title = request.form.get('title')
        market_niche = request.form.get('market_niche')
        purpose = request.form.get('purpose')
        
        if not all([title, market_niche, purpose]):
            return jsonify({
                'error': 'Todos los campos son requeridos',
                'status': 'error'
            }), 400
        
        # Verificar si ya existe un libro con el mismo título
        existing_book = Book.query.filter_by(title=title).first()
        if existing_book:
            # Si existe y está en estado de error, podemos reintentar
            if existing_book.status == 'error':
                logger.info(f"Reiniciando generación para libro existente: {title} (ID: {existing_book.id})")
                book = existing_book
                book.status = 'processing'
                book.error_message = None
                db.session.commit()
            # Si está completo o en proceso, no permitir duplicados
            else:
                logger.warning(f"Intento de crear libro duplicado: {title}")
                return jsonify({
                    'message': 'Ya existe un libro con este título', 
                    'status': 'duplicate',
                    'book_uuid': existing_book.uuid
                }), 400
        else:
            # Crear el libro en la base de datos para poder seguir su progreso
            book = Book(
                title=title,
                market_niche=market_niche,
                purpose=purpose,
                status='processing'
            )
            db.session.add(book)
            db.session.commit()
            logger.info(f"Nuevo libro creado: {title} (ID: {book.id})")
        
        # Verificar si la API key está configurada
        api_key = current_app.config['CLAUDE_API_KEY']
        if not api_key or api_key == 'tu_api_key_de_claude_aqui':
            book.status = 'error'
            book.error_message = "Error de configuración: API key de Claude no definida. Actualiza tu archivo .env"
            db.session.commit()
            logger.error("API key de Claude no configurada")
            return jsonify({
                'error': 'API key de Claude no configurada',
                'status': 'error',
                'book_uuid': book.uuid
            }), 400
        
        # Crear el cliente de Claude
        claude_client = ClaudeClient(
            api_key=api_key,
            api_url=current_app.config['CLAUDE_API_URL'],
            model=current_app.config['CLAUDE_MODEL']
        )
        
        # Crear el generador de libros
        book_generator = BookGenerator(claude_client)
        
        # Guardar la app actual para usarla en el hilo
        app = current_app._get_current_object()
        
        # Iniciar la generación en un hilo separado
        def generate_book_thread():
            with app.app_context():  # ¡IMPORTANTE! Crear un contexto de aplicación para el hilo
                try:
                    logger.info(f"Iniciando generación del libro: {book.title} (ID: {book.id})")
                    result = book_generator.generate_book(title, market_niche, purpose)
                    
                    if "error" in result:
                        logger.error(f"Error en la generación del libro {book.id}: {result['error']}")
                        book.status = 'error'
                        book.error_message = result["error"]
                        db.session.commit()
                    else:
                        logger.info(f"Libro generado con éxito: {book.title} (ID: {book.id})")
                except Exception as e:
                    logger.error(f"Excepción no controlada durante la generación del libro {book.id}: {str(e)}")
                    book.status = 'error'
                    book.error_message = f"Error inesperado: {str(e)}"
                    db.session.commit()
                finally:
                    # Eliminar el hilo del diccionario cuando termine
                    if book.id in active_generation_threads:
                        del active_generation_threads[book.id]
        
        # Iniciar el hilo solo si no hay otro activo para este libro
        if book.id not in active_generation_threads:
            thread = threading.Thread(target=generate_book_thread)
            thread.daemon = True  # El hilo se cerrará cuando el programa principal termine
            thread.start()
            
            # Guardar referencia al hilo activo
            active_generation_threads[book.id] = thread
            
            logger.info(f"Hilo de generación iniciado para libro {book.id}")
            return jsonify({
                'message': 'Generación de libro iniciada', 
                'status': 'processing',
                'book_uuid': book.uuid
            })
        else:
            logger.info(f"Ya existe un hilo de generación activo para el libro {book.id}")
            return jsonify({
                'message': 'La generación de este libro ya está en curso', 
                'status': 'processing',
                'book_uuid': book.uuid
            })
    
    return render_template('generate.html')

@main_bp.route('/book/<uuid>')
def view_book(uuid):
    """Página para ver un libro específico"""
    book = Book.query.filter_by(uuid=uuid).first_or_404()
    return render_template('view_book.html', book=book)

@main_bp.route('/book/<uuid>/regenerate/<int:chapter_number>')
def regenerate_chapter(uuid, chapter_number):
    """Regenera un capítulo específico"""
    book = Book.query.filter_by(uuid=uuid).first_or_404()
    
    # Verificar si el libro está en estado de error o completado
    if book.status not in ['error', 'completed']:
        return jsonify({
            'error': 'No se puede regenerar un capítulo mientras el libro está en proceso de generación',
            'status': 'error'
        }), 400
    
    # Verificar si el capítulo existe
    chapter = Chapter.query.filter_by(book_id=book.id, chapter_number=chapter_number).first()
    if not chapter:
        return jsonify({
            'error': f'El capítulo {chapter_number} no existe',
            'status': 'error'
        }), 404
    
    # Eliminar el capítulo para regenerarlo
    db.session.delete(chapter)
    db.session.commit()
    
    # Actualizar el estado del libro
    book.status = 'processing'
    book.error_message = None
    db.session.commit()
    
    # Crear el cliente de Claude y el generador
    claude_client = ClaudeClient(
        api_key=current_app.config['CLAUDE_API_KEY'],
        api_url=current_app.config['CLAUDE_API_URL'],
        model=current_app.config['CLAUDE_MODEL']
    )
    
    book_generator = BookGenerator(claude_client)
    
    # Guardar la app actual para usarla en el hilo
    app = current_app._get_current_object()
    
    # Función para regenerar en un hilo separado
    def regenerate_chapter_thread():
        with app.app_context():  # ¡IMPORTANTE! Crear un contexto de aplicación para el hilo
            try:
                # Obtener todos los capítulos actuales para mantener la coherencia
                chapters = Chapter.query.filter_by(book_id=book.id).order_by(Chapter.chapter_number).all()
                
                # Construir el resumen de los capítulos anteriores
                previous_chapters_summary = ""
                for prev_chapter in chapters:
                    if prev_chapter.chapter_number < chapter_number:
                        previous_chapters_summary += f"Capítulo {prev_chapter.chapter_number}: {prev_chapter.title} - {prev_chapter.scope}\nResumen: {prev_chapter.content[:500]}...\n\n"
                
                # Obtener la información del capítulo de la estructura del libro
                # (asumiendo que la estructura está en el primer capítulo o reconstruyéndola)
                chapter_data = {
                    'number': chapter_number,
                    'title': f"Capítulo {chapter_number}",  # Título temporal
                    'scope': "Alcance temporal"  # Alcance temporal
                }
                
                # Buscar la información real del capítulo basado en otros capítulos
                for other_chapter in chapters:
                    if other_chapter.chapter_number == chapter_number - 1:
                        # Extraer información del capítulo anterior para reconstruir el contexto
                        chapter_data['title'] = f"Continuación de '{other_chapter.title}'"
                        chapter_data['scope'] = f"Siguiente tema después de: {other_chapter.scope}"
                        break
                
                # Generar el nuevo contenido del capítulo
                chapter_result = book_generator.generate_chapter(book, chapter_data, previous_chapters_summary)
                
                if 'error' in chapter_result:
                    logger.error(f"Error al regenerar el capítulo {chapter_number}: {chapter_result.get('error')}")
                    book.status = 'error'
                    book.error_message = f"Error al regenerar el capítulo {chapter_number}: {chapter_result.get('error')}"
                    db.session.commit()
                    return
                
                # Crear el capítulo en la base de datos
                new_chapter = Chapter(
                    book_id=book.id,
                    chapter_number=chapter_number,
                    title=chapter_data['title'],
                    scope=chapter_data['scope'],
                    content=chapter_result['content'],
                    input_tokens=chapter_result['input_tokens'],
                    output_tokens=chapter_result['output_tokens']
                )
                
                # Actualizar los tokens en el libro
                book.input_tokens += chapter_result['input_tokens']
                book.output_tokens += chapter_result['output_tokens']
                
                db.session.add(new_chapter)
                book.status = 'completed'
                db.session.commit()
                
                logger.info(f"Capítulo {chapter_number} regenerado con éxito para el libro {book.id}")
                
            except Exception as e:
                logger.error(f"Error al regenerar el capítulo {chapter_number}: {str(e)}")
                book.status = 'error'
                book.error_message = f"Error al regenerar el capítulo {chapter_number}: {str(e)}"
                db.session.commit()
    
    # Iniciar el hilo
    thread = threading.Thread(target=regenerate_chapter_thread)
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'message': f'Regeneración del capítulo {chapter_number} iniciada',
        'status': 'processing'
    })

@main_bp.route('/book/<uuid>/export/docx')
def export_book_docx(uuid):
    """Exportar libro a formato DOCX optimizado para Kindle"""
    book = Book.query.filter_by(uuid=uuid).first_or_404()
    
    # Verificar que el libro esté completo
    if book.status != 'completed':
        return jsonify({
            'error': 'El libro aún no está completo o tiene errores. Por favor, espere a que se generen todos los capítulos.',
            'status': book.status
        }), 400
    
    if len(book.chapters) < 10:
        return jsonify({
            'error': 'El libro no tiene los 10 capítulos requeridos.',
            'status': 'incomplete'
        }), 400
    
    # Crear el exportador DOCX
    docx_exporter = DocxExporter(book)
    
    try:
        # Generar el archivo DOCX
        docx_buffer = docx_exporter.generate_docx()
        
        # Establecer nombre de archivo seguro
        filename = f"{book.title.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.docx"
        
        # Enviar el archivo al cliente
        return send_file(
            docx_buffer,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        logger.error(f"Error al exportar libro a DOCX: {str(e)}")
        return jsonify({
            'error': f'Error al generar el archivo DOCX: {str(e)}',
            'status': 'error'
        }), 500

@main_bp.route('/api/book/<uuid>')
def get_book(uuid):
    """API para obtener los datos de un libro específico"""
    book = Book.query.filter_by(uuid=uuid).first_or_404()
    return jsonify(book.to_dict())

@main_bp.route('/api/books')
def get_books():
    """API para obtener la lista de todos los libros"""
    books = Book.query.order_by(Book.created_at.desc()).all()
    return jsonify([book.to_dict() for book in books])

@main_bp.route('/api/book/<uuid>/progress')
def get_book_progress(uuid):
    """API para verificar el progreso de generación de un libro"""
    book = Book.query.filter_by(uuid=uuid).first_or_404()
    completed_chapters = len(book.chapters)
    
    # Si el libro está en estado de error, devolver el mensaje de error
    if book.status == 'error':
        return jsonify({
            'book_id': book.id,
            'uuid': book.uuid,
            'title': book.title,
            'status': 'error',
            'error_message': book.error_message,
            'total_chapters': 10,
            'completed_chapters': completed_chapters,
            'progress_percentage': (completed_chapters / 10) * 100 if completed_chapters > 0 else 0
        })
    
    # Verificar si el libro está "atascado"
    is_stalled = False
    if book.status == 'processing' and book.last_updated:
        time_since_update = (datetime.utcnow() - book.last_updated).total_seconds()
        # Si han pasado más de 10 minutos sin actualización, considerarlo atascado
        if time_since_update > 600:
            is_stalled = True
    
    return jsonify({
        'book_id': book.id,
        'uuid': book.uuid,
        'title': book.title,
        'status': 'stalled' if is_stalled else book.status,
        'error_message': "La generación parece estar atascada. Puede intentar reiniciar la aplicación." if is_stalled else book.error_message,
        'total_chapters': 10,  # Siempre esperamos 10 capítulos
        'completed_chapters': completed_chapters,
        'progress_percentage': (completed_chapters / 10) * 100 if completed_chapters > 0 else 0,
        'last_updated': book.last_updated.isoformat() if book.last_updated else None
    })
    
@main_bp.route('/api/check-claude-connection')
def check_claude_connection():
    """
    Verifica la conexión con la API de Claude usando un mensaje simple
    para comprobar si la configuración es correcta.
    """
    api_key = current_app.config['CLAUDE_API_KEY']
    model = current_app.config['CLAUDE_MODEL']
    
    if not api_key or api_key == 'tu_api_key_de_claude_aqui':
        return jsonify({
            'status': 'error',
            'message': 'API key de Claude no configurada. Por favor, actualiza tu archivo .env'
        }), 400
    
    # Esta es la sección visible para el usuario en el frontend
    user_message = {
        'status': None,
        'message': None,
        'model': model,
        'response': None
    }
    
    # Esta es información adicional para diagnosticar problemas
    diagnostics = {
        'api_key_status': 'No válida',
        'model_status': 'No verificado',
        'api_url': current_app.config['CLAUDE_API_URL'],
        'suggested_action': 'Actualizar API key en .env',
        'timestamp': datetime.utcnow().isoformat()
    }
    
    try:
        # Primero probar si la API key tiene formato válido
        if not api_key.startswith(('sk-', 'pk-')):
            user_message.update({
                'status': 'error',
                'message': 'API key con formato incorrecto. Las API keys de Claude comienzan con "sk-" o "pk-".'
            })
            return jsonify(user_message), 400
        
        # La key parece válida, así que la marcamos como potencialmente correcta
        diagnostics['api_key_status'] = 'Formato correcto, verificando validez...'
        
        claude_client = ClaudeClient(
            api_key=api_key,
            api_url=current_app.config['CLAUDE_API_URL'],
            model=model
        )
        
        # Enviar un mensaje simple para verificar la conexión
        result = claude_client.generate_text(
            "Por favor responde con un 'OK' para verificar la conexión.", 
            max_tokens=10
        )
        
        if 'error' in result:
            # Analizar el error para dar información más específica
            error_msg = result.get('error', '')
            
            if '401' in error_msg or 'unauthorized' in error_msg.lower():
                diagnostics['suggested_action'] = 'La API key no es válida. Verifica que has copiado la key correctamente.'
                user_message.update({
                    'status': 'error',
                    'message': 'API key rechazada por Anthropic. Verifica que has copiado la key correctamente y que está activa.'
                })
            elif '404' in error_msg or 'not found' in error_msg.lower():
                diagnostics['suggested_action'] = 'El modelo especificado no existe o no está disponible con tu plan.'
                diagnostics['model_status'] = 'No disponible'
                user_message.update({
                    'status': 'error',
                    'message': f'El modelo "{model}" no existe o no está disponible con tu cuenta. Prueba con "claude-3-haiku-20240307" o "claude-instant-1.2".'
                })
            elif '429' in error_msg or 'rate' in error_msg.lower() or 'limit' in error_msg.lower():
                diagnostics['suggested_action'] = 'Tu cuenta ha alcanzado el límite de uso. Espera unos minutos o verifica tu plan.'
                user_message.update({
                    'status': 'error',
                    'message': 'Has alcanzado el límite de uso de la API. Espera unos minutos e intenta de nuevo, o verifica los límites de tu cuenta.'
                })
            else:
                user_message.update({
                    'status': 'error',
                    'message': f"Error al conectar con la API de Claude: {result.get('error')}"
                })
            
            # Incluir diagnósticos completos solo en entorno de desarrollo
            if current_app.config.get('FLASK_ENV') == 'development':
                user_message['diagnostics'] = diagnostics
                
            return jsonify(user_message), 400
        
        # Conexión exitosa
        diagnostics['api_key_status'] = 'Válida'
        diagnostics['model_status'] = 'Disponible'
        diagnostics['suggested_action'] = 'Todo está configurado correctamente'
        
        user_message.update({
            'status': 'success',
            'message': 'Conexión con la API de Claude exitosa',
            'response': result['text']
        })
        
        # Incluir diagnósticos completos solo en entorno de desarrollo
        if current_app.config.get('FLASK_ENV') == 'development':
            user_message['diagnostics'] = diagnostics
            
        return jsonify(user_message)
        
    except Exception as e:
        user_message.update({
            'status': 'error',
            'message': f"Error al verificar la conexión: {str(e)}"
        })
        
        # Incluir diagnósticos completos solo en entorno de desarrollo
        if current_app.config.get('FLASK_ENV') == 'development':
            diagnostics['error_details'] = str(e)
            user_message['diagnostics'] = diagnostics
            
        return jsonify(user_message), 500