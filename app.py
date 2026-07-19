import logging
import os

import markdown
from dotenv import load_dotenv
from flask import Flask, render_template, request, session
from flask_session import Session
from werkzeug.middleware.proxy_fix import ProxyFix

# Load env vars first before anything else reads them
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from ai_processor import GeminiAIProcessor, OllamaAIProcessor, OpenAIAIProcessor
from auth import INACTIVITY_WARNING_OFFSET, STORE_LIFETIME, SUPABASE_INACTIVITY_TIMEOUT, auth_bp
from saves import saves_bp
from yt_api import get_video_data

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Server-side sessions: the browser only ever holds a signed, random session
# id in its cookie - the actual session dict (user info, Supabase tokens,
# last_activity) lives server-side instead. Set REDIS_URL to point this at
# Redis (recommended in production / multi-instance); otherwise it falls
# back to on-disk storage, which is fine for a single instance.
_redis_url = os.environ.get("REDIS_URL")
if _redis_url:
    import redis

    app.config["SESSION_TYPE"] = "redis"
    app.config["SESSION_REDIS"] = redis.from_url(_redis_url)
else:
    session_dir = os.environ.get(
        "SESSION_FILE_DIR", os.path.join(app.instance_path, "flask_session")
    )
    os.makedirs(session_dir, exist_ok=True)
    app.config["SESSION_TYPE"] = "filesystem"
    app.config["SESSION_FILE_DIR"] = session_dir

app.config.update(
    SESSION_PERMANENT=True,  # persistent session cookie
    PERMANENT_SESSION_LIFETIME=STORE_LIFETIME,
    SESSION_USE_SIGNER=True,  # sign the cookie holding the session id, using app.secret_key
    SESSION_KEY_PREFIX="studytool:",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV")
    != "development",  # requires HTTPS outside local dev
)
Session(app)

app.register_blueprint(auth_bp)
app.register_blueprint(saves_bp)

# Select AI provider via AI_PROVIDER env var: "gemini", "openai", or "ollama" (default)
_provider = os.environ.get("AI_PROVIDER", "ollama").lower()
if _provider == "openai":
    processor = OpenAIAIProcessor()
elif _provider == "gemini":
    processor = GeminiAIProcessor()
else:
    processor = OllamaAIProcessor()

logger.info(f"Using AI provider: {_provider}")


def build_article_html(article: dict) -> str:
    lines = [f"# {article['title']}", ""]
    for section in article["sections"]:
        lines.append(f"## {section['heading']}")
        lines.append("")
        lines.append(section["content"])
        lines.append("")
    return markdown.markdown("\n".join(lines), extensions=["extra", "toc"])


def build_notes_html(notes: dict) -> str:
    lines = []
    for topic in notes["topics"]:
        lines.append(f"### {topic['topic']}")
        lines.append("")
        for point in topic["points"]:
            lines.append(f"- {point}")
        lines.append("")
    return markdown.markdown("\n".join(lines), extensions=["extra"])


@app.context_processor
def inject_user():
    return {"current_user": session.get("user")}


@app.context_processor
def inject_session_config():
    return {
        "inactivity_timeout_seconds": int(SUPABASE_INACTIVITY_TIMEOUT.total_seconds()),
        "warning_lead_seconds": int(INACTIVITY_WARNING_OFFSET.total_seconds()),
    }


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    url = request.form.get("url", "").strip()

    if not url:
        return render_template("index.html", error="Please enter a YouTube URL.")

    try:
        video = get_video_data(url)
        output = processor.convert(video.transcript)

        return render_template(
            "result.html",
            article=build_article_html(output.article),
            notes=build_notes_html(output.notes),
            article_json=output.article,
            notes_json=output.notes,
            video=video,
        )

    except Exception as e:
        logger.error(f"Generate error: {e}", exc_info=True)
        return render_template("index.html", error=str(e))


if __name__ == "__main__":
    app.run(debug=True)
