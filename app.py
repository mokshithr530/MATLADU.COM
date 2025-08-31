import os
import random
import string
from flask import Flask, render_template, request, send_from_directory, jsonify
from flask_socketio import SocketIO, emit, join_room
from werkzeug.utils import secure_filename

# ---------- App setup ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

socketio = SocketIO(app, cors_allowed_origins="*")

# In-memory store: code -> {'name': str, 'users': set(), 'history': list[dict]}
servers = {}
# sid -> (username, server_code)
user_sid_map = {}

def random_code(n=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))

# ---------- Routes ----------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat")
def chat():
    return render_template("chat.html")

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/upload", methods=["POST"])
def upload(): 
    username = request.form.get("username", "Anonymous")
    server_id = (request.form.get("server_id") or "").upper()
    f = request.files.get("file")
    if not f or not server_id or server_id not in servers:
        return jsonify({"error": "Invalid upload"}), 400

    fname = secure_filename(f.filename or "file")
    save_path = os.path.join(app.config["UPLOAD_FOLDER"], fname)
    f.save(save_path)

    # Broadcast file message
    msg = {
        "msg_id": random_code(8),
        "username": username,
        "file_url": f"/uploads/{fname}",
        "file_name": fname,
        "type": "file",
    }
    servers[server_id]["history"].append(msg)
    socketio.emit("chat_message", msg, room=server_id)
    return "", 204

# ---------- Socket.IO events ----------
@socketio.on("create_server")
def on_create_server(data):
    username = (data or {}).get("username") or "Anonymous"
    server_name = (data or {}).get("server_name") or "New Server"

    code = random_code(6)
    servers[code] = {"name": server_name, "users": set(), "history": []}

    join_room(code)
    servers[code]["users"].add(username)
    user_sid_map[request.sid] = (username, code)

    emit("joined_server", {
        "server_id": code,
        "server_name": server_name,
        "history": servers[code]["history"],
        "users_online": sorted(list(servers[code]["users"]))
    }, room=request.sid)

    emit("user_list", sorted(list(servers[code]["users"])), room=code)

@socketio.on("join_server")
def on_join_server(data):
    username = (data or {}).get("username") or "Anonymous"
    code = ((data or {}).get("server_id") or "").upper()

    if code not in servers:
        emit("server_error", {"error": "Server not found."}, room=request.sid)
        return

    join_room(code)
    servers[code]["users"].add(username)
    user_sid_map[request.sid] = (username, code)

    emit("joined_server", {
        "server_id": code,
        "server_name": servers[code]["name"],
        "history": servers[code]["history"],
        "users_online": sorted(list(servers[code]["users"]))
    }, room=request.sid)

    emit("user_list", sorted(list(servers[code]["users"])), room=code)

@socketio.on("chat_message")
def on_chat_message(data):
    username = (data or {}).get("username") or "Anonymous"
    code = ((data or {}).get("server_id") or "").upper()
    text = (data or {}).get("text") or ""
    reply_to = (data or {}).get("reply_to")

    if not code or code not in servers:
        emit("server_error", {"error": "Invalid server or not connected."}, room=request.sid)
        return
    if not text.strip():
        return

    # Build reply preview if needed
    reply_preview = ""
    if reply_to:
        for m in servers[code]["history"]:
            if m.get("msg_id") == reply_to:
                reply_preview = m.get("text") or m.get("file_name") or ""
                if len(reply_preview) > 60:
                    reply_preview = reply_preview[:60] + "…"
                break

    msg = {
        "msg_id": random_code(8),
        "username": username,
        "text": text[:500] if len(text) > 500 else text,
        "reply_to": reply_to,
        "reply_preview": reply_preview,
        "type": "text",
    }
    servers[code]["history"].append(msg)
    emit("chat_message", msg, room=code)

@socketio.on("disconnect")
def on_disconnect():
    info = user_sid_map.pop(request.sid, None)
    if not info:
        return
    username, code = info
    if code in servers and username in servers[code]["users"]:
        servers[code]["users"].remove(username)
        emit("user_list", sorted(list(servers[code]["users"])), room=code)

# ---------- Main ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # use Render's port if set
    print(f"✅ Server starting on port {port}...")
    socketio.run(app, host="0.0.0.0", port=port)
