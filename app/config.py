import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Configuración de Claude API
    CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY')
    CLAUDE_API_URL = 'https://api.anthropic.com/v1/messages'
    CLAUDE_MODEL = os.environ.get('CLAUDE_MODEL')  
    MAX_TOKENS = 100000  # Límite de tokens para las respuestas