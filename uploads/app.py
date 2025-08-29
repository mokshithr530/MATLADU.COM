import os
import random
import string
import json
import gzip
import base64
import requests
from flask import Flask, request, send_from_directory, jsonify
from flask_socketio import SocketIO, join_room, leave_room, emit
from flask_compress import Compress
from werkzeug.utils import secure_filename

print("starting server...")

# --- App & Socket.IO setup (single app instance) ---
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__, static_folder='.', static_url_path='')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ultra-low bandwidth optimizations
app.config['COMPRESS_MIMETYPES'] = [
    'text/html', 'text/css', 'text/javascript', 'application/javascript',
    'application/json', 'text/plain', 'image/svg+xml'
]
app.config['COMPRESS_LEVEL'] = 9
app.config['COMPRESS_BR_LEVEL'] = 11
app.config['COMPRESS_MIN_SIZE'] = 100
app.config['COMPRESS_ALGORITHM'] = ['br', 'gzip']

compress = Compress()
compress.init_app(app)

socketio = SocketIO(
    app,
    cors_allowed_origins='*',
    async_mode='eventlet',
    ping_timeout=60,
    ping_interval=25
)

# --- Data stores ---
servers = {}         # code -> {'name': str, 'users': set(), 'history': list[dict]}
user_sid_map = {}    # sid  -> (username, code)

# --- Helpers ---
def random_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def compress_message(msg: dict) -> str:
    msg_str = json.dumps(msg, separators=(',', ':'))
    compressed = gzip.compress(msg_str.encode('utf-8'), compresslevel=9)
    return base64.b64encode(compressed).decode('utf-8')

# --- Routes (serve static html/css/js) ---
@app.route('/')
def root():
    return send_from_directory('.', 'intro.html')

@app.route('/chat.html')
def chat_page():
    return send_from_directory('.', 'chat.html')

@app.route('/style.css')
def style_css():
    return send_from_directory('.', 'style.css')

@app.route('/script.js')
def script_js():
    return send_from_directory('.', 'script.js')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/search-gifs')
def search_gifs():
    GIPHY_API_KEY = "lxXvLdVLd40HUmaM1sY0C8Aq9LuSArj6"
    GIPHY_BASE_URL = "https://api.giphy.com/v1/gifs"
    query = request.args.get('q', '')
    limit = request.args.get('limit', '10')

    if not query:
        return jsonify({'error': 'No search query provided'}), 400

    try:
        url = f"{GIPHY_BASE_URL}/search"
        params = {
            'api_key': GIPHY_API_KEY,
            'q': query,
            'limit': limit,
            'rating': 'g',
            'lang': 'en'
        }
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        gifs = []
        for gif in data.get('data', []):
            gifs.append({
                'id': gif['id'],
                'title': gif['title'],
                'url': gif['images']['fixed_height']['url'],
                'preview_url': gif['images']['fixed_height_small']['url'],
                'width': gif['images']['fixed_height']['width'],
                'height': gif['images']['fixed_height']['height']
            })
        return jsonify({'gifs': gifs})
    except requests.RequestException as e:
        return jsonify({'error': f'Failed to fetch GIFs: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500

# --- File upload ---
@app.route('/upload', methods=['POST'])
def upload_file():
    username = request.form['username']
    server_id = (request.form['server_id'] or '').upper()
    f = request.files['file']
    fname = secure_filename(f.filename)

    MAX_FILE_SIZE = 2 * 1024 * 1024
    if request.content_length and request.content_length > MAX_FILE_SIZE:
        return jsonify({'error': 'File too large. Max 2MB for low bandwidth.'}), 413

    file_ext = os.path.splitext(fname)[1].lower()
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], fname)

    if file_ext in ('.jpg', '.jpeg', '.png', '.gif'):
        try:
            from PIL import Image
            img = Image.open(f)
            if file_ext == '.gif':
                max_size = (400, 300)
                if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
                    img.thumbnail(max_size)
                img.save(save_path, optimize=True, save_all=True)
            else:
                max_size = (800, 600)
                if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
                    img.thumbnail(max_size)
                img.save(save_path, optimize=True, quality=60)
        except Exception:
            f.stream.seek(0)
            f.save(save_path)
    else:
        f.save(save_path)

    msg = {
        'msg_id': random_code(8),
        'username': username,
        'file_url': '/uploads/' + fname,
        'file_name': fname
    }

    if server_id in servers:
        servers[server_id]['history'].append(msg)
        socketio.emit('chat_message', msg, room=server_id)

    return '', 204

