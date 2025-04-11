import requests
import json
import time
import logging
from requests.exceptions import RequestException, Timeout

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ClaudeClient:
    # Diccionario de límites de tokens por modelo
    MODEL_LIMITS = {
        "claude-3-haiku-20240307": 4096,
        "claude-3-sonnet-20240229": 4096,
        "claude-3-opus-20240229": 4096,
        "claude-3.5-sonnet": 4096,
        "claude-3.5-haiku": 4096,
        "claude-3.7-sonnet": 20000,
        "claude-3.7-sonnet-20250219": 20000,
        "claude-instant-1.2": 4096,
        # Valores predeterminados para otros modelos
        "default": 4096
    }
    
    def __init__(self, api_key, api_url, model, max_retries=3, timeout=300):
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.max_retries = max_retries
        self.timeout = timeout
        # Headers actualizados para la API de Claude más reciente
        self.headers = {
            'Content-Type': 'application/json',
            'anthropic-version': '2023-06-01',
            'x-api-key': self.api_key
        }
    
    def get_token_limit(self, model_name):
        """Obtiene el límite de tokens para un modelo específico"""
        return self.MODEL_LIMITS.get(model_name.lower(), self.MODEL_LIMITS['default'])
    
    def generate_text(self, prompt, max_tokens=None):
        """
        Genera texto usando la API de Claude con reintentos y manejo de errores mejorado.
        
        Args:
            prompt: El texto del prompt a enviar a Claude
            max_tokens: Número máximo de tokens a generar en la respuesta (opcional)
            
        Returns:
            dict: Contiene el texto generado y los tokens consumidos
        """
        # Verificar el límite de tokens para el modelo actual
        model_limit = self.get_token_limit(self.model)
        
        # Si max_tokens no está especificado o excede el límite del modelo, usar el límite del modelo
        if max_tokens is None or max_tokens > model_limit:
            max_tokens = model_limit
            logger.info(f"Ajustando max_tokens a {max_tokens} basado en límites del modelo {self.model}")
        
        # Asegurar que el prompt no exceda los límites razonables
        prompt_length = len(prompt)
        if prompt_length > 100000:
            logger.warning(f"El prompt es muy largo ({prompt_length} caracteres). Truncando...")
            prompt = prompt[:100000] + "\n\n[Contenido truncado debido a longitud excesiva]"
        
        # Formato de payload actualizado para la API de Claude más reciente
        payload = {
            'model': self.model,
            'max_tokens': max_tokens,
            'temperature': 0.7,  # Añadir temperatura para mejorar la creatividad
            'messages': [
                {
                    'role': 'user',
                    'content': prompt
                }
            ]
        }
        
        # Añadir configuración de pensamiento extendido si es claude-3.7-sonnet
        if "claude-3.7-sonnet" in self.model.lower() or "claude-3.7-sonnet-20250219" in self.model.lower():
            payload['thinking'] = {
                "type": "enabled",
                "budget_tokens": 30000
            }
            logger.info(f"Habilitando pensamiento extendido con 16,000 tokens de presupuesto para {self.model}")
        
        # Registrar inicio de la llamada
        logger.info(f"Iniciando llamada a la API de Claude ({self.model}) - tamaño del prompt: {len(prompt)} caracteres")
        logger.info(f"Usando max_tokens={max_tokens} (límite del modelo: {model_limit})")
        
        # Mostrar el inicio del prompt para depuración
        if len(prompt) > 200:
            logger.debug(f"Inicio del prompt: {prompt[:200]}...")
        
        for attempt in range(1, self.max_retries + 1):
            try:
                # Añadir un pequeño retraso entre reintentos
                if attempt > 1:
                    sleep_time = 2 ** attempt  # Backoff exponencial
                    logger.info(f"Reintento {attempt}/{self.max_retries} después de {sleep_time} segundos...")
                    time.sleep(sleep_time)
                
                # Registrar el intento
                logger.info(f"Enviando solicitud a Claude (intento {attempt}/{self.max_retries})")
                
                # Realizar la solicitud con timeout
                start_time = time.time()
                response = requests.post(
                    self.api_url,
                    headers=self.headers,
                    json=payload,  # Usar json en lugar de data para manejo automático de la serialización
                    timeout=self.timeout
                )
                
                # Registrar tiempo de respuesta
                elapsed_time = time.time() - start_time
                logger.info(f"Respuesta recibida en {elapsed_time:.2f} segundos")
                
                # Intentar extraer detalles del error si existe
                if response.status_code != 200:
                    error_detail = ""
                    try:
                        error_content = response.json()
                        logger.error(f"Respuesta de error detallada: {error_content}")
                        if 'error' in error_content and 'message' in error_content['error']:
                            error_detail = f": {error_content['error']['message']}"
                            
                            # Si el error es sobre max_tokens, ajustar para el próximo intento
                            if 'max_tokens' in error_detail and attempt < self.max_retries:
                                if 'which is the maximum allowed' in error_detail:
                                    # Extraer el límite real si está en el mensaje de error
                                    import re
                                    match = re.search(r'max_tokens: \d+ > (\d+)', error_detail)
                                    if match:
                                        actual_limit = int(match.group(1))
                                        # Usar un valor ligeramente por debajo del límite
                                        new_limit = actual_limit - 100
                                        logger.warning(f"Ajustando max_tokens a {new_limit} basado en mensaje de error")
                                        payload['max_tokens'] = new_limit
                                        
                                        # Actualizar también el límite almacenado para este modelo
                                        self.MODEL_LIMITS[self.model.lower()] = actual_limit
                                        logger.warning(f"Actualizando límite conocido para {self.model} a {actual_limit}")
                                        continue
                                    
                            # Si el error es sobre thinking budget_tokens, ajustar para el próximo intento
                            if 'thinking.budget_tokens' in error_detail and 'thinking' in payload and attempt < self.max_retries:
                                if 'too large' in error_detail:
                                    # Extraer el límite real si está en el mensaje de error
                                    import re
                                    match = re.search(r'max allowable value is (\d+)', error_detail)
                                    if match:
                                        actual_limit = int(match.group(1))
                                        # Usar el valor máximo permitido
                                        logger.warning(f"Ajustando budget_tokens a {actual_limit} basado en mensaje de error")
                                        payload['thinking']['budget_tokens'] = actual_limit
                                        continue
                    except:
                        logger.error(f"No se pudo extraer detalle del error. Respuesta: {response.text[:500]}")
                    
                    # Si es un error 400, podría ser por la longitud del prompt
                    if response.status_code == 400 and attempt < self.max_retries:
                        # Reducir el prompt para el siguiente intento
                        prompt_reduction = int(len(prompt) * 0.8)  # Reducir a 80% del tamaño original
                        logger.warning(f"Reduciendo tamaño del prompt para siguiente intento a {prompt_reduction} caracteres")
                        prompt = prompt[:prompt_reduction] + "\n\n[Contenido truncado para ajustar límites de la API]"
                        payload['messages'][0]['content'] = prompt
                    
                    # Lanzar la excepción para que sea manejada por el bloque except
                    response.raise_for_status()
                
                # Parsear la respuesta
                result = response.json()
                
                # Verificar si hay mensajes de error en la respuesta JSON
                if 'error' in result:
                    error_msg = result.get('error', {}).get('message', 'Error desconocido en la API')
                    logger.error(f"Error en la respuesta de Claude: {error_msg}")
                    
                    # Si es un error recuperable, reintentar
                    if "rate_limit" in error_msg or "timeout" in error_msg:
                        continue
                    
                    return {
                        'text': f"Error en la API de Claude: {error_msg}",
                        'input_tokens': 0,
                        'output_tokens': 0,
                        'error': error_msg
                    }
                
                # Extraer el texto generado (cambio para adaptarse al formato actual de la API)
                if 'content' in result and len(result['content']) > 0:
                    generated_text = result['content'][0]['text']
                else:
                    logger.error("La respuesta no contiene el texto esperado")
                    return {
                        'text': "Error: La respuesta de la API no tiene el formato esperado",
                        'input_tokens': 0,
                        'output_tokens': 0,
                        'error': "Formato de respuesta inválido"
                    }
                
                # Extraer información de tokens (adaptado al formato actual de la API)
                input_tokens = result.get('usage', {}).get('input_tokens', 0)
                output_tokens = result.get('usage', {}).get('output_tokens', 0)
                
                # Extraer información sobre pensamiento extendido si está disponible
                thinking_tokens = result.get('usage', {}).get('thinking_tokens', 0)
                if thinking_tokens > 0:
                    logger.info(f"El pensamiento extendido utilizó {thinking_tokens} tokens adicionales")
                
                logger.info(f"Texto generado con éxito. Tokens de entrada: {input_tokens}, Tokens de salida: {output_tokens}")
                
                return {
                    'text': generated_text,
                    'input_tokens': input_tokens,
                    'output_tokens': output_tokens,
                    'thinking_tokens': thinking_tokens if thinking_tokens > 0 else 0
                }
                
            except Timeout:
                logger.error(f"Timeout al llamar a la API de Claude (intento {attempt}/{self.max_retries})")
                if attempt == self.max_retries:
                    return {
                        'text': "Error: La solicitud a la API de Claude agotó el tiempo de espera. Por favor, inténtalo de nuevo más tarde.",
                        'input_tokens': 0,
                        'output_tokens': 0,
                        'error': "Timeout"
                    }
            
            except RequestException as e:
                logger.error(f"Error en la solicitud HTTP (intento {attempt}/{self.max_retries}): {str(e)}")
                if attempt == self.max_retries:
                    # Intentar obtener detalles adicionales del error si están disponibles
                    error_detail = ""
                    try:
                        if hasattr(e, 'response') and e.response is not None:
                            error_content = e.response.json()
                            logger.error(f"Detalles del error: {error_content}")
                            if 'error' in error_content and 'message' in error_content['error']:
                                error_detail = f": {error_content['error']['message']}"
                    except:
                        pass
                    
                    return {
                        'text': f"Error al comunicarse con la API de Claude: {str(e)}{error_detail}",
                        'input_tokens': 0,
                        'output_tokens': 0,
                        'error': str(e) + error_detail
                    }
            
            except Exception as e:
                logger.error(f"Error inesperado (intento {attempt}/{self.max_retries}): {str(e)}")
                if attempt == self.max_retries:
                    return {
                        'text': f"Error inesperado al generar el texto: {str(e)}",
                        'input_tokens': 0,
                        'output_tokens': 0,
                        'error': str(e)
                    }
        
        # Si llegamos aquí, todos los intentos fallaron
        return {
            'text': "Error: No se pudo generar el texto después de varios intentos. Por favor, verifica tu conexión y la configuración de la API.",
            'input_tokens': 0,
            'output_tokens': 0,
            'error': "Máximo de reintentos alcanzado"
        }