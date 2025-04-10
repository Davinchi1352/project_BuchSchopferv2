from datetime import datetime, timezone
import pytz

def format_number(value):
    """Formatea un número con separadores de miles"""
    try:
        return f"{int(value):,}".replace(',', '.')
    except (ValueError, TypeError):
        return value

def format_datetime(value):
    """
    Formatea una fecha y hora para la zona horaria de Austria (CET/CEST)
    
    Args:
        value: Un objeto datetime en UTC o None
        
    Returns:
        str: Fecha y hora formateada en el huso horario de Austria (Viena)
    """
    if not value:
        return "-"
    
    # Asegurar que el valor es consciente de zona horaria (aware)
    # Las fechas de SQLAlchemy suelen venir sin zona horaria
    if value.tzinfo is None:
        # Las fechas en la base de datos están en UTC, aunque no tienen la información de zona horaria
        value = pytz.utc.localize(value)
    
    # Convertir a la zona horaria de Austria (Viena)
    austria_tz = pytz.timezone('Europe/Vienna')
    austria_time = value.astimezone(austria_tz)
    
    # Formato: dd/mm/yyyy HH:MM (hora de Viena)
    return austria_time.strftime('%d/%m/%Y %H:%M') + ' (hora de Viena)'