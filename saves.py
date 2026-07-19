import json
from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from supabase_client import supabase
from auth import login_required, refresh_session_if_needed

saves_bp = Blueprint("saves", __name__)


def get_user_id() -> str:
    return session["user"]["id"]


def get_authed_client():
    """Refresh token if needed, then return a Supabase client scoped to the user."""
    refresh_session_if_needed()
    client = supabase
    client.postgrest.auth(session["access_token"])
    return client


# ── Folder helpers ─────────────────────────────────────────────────────────────


def fetch_folder_tree() -> list:
    """Fetch all folders for the user and build a nested tree."""
    db = get_authed_client()
    result = db.table("folders").select("*").eq("user_id", get_user_id()).order("name").execute()

    folders = result.data
    return build_tree(folders, parent_id=None)


def build_tree(folders: list, parent_id) -> list:
    """Recursively build a nested folder tree."""
    return [
        {**f, "children": build_tree(folders, f["id"])}
        for f in folders
        if f["parent_id"] == parent_id
    ]


# ── Folder routes ──────────────────────────────────────────────────────────────


@saves_bp.route("/folders", methods=["GET"])
@login_required
def get_folders():
    tree = fetch_folder_tree()
    return jsonify(tree)


@saves_bp.route("/folders", methods=["POST"])
@login_required
def create_folder():
    data = request.get_json()
    name = data.get("name", "").strip()
    parent_id = data.get("parent_id")  # None = top-level

    if not name:
        return jsonify({"error": "Folder name is required"}), 400

    db = get_authed_client()
    result = (
        db.table("folders")
        .insert(
            {
                "user_id": get_user_id(),
                "parent_id": parent_id,
                "name": name,
            }
        )
        .execute()
    )

    return jsonify(result.data[0]), 201


@saves_bp.route("/folders/<folder_id>", methods=["PATCH"])
@login_required
def rename_folder(folder_id):
    data = request.get_json()
    name = data.get("name", "").strip()

    if not name:
        return jsonify({"error": "Folder name is required"}), 400

    db = get_authed_client()
    result = (
        db.table("folders")
        .update({"name": name})
        .eq("id", folder_id)
        .eq("user_id", get_user_id())
        .execute()
    )

    return jsonify(result.data[0])


@saves_bp.route("/folders/<folder_id>", methods=["DELETE"])
@login_required
def delete_folder(folder_id):
    db = get_authed_client()
    db.table("folders").delete().eq("id", folder_id).eq("user_id", get_user_id()).execute()

    return jsonify({"deleted": folder_id})


# ── Save routes ────────────────────────────────────────────────────────────────


@saves_bp.route("/saves", methods=["POST"])
@login_required
def create_save():
    data = request.get_json()

    db = get_authed_client()
    result = (
        db.table("saves")
        .insert(
            {
                "user_id": get_user_id(),
                "folder_id": data.get("folder_id"),
                "title": data["title"],
                "url": data["url"],
                "article": data["article"],
                "notes": data["notes"],
                "video_title": data.get("video_title"),
                "video_channel": data.get("video_channel"),
                "thumbnail_url": data.get("thumbnail_url"),
                "duration": data.get("duration"),
            }
        )
        .execute()
    )

    return jsonify(result.data[0]), 201


@saves_bp.route("/saves", methods=["GET"])
@login_required
def list_saves():
    folder_id = request.args.get("folder_id")

    db = get_authed_client()
    query = (
        db.table("saves")
        .select(
            "id, title, url, video_title, video_channel, thumbnail_url, duration, folder_id, created_at"
        )
        .eq("user_id", get_user_id())
        .order("created_at", desc=True)
    )

    if folder_id == "unfiled":
        query = query.is_("folder_id", "null")
    elif folder_id:
        query = query.eq("folder_id", folder_id)

    result = query.execute()
    return jsonify(result.data)


@saves_bp.route("/saves/<save_id>", methods=["GET"])
@login_required
def load_save(save_id):
    db = get_authed_client()
    result = (
        db.table("saves")
        .select("*")
        .eq("id", save_id)
        .eq("user_id", get_user_id())
        .single()
        .execute()
    )

    save = result.data

    import markdown
    from app import build_article_html, build_notes_html

    return render_template(
        "result.html",
        article=build_article_html(save["article"]),
        notes=build_notes_html(save["notes"]),
        article_json=save["article"],
        notes_json=save["notes"],
        video={
            "url": save["url"],
            "title": save.get("video_title", ""),
            "channel": save.get("video_channel", ""),
            "thumbnail": save.get("thumbnail_url", ""),
            "duration": save.get("duration", 0),
        },
        save_id=save_id,
    )


@saves_bp.route("/saves/<save_id>", methods=["PATCH"])
@login_required
def update_save(save_id):
    data = request.get_json()
    updates = {}

    if "title" in data:
        title = data["title"].strip()
        if not title:
            return jsonify({"error": "Title cannot be empty"}), 400
        updates["title"] = title

    if "folder_id" in data:
        updates["folder_id"] = data["folder_id"]  # None = unfiled

    if not updates:
        return jsonify({"error": "Nothing to update"}), 400

    db = get_authed_client()
    result = (
        db.table("saves").update(updates).eq("id", save_id).eq("user_id", get_user_id()).execute()
    )

    return jsonify(result.data[0])


@saves_bp.route("/saves/<save_id>", methods=["DELETE"])
@login_required
def delete_save(save_id):
    db = get_authed_client()
    db.table("saves").delete().eq("id", save_id).eq("user_id", get_user_id()).execute()

    return jsonify({"deleted": save_id})


# ── Library page ───────────────────────────────────────────────────────────────


@saves_bp.route("/library")
@login_required
def library():
    tree = fetch_folder_tree()

    db = get_authed_client()
    result = (
        db.table("saves")
        .select(
            "id, title, url, video_title, video_channel, thumbnail_url, duration, folder_id, created_at"
        )
        .eq("user_id", get_user_id())
        .order("created_at", desc=True)
        .execute()
    )

    saves = result.data
    return render_template("library.html", folder_tree=tree, saves=saves)
