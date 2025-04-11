import json
import re
import time
import logging
import traceback
from flask import current_app
from app import db
from app.models.book import Book, Chapter
from app.services.claude_api import ClaudeClient
from sqlalchemy.exc import SQLAlchemyError

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BookGenerator:
    def __init__(self, claude_client):
        self.claude_client = claude_client
    
    def generate_table_of_contents(self, title, market_niche, purpose):
        """
        Genera la tabla de contenidos del libro con estructura de capítulos.
        
        Returns:
            dict: La tabla de contenidos y los tokens consumidos
        """
        logger.info(f"Generando tabla de contenidos para libro: '{title}'")
        
        prompt = f"""
        Quiero que me ayudes a crear una tabla de contenidos detallada para un libro con estas características:
        
        Título: {title}
        Nicho de mercado: {market_niche}
        Propósito: {purpose}
        
        Por favor, genera una tabla de contenidos con los siguientes requisitos:
        1. Debe tener exactamente 10 capítulos.
        2. Cada capítulo debe tener un título descriptivo y atractivo.
        3. Para cada capítulo, incluye una breve descripción del alcance que se cubrirá (entre 120 y 150 palabras).
        4. La estructura debe ser lógica y coherente, con una progresión natural desde el inicio hasta el final. Evita tantos subtitutlos como sea posible para que sea una lectura fluida.
        5. Evita repeticiones o solapamientos de temas entre capítulos.
        6. Cada capítulo debe complementar los anteriores y preparar el camino para los siguientes.
        
        IMPORTANTE: Tu respuesta debe ser un JSON válido con exactamente esta estructura:
        {{
            "title": "Título del libro",
            "chapters": [
                {{
                    "number": 1,
                    "title": "Título del capítulo 1",
                    "scope": "Descripción del alcance del capítulo 1"
                }},
                {{
                    "number": 2,
                    "title": "Título del capítulo 2",
                    "scope": "Descripción del alcance del capítulo 2"
                }},
                ...y así sucesivamente hasta el capítulo 10
            ]
        }}
        
        No incluyas ningún texto adicional antes o después del JSON.
        Asegúrate de que la respuesta sea un JSON válido y completo.
        """
        
        response = self.claude_client.generate_text(prompt, max_tokens=2000)
        
        # Verificar si hay error en la respuesta
        if 'error' in response:
            logger.error(f"Error al generar la tabla de contenidos: {response.get('error')}")
            return None
        
        # Extraer el JSON de la respuesta
        try:
            # Primero intentar parsear directamente - a veces Claude devuelve JSON limpio
            try:
                toc_data = json.loads(response['text'])
                logger.info("JSON extraído correctamente de la respuesta")
                return {
                    'toc': toc_data,
                    'input_tokens': response['input_tokens'],
                    'output_tokens': response['output_tokens']
                }
            except json.JSONDecodeError:
                # Si falla, buscar el primer patrón que se parezca a JSON en la respuesta
                logger.info("Intentando extraer JSON mediante expresión regular")
                json_match = re.search(r'({.*?})', response['text'].replace('\n', ''), re.DOTALL)
                
                if not json_match:
                    # Intentar de forma más agresiva
                    json_match = re.search(r'({[\s\S]*})', response['text'], re.DOTALL)
                
                if json_match:
                    json_str = json_match.group(1)
                    # Limpiar posibles caracteres no válidos
                    json_str = re.sub(r'```json|```', '', json_str)
                    toc_data = json.loads(json_str)
                    
                    # Verificar que el JSON tiene la estructura esperada
                    if 'chapters' not in toc_data:
                        raise ValueError("El JSON extraído no contiene la clave 'chapters'")
                    
                    logger.info(f"JSON extraído mediante regex: {len(toc_data['chapters'])} capítulos encontrados")
                    return {
                        'toc': toc_data,
                        'input_tokens': response['input_tokens'],
                        'output_tokens': response['output_tokens']
                    }
                else:
                    logger.error("No se encontró JSON en la respuesta")
                    logger.error(f"Contenido de la respuesta: {response['text'][:500]}...")
                    raise ValueError("No se encontró JSON en la respuesta")
        except Exception as e:
            logger.error(f"Error al parsear la tabla de contenidos: {str(e)}")
            logger.error(f"Respuesta recibida (primeros 500 caracteres): {response['text'][:500]}...")
            return None
    
    def generate_chapter(self, book, chapter_data, previous_chapters_summary=None):
        """
        Genera el contenido de un capítulo específico.
        
        Args:
            book: Instancia del modelo Book
            chapter_data: Información del capítulo a generar
            previous_chapters_summary: Resumen de los capítulos anteriores
            
        Returns:
            dict: El contenido generado y los tokens consumidos
        """
        logger.info(f"Generando capítulo {chapter_data['number']}: {chapter_data['title']}")
        
        # Preparar el contexto de los capítulos anteriores de forma más eficiente
        context = ""
        if previous_chapters_summary and len(previous_chapters_summary) > 0:
            # Limitar el tamaño del resumen para evitar exceder límites de tokens
            if len(previous_chapters_summary) > 1500:
                context = f"""
                Para mantener la coherencia con los capítulos anteriores, aquí tienes un resumen (resumido):
                {previous_chapters_summary[:1500]}...
                [Resumen truncado por longitud]
                """
            else:
                context = f"""
                Para mantener la coherencia con los capítulos anteriores, aquí tienes un resumen:
                {previous_chapters_summary}
                """
        
        # Crear un prompt más directo y eficiente con énfasis en la longitud requerida
        prompt = f"""
        Tarea: Escribir el Capítulo {chapter_data['number']} para un libro.
        
        INFORMACIÓN DEL LIBRO:
        - Título: "{book.title}"
        - Nicho de mercado: "{book.market_niche}" 
        - Propósito: "{book.purpose}"
        
        DETALLES DEL CAPÍTULO:
        - Número: {chapter_data['number']}
        - Título: "{chapter_data['title']}"
        - Alcance: {chapter_data['scope']}
        
        {context}
        
        REQUISITOS DEL CAPÍTULO:
        1. IMPORTANTE: Es absolutamente necesario que el capítulo tenga MÍNIMO 3,450 palabras y preferiblemente entre 3,500-4,000 palabras.
        2. El capítulo debe ser extremadamente detallado, profundo y completo, con ejemplos extensos y bien desarrollados.
        3. Estructura:
           - Introducción atractiva y completa (mínimo 150 palabras)
           - Desarrollo extenso del tema con varios subtemas (mínimo 3,000 palabras). No crear tantos subtitulos para crear una lectura fluida.
           - Ejemplos prácticos, anécdotas, o casos de estudio detallados
           - Conclusión sustanciosa que resuma los puntos clave y genere expectativa (mínimo 300 palabras)
        4. Características:
           - Profundo y exhaustivo en la cobertura de cada tema
           - Fluido y coherente con el resto del libro
           - Profesional pero accesible
           - Sin repeticiones de contenido previo
           - Incluye historias y ejemplos detallados para ilustrar los puntos principales
           - Usa lenguaje rico y diverso
        
        No incluyas marcadores como "Capítulo X" o "Introducción" al principio.
        Comienza directamente con el contenido del capítulo.
        
        RECUERDA: El capítulo DEBE tener como mínimo 3,450 palabras. Es el requisito más importante.
        """
        
        # Usar el límite de tokens proporcionado por el cliente
        # El cliente de Claude ahora maneja automáticamente los límites según el modelo
        max_output_tokens = self.claude_client.get_token_limit(self.claude_client.model)
        
        # Reducir ligeramente para evitar errores al límite
        max_output_tokens -= 100
        
        logger.info(f"Usando límite de max_tokens={max_output_tokens} para modelo {self.claude_client.model}")
        
        # Usar un número apropiado de tokens para el modelo en uso
        response = self.claude_client.generate_text(prompt, max_tokens=max_output_tokens)
        
        # Verificar si hay error en la respuesta
        if 'error' in response:
            logger.error(f"Error al generar el capítulo {chapter_data['number']}: {response.get('error')}")
            return {
                'content': f"Error al generar el capítulo: {response.get('error')}",
                'input_tokens': response.get('input_tokens', 0),
                'output_tokens': response.get('output_tokens', 0),
                'error': response.get('error')
            }
        
        # Verificar que el contenido generado tenga un tamaño adecuado
        content = response['text']
        word_count = len(content.split())
        
        # Verificar si el contenido es demasiado corto
        if word_count < 2500:  # Un capítulo muy corto probablemente indica un error
            logger.warning(f"Capítulo {chapter_data['number']} demasiado corto: {word_count} palabras")
            
            # Si es muy corto y hay indicaciones de error
            if "error" in content.lower() or "lo siento" in content.lower():
                logger.error(f"El contenido parece contener un mensaje de error: {content[:200]}...")
                return {
                    'content': f"Error al generar el capítulo. Contenido demasiado corto o con errores: {content}",
                    'input_tokens': response['input_tokens'],
                    'output_tokens': response['output_tokens'],
                    'error': "Contenido insuficiente o con errores"
                }
            # Si es corto pero no hay error aparente, intentamos regenerarlo solicitando más contenido
            else:
                logger.warning(f"Intentando ampliar el capítulo para alcanzar el mínimo de 3,450 palabras")
                
                # Prompt para ampliar el contenido
                expansion_prompt = f"""
                Has generado el siguiente contenido para el capítulo {chapter_data['number']} del libro "{book.title}":
                
                {content}
                
                Sin embargo, el contenido es demasiado corto (solo {word_count} palabras). Necesito que amplíes este capítulo para que tenga AL MENOS 3,450 palabras.
                
                Por favor, expande SIGNIFICATIVAMENTE cada sección, añadiendo:
                1. Más ejemplos concretos y detallados
                2. Anécdotas o casos de estudio relevantes
                3. Explicaciones más profundas de los conceptos
                4. Consideraciones adicionales relacionadas con el tema
                5. Implicaciones prácticas de las ideas presentadas
                
                Devuelve el capítulo COMPLETO, incluyendo el contenido original más las expansiones, para que tenga al menos 3,000 palabras en total.
                """
                
                # Intentar ampliar el contenido
                expansion_response = self.claude_client.generate_text(expansion_prompt, max_tokens=max_output_tokens)
                
                if 'error' not in expansion_response:
                    expanded_content = expansion_response['text']
                    expanded_word_count = len(expanded_content.split())
                    
                    logger.info(f"Capítulo ampliado de {word_count} a {expanded_word_count} palabras")
                    
                    # Actualizar el contenido y los tokens
                    content = expanded_content
                    response['input_tokens'] += expansion_response['input_tokens']
                    response['output_tokens'] += expansion_response['output_tokens']
                    word_count = expanded_word_count
                else:
                    logger.error(f"Error al ampliar el capítulo: {expansion_response.get('error')}")
                    # Continuamos con el contenido original, aunque sea corto
        
        # Verificar si el contenido está por debajo del objetivo de 3,450 palabras pero es utilizable
        if word_count < 3450 and word_count >= 2800:
            logger.warning(f"Capítulo {chapter_data['number']} tiene {word_count} palabras, por debajo del objetivo de 3,450 palabras, pero es utilizable")
        else:
            logger.info(f"Capítulo {chapter_data['number']} generado con éxito: {word_count} palabras")
        
        return {
            'content': content,
            'input_tokens': response['input_tokens'],
            'output_tokens': response['output_tokens']
        }
    
    def update_book_status(self, book_id, status, error=None):
        """
        Actualiza el estado del libro en la base de datos.
        
        Args:
            book_id: ID del libro
            status: Estado del libro ('processing', 'completed', 'error')
            error: Mensaje de error, si aplica
        """
        try:
            book = Book.query.get(book_id)
            if book:
                book.status = status
                book.error_message = error
                db.session.commit()
                logger.info(f"Estado del libro {book_id} actualizado a '{status}'")
        except SQLAlchemyError as e:
            logger.error(f"Error al actualizar el estado del libro {book_id}: {str(e)}")
            db.session.rollback()
    
    def generate_book(self, title, market_niche, purpose):
        """
        Genera un libro completo con todos sus capítulos.
        
        Args:
            title: Título del libro
            market_niche: Nicho de mercado
            purpose: Propósito del libro
            
        Returns:
            dict: Resultado de la operación con id del libro generado
        """
        # Obtener libro existente o crear uno nuevo
        try:
            book = Book.query.filter_by(title=title, market_niche=market_niche).first()
            
            if not book:
                book = Book(
                    title=title,
                    market_niche=market_niche,
                    purpose=purpose,
                    status='processing'
                )
                db.session.add(book)
                db.session.commit()
                logger.info(f"Nuevo libro creado con ID {book.id}: '{title}'")
            else:
                # Si el libro ya existe, actualizar su estado
                logger.info(f"Libro existente encontrado con ID {book.id}: '{title}'. Actualizando estado.")
                book.status = 'processing'
                book.error_message = None
                db.session.commit()
        except SQLAlchemyError as e:
            logger.error(f"Error al crear/actualizar el libro en la base de datos: {str(e)}")
            return {"error": f"Error de base de datos: {str(e)}"}
        
        try:
            # Generar la tabla de contenidos
            toc_result = self.generate_table_of_contents(title, market_niche, purpose)
            if not toc_result:
                error_msg = "No se pudo generar la tabla de contenidos. Verifica la configuración de la API de Claude."
                logger.error(error_msg)
                self.update_book_status(book.id, 'error', error_msg)
                return {"error": error_msg}
            
            toc = toc_result['toc']
            book.input_tokens += toc_result['input_tokens']
            book.output_tokens += toc_result['output_tokens']
            db.session.commit()
            
            # Verificar que la tabla de contenidos tenga el formato esperado
            if 'chapters' not in toc or not isinstance(toc['chapters'], list) or len(toc['chapters']) == 0:
                error_msg = "Formato de tabla de contenidos inválido"
                logger.error(f"{error_msg}: {toc}")
                self.update_book_status(book.id, 'error', error_msg)
                return {"error": error_msg}
            
            logger.info(f"Tabla de contenidos generada con {len(toc['chapters'])} capítulos")
            
            # Resumen de los capítulos anteriores para mantener coherencia
            previous_chapters_summary = ""
            
            # Generar cada capítulo
            for chapter_data in toc['chapters']:
                try:
                    # Verificar si el capítulo ya existe para evitar duplicados
                    existing_chapter = Chapter.query.filter_by(
                        book_id=book.id,
                        chapter_number=chapter_data['number']
                    ).first()
                    
                    if existing_chapter:
                        logger.info(f"Capítulo {chapter_data['number']} ya existe, saltando generación")
                        
                        # Actualizar el resumen para los siguientes capítulos
                        if len(previous_chapters_summary) > 0:
                            previous_chapters_summary += "\n\n"
                        previous_chapters_summary += f"Capítulo {chapter_data['number']}: {chapter_data['title']} - {chapter_data['scope']}\nResumen: {existing_chapter.content[:500]}..."
                        
                        continue
                    
                    # Generar contenido del capítulo
                    chapter_result = self.generate_chapter(book, chapter_data, previous_chapters_summary)
                    
                    # Crear capítulo en la base de datos
                    chapter = Chapter(
                        book_id=book.id,
                        chapter_number=chapter_data['number'],
                        title=chapter_data['title'],
                        scope=chapter_data['scope'],
                        content=chapter_result['content'],
                        input_tokens=chapter_result['input_tokens'],
                        output_tokens=chapter_result['output_tokens'],
                        thinking_tokens=chapter_result.get('thinking_tokens', 0)  # Capturar tokens de pensamiento
                    )                    

                    # Actualizar los tokens en el libro
                    book.input_tokens += chapter_result['input_tokens']
                    book.output_tokens += chapter_result['output_tokens']
                    book.thinking_tokens += chapter_result.get('thinking_tokens', 0)  # Acumular tokens de pensamiento
                    
                    # Verificar si hubo error en la generación del capítulo
                    if 'error' in chapter_result:
                        logger.error(f"Error al generar el capítulo {chapter_data['number']}: {chapter_result.get('error')}")
                        error_message = f"Error en capítulo {chapter_data['number']}: {chapter_result.get('error')}"
                        self.update_book_status(book.id, 'error', error_message)
                        return {"error": error_message}
                    
                    # Crear capítulo en la base de datos
                    chapter = Chapter(
                        book_id=book.id,
                        chapter_number=chapter_data['number'],
                        title=chapter_data['title'],
                        scope=chapter_data['scope'],
                        content=chapter_result['content'],
                        input_tokens=chapter_result['input_tokens'],
                        output_tokens=chapter_result['output_tokens']
                    )
                    
                    # Actualizar los tokens en el libro
                    book.input_tokens += chapter_result['input_tokens']
                    book.output_tokens += chapter_result['output_tokens']
                    
                    db.session.add(chapter)
                    db.session.commit()
                    logger.info(f"Capítulo {chapter_data['number']} guardado en la base de datos")
                    
                    # Actualizar el resumen de los capítulos anteriores
                    if len(previous_chapters_summary) > 0:
                        previous_chapters_summary += "\n\n"
                    previous_chapters_summary += f"Capítulo {chapter_data['number']}: {chapter_data['title']} - {chapter_data['scope']}\nResumen: {chapter_result['content'][:500]}..."
                    
                    # Para no sobrecargar la API, esperamos un breve período entre cada llamada
                    time.sleep(2)
                
                except Exception as e:
                    error_message = f"Error inesperado al generar el capítulo {chapter_data['number']}: {str(e)}"
                    logger.error(error_message)
                    logger.error(traceback.format_exc())
                    self.update_book_status(book.id, 'error', error_message)
                    return {"error": error_message}
            
            # Actualizar el estado del libro a completado
            self.update_book_status(book.id, 'completed')
            logger.info(f"Libro '{book.title}' generado completamente con {len(book.chapters)} capítulos")
            
            return {"success": True, "book_id": book.id, "book_uuid": book.uuid}
        
        except Exception as e:
            error_message = f"Error inesperado durante la generación del libro: {str(e)}"
            logger.error(error_message)
            logger.error(traceback.format_exc())
            self.update_book_status(book.id, 'error', error_message)
            return {"error": error_message}