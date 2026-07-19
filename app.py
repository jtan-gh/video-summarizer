import logging
import os

import markdown
from dotenv import load_dotenv
from flask import Flask, render_template, request, session
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
from auth import auth_bp
from saves import saves_bp
from yt_api import get_video_data

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
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
