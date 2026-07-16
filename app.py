import os
import markdown
from flask import Flask, render_template, request, session
from dotenv import load_dotenv
from ai_processor import OllamaAIProcessor, GeminiAIProcessor
from yt_api import get_video_data
from auth import auth_bp
from saves import saves_bp

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.register_blueprint(auth_bp)
app.register_blueprint(saves_bp)

processor = GeminiAIProcessor()


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
    """Make current user available in all templates."""
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
            video=video,  # pass the whole object to the template
        )
    except Exception as e:
        return render_template("index.html", error=str(e))


if __name__ == "__main__":
    app.run(debug=True)
