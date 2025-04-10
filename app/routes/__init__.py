from flask import Blueprint

main_bp = Blueprint('main', __name__)

from app.routes import main  # Importa las rutas del blueprint