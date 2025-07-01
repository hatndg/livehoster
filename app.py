from flask import Flask, request, redirect, url_for, render_template, session, send_from_directory, abort, jsonify
import subprocess, threading, time, os, shutil, json, psutil
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "secret"
HLS_ROOT = "streams"
LOGO_PATH = "logo.png"

CHANNEL_FILE = "channels.json"
USER_FILE = "users.json"

def load_channels():
    if os.path.exists(CHANNEL_FILE):
        with open(CHANNEL_FILE) as f:
            return json.load(f)
    return {}

def save_channels(channels):
    with open(CHANNEL_FILE, "w") as f:
        json.dump(channels, f)

def load_users():
    if os.path.exists(USER_FILE):
        with open(USER_FILE) as f:
            return json.load(f)
    return {"admin": generate_password_hash("Admin@123")}

def save_users(users):
    with open(USER_FILE, "w") as f:
        json.dump(users, f)

channels = load_channels()
users = load_users()
ffmpeg_procs = {}

def cleanup_stream(channel):
    path = os.path.join(HLS_ROOT, channel)
    if os.path.exists(path): shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)

def start_stream(channel, url):
    cleanup_stream(channel)
    path = os.path.join(HLS_ROOT, channel)
    cmd = [
        "ffmpeg", "-i", url, "-i", LOGO_PATH,
        "-filter_complex", "overlay=W-w-10:10",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-c:a", "aac", "-f", "hls", "-hls_time", "4", "-hls_list_size", "6",
        "-hls_flags", "delete_segments", os.path.join(path, "index.m3u8")
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ffmpeg_procs[channel] = proc
    threading.Thread(target=lambda: (proc.wait(), cleanup_stream(channel)), daemon=True).start()

@app.route("/health")
def health(): return "OK", 200

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u, p = request.form["username"], request.form["password"]
        if u in users and check_password_hash(users[u], p):
            session["user"] = u
            return redirect("/dashboard")
        return render_template("login.html", error="Sai thông tin")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")

@app.route("/change-password", methods=["GET", "POST"])
def change_password():
    if "user" not in session: return redirect("/")
    if request.method == "POST":
        old, new = request.form["old"], request.form["new"]
        if check_password_hash(users[session["user"]], old):
            users[session["user"]] = generate_password_hash(new)
            save_users(users)
            return redirect("/dashboard")
        return render_template("change_password.html", error="Sai mật khẩu cũ")
    return render_template("change_password.html")

@app.route("/dashboard")
def dashboard():
    if "user" not in session: return redirect("/")
    return render_template("dashboard.html", channels=channels)

@app.route("/add-stream", methods=["POST"])
def add_stream():
    if "user" not in session: return redirect("/")
    name, url = request.form["name"], request.form["url"]
    channels[name] = url
    save_channels(channels)
    start_stream(name, url)
    return redirect("/dashboard")

@app.route("/delete-stream/<channel>")
def delete_stream(channel):
    if "user" not in session: return redirect("/")
    if channel in channels:
        if channel in ffmpeg_procs:
            ffmpeg_procs[channel].kill()
        cleanup_stream(channel)
        channels.pop(channel)
        save_channels(channels)
    return redirect("/dashboard")

@app.route("/restart-stream/<channel>")
def restart_stream(channel):
    if "user" not in session: return redirect("/")
    if channel in channels:
        if channel in ffmpeg_procs:
            ffmpeg_procs[channel].kill()
        start_stream(channel, channels[channel])
    return redirect("/dashboard")

@app.route("/cpu-ram")
def cpu_ram():
    return jsonify({
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent
    })

@app.route("/hls/<channel>/<path:filename>")
def hls_stream(channel, filename):
    path = os.path.join(HLS_ROOT, channel)
    if os.path.exists(os.path.join(path, filename)):
        return send_from_directory(path, filename)
    return abort(404)

if __name__ == "__main__":
    os.makedirs(HLS_ROOT, exist_ok=True)
    save_users(users)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
