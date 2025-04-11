import uuid
from datetime import datetime, timezone
from app import db

def generate_uuid():
    return str(uuid.uuid4())

def get_utc_now():
    """Devuelve la fecha y hora actual en UTC con información de zona horaria"""
    return datetime.now(timezone.utc)

class Book(db.Model):
    __tablename__ = 'books'
    
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), default=generate_uuid, unique=True, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    market_niche = db.Column(db.String(255), nullable=False)
    purpose = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=get_utc_now)
    input_tokens = db.Column(db.Integer, default=0)
    output_tokens = db.Column(db.Integer, default=0)
    thinking_tokens = db.Column(db.Integer, default=0)  # Nuevo campo para tokens de pensamiento extendido
    status = db.Column(db.String(20), default='processing')  # 'processing', 'completed', 'error'
    error_message = db.Column(db.Text)
    last_updated = db.Column(db.DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    chapters = db.relationship('Chapter', backref='book', lazy=True, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f'<Book {self.title}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'uuid': self.uuid,
            'title': self.title,
            'market_niche': self.market_niche,
            'purpose': self.purpose,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'status': self.status,
            'error_message': self.error_message,
            'input_tokens': self.input_tokens,
            'output_tokens': self.output_tokens,
            'thinking_tokens': self.thinking_tokens,  # Incluir tokens de pensamiento en la serialización
            'chapters': [chapter.to_dict() for chapter in sorted(self.chapters, key=lambda x: x.chapter_number)]
        }

class Chapter(db.Model):
    __tablename__ = 'chapters'
    
    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    chapter_number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    scope = db.Column(db.Text, nullable=False)
    content = db.Column(db.Text, nullable=False)
    input_tokens = db.Column(db.Integer, default=0)
    output_tokens = db.Column(db.Integer, default=0)
    thinking_tokens = db.Column(db.Integer, default=0)  # Nuevo campo para tokens de pensamiento extendido
    created_at = db.Column(db.DateTime, default=get_utc_now)
    
    def __repr__(self):
        return f'<Chapter {self.chapter_number}: {self.title}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'book_id': self.book_id,
            'chapter_number': self.chapter_number,
            'title': self.title,
            'scope': self.scope,
            'content': self.content,
            'input_tokens': self.input_tokens,
            'output_tokens': self.output_tokens,
            'thinking_tokens': self.thinking_tokens,  # Incluir tokens de pensamiento
            'created_at': self.created_at.isoformat() if self.created_at else None
        }