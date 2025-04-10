from app import create_app, db
from flask_migrate import upgrade

app = create_app()

@app.cli.command("init-db")
def init_db():
    """Inicializa la base de datos con tablas necesarias."""
    with app.app_context():
        db.create_all()
        print("Base de datos inicializada.")

if __name__ == '__main__':
    app.run(debug=True)