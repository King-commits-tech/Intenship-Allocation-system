"""Entry point: ``python run.py`` or ``flask --app run run``."""
import os

from app import create_app

app = create_app(os.environ.get("FLASK_CONFIG", "development"))

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 5000))
    app.run(host=host, port=port, debug=app.config.get("DEBUG", False))