# --- Socket.IO events ---
@socketio.on('create_server')
def on_create_server(data):
    username = (data or {}).get('username') or 'Anonymous'
    server_name = (data or {}).get('server_name') or 'New Server'

    code = random_code(6)
    servers[code] = {
        'name': server_name,
        'users': set(),
        'history': []
    }

    join_room(code)
    servers[code]['users'].add(username)
    user_sid_map[request.sid] = (username, code)

    emit('joined_server', {
        'server_id': code,
        'server_name': server_name,
        'history': servers[code]['history'],
        'users_online': list(servers[code]['users'])
    }, room=request.sid)

    emit('user_list', list(servers[code]['users']), room=code)

@socketio.on('join_server')
def on_join_server(data):
    username = (data or {}).get('username') or 'Anonymous'
    code = ((data or {}).get('server_id') or '').upper()

    if code not in servers:
        emit('server_error', {'error': 'Server not found.'}, room=request.sid)
        return

    join_room(code)
    servers[code]['users'].add(username)
    user_sid_map[request.sid] = (username, code)

    emit('joined_server', {
        'server_id': code,
        'server_name': servers[code]['name'],
        'history': servers[code]['history'],
        'users_online': list(servers[code]['users'])
    }, room=request.sid)

    emit('user_list', list(servers[code]['users']), room=code)

@socketio.on('chat_message')
def handle_chat(data):
    username = data.get('username')
    code = (data.get('server_id') or '').upper()
    msgtxt = data.get('text')
    reply_to = data.get('reply_to')
    msg_type = data.get('type')

    if not code or code not in servers:
        emit('server_error', {'error': 'Invalid server or not connected.'}, room=request.sid)
        return

    if msg_type == 'gif':
        reply_preview = ''
        if reply_to:
            for m in servers[code]['history']:
                if m['msg_id'] == reply_to:
                    reply_preview = m.get('text') or m.get('file_name') or m.get('gif_title', '')
                    if len(reply_preview) > 50:
                        reply_preview = reply_preview[:50] + '...'
                    break

        msg = {
            'msg_id': random_code(8),
            'username': username,
            'type': 'gif',
            'content': data.get('content'),
            'gif_title': data.get('gif_title', ''),
            'reply_to': reply_to,
            'reply_preview': reply_preview
        }
        servers[code]['history'].append(msg)
        emit('chat_message', msg, room=code)
        return

    if msgtxt:
        if len(msgtxt) > 500:
            msgtxt = msgtxt[:500] + "..."

        reply_preview = ''
        if reply_to:
            for m in servers[code]['history']:
                if m['msg_id'] == reply_to:
                    reply_preview = m.get('text') or m.get('file_name', '') or m.get('gif_title', '')
                    if len(reply_preview) > 50:
                        reply_preview = reply_preview[:50] + "..."
                    break

        msg = {
            'msg_id': random_code(8),
            'username': username,
            'text': msgtxt,
            'reply_to': reply_to,
            'reply_preview': reply_preview
        }
        servers[code]['history'].append(msg)
        emit('chat_message', msg, room=code)

@socketio.on('disconnect')
def on_disconnect():
    info = user_sid_map.pop(request.sid, None)
    if not info:
        return
    username, code = info
    if code in servers and username in servers[code]['users']:
        servers[code]['users'].remove(username)
        emit('user_list', list(servers[code]['users']), room=code)

if __name__ == "__main__":
    print("✅ Server started on http://127.0.0.1:5000")
    socketio.run(app, host='127.0.0.1', port=5000)
