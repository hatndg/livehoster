from flask import Flask, send_from_directory, abort, request
import subprocess
import threading
import os
import shutil
import atexit
import logging
import time

# --- Cấu hình Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# --- CẤU HÌNH ---
HLS_ROOT = "/tmp/hls"
# Giả mạo User-Agent của một trình phát media phổ biến để tránh bị chặn
USER_AGENT = "VLC/3.0.18 (Linux; x86_64)" 
# Bạn có thể đổi sang các User-Agent khác như:
# "ExoPlayerLib/2.15.1"
# "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"

STARTUP_TIMEOUT = 10 # Thời gian chờ (giây) để FFmpeg tạo file m3u8

CHANNELS = {
    "skymainevent": "https://7pal.short.gy/SSMEuhd",
    "lamdong": "http://118.107.85.5:1935/live/smil:LTV.smil/playlist.m3u",
    "lovenature": "https://d18dyiwu97wm6q.cloudfront.net/playlist2160p.m3u8"
}

processes = {}

# --- Dọn dẹp tiến trình khi thoát ---
def cleanup_processes():
    logging.info("Shutting down... Terminating all FFmpeg processes.")
    for channel, proc in list(processes.items()):
        if proc.poll() is None:
            logging.info(f"Killing FFmpeg for channel: {channel} (PID: {proc.pid})")
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
    if os.path.exists(HLS_ROOT):
        shutil.rmtree(HLS_ROOT)

atexit.register(cleanup_processes)

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    return response

def start_hls_stream(channel_name, channel_url):
    output_dir = os.path.join(HLS_ROOT, channel_name)
    os.makedirs(output_dir, exist_ok=True)

    # --- LỆNH FFMPEG SIÊU NHẸ (REMUX/COPY) ---
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        # Thêm header User-Agent để giả dạng trình phát video
        "-user_agent", USER_AGENT,
        "-i", channel_url,
        "-c", "copy",          # Sao chép cả video và audio, không encode lại
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "6",
        "-hls_flags", "delete_segments+program_date_time",
        "-hls_segment_filename", os.path.join(output_dir, "segment_%03d.ts"),
        os.path.join(output_dir, "index.m3u8")
    ]

    logging.info(f"Starting REMUX for '{channel_name}'...")
    logging.info(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
    
    proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    processes[channel_name] = proc

def ensure_stream_is_running(channel):
    """Kiểm tra và khởi động stream nếu cần. Trả về True nếu stream vừa được khởi động."""
    if channel not in processes or processes[channel].poll() is not None:
        logging.info(f"Process for '{channel}' not found or has exited. Starting new process.")
        if channel in processes:
            processes[channel].kill()
        thread = threading.Thread(target=start_hls_stream, args=(channel, CHANNELS[channel]), daemon=True)
        thread.start()
        return True
    return False

@app.route("/stream/<channel>/index.m3u8")
def serve_m3u8(channel):
    if channel not in CHANNELS:
        abort(404, "Kênh không tồn tại")
    
    stream_just_started = ensure_stream_is_running(channel)
    output_file = os.path.join(HLS_ROOT, channel, "index.m3u8")

    if stream_just_started:
        # Chờ một chút vì remux khởi động rất nhanh
        for i in range(STARTUP_TIMEOUT):
            if os.path.exists(output_file):
                break
            if processes[channel].poll() is not None:
                error_output = processes[channel].stderr.read().decode('utf-8', errors='ignore')
                logging.error(f"FFmpeg for {channel} exited prematurely. Error: {error_output[-1000:]}")
                abort(503, "Stream process failed to start. Check source URL or logs.")
            time.sleep(1)
        else:
            logging.error(f"Timeout ({STARTUP_TIMEOUT}s) waiting for index.m3u8 for '{channel}'.")
            abort(503, "Stream timed out on startup.")
            
    if not os.path.exists(output_file):
        abort(404)

    return send_from_directory(os.path.join(HLS_ROOT, channel), "index.m3u8")

@app.route("/stream/<channel>/<string:filename>")
def serve_ts_segment(channel, filename):
    if not filename.endswith('.ts'):
        abort(404, "Invalid file type")
    return send_from_directory(os.path.join(HLS_ROOT, channel), filename)

# --- Giao diện người dùng để dễ test ---
@app.route("/")
def index():
    links = "".join([f'<li><a href="/play/{c}">{c.capitalize()}</a></li>' for c in CHANNELS])
    return f"<h1>Kênh có sẵn (chế độ Copy Stream):</h1><ul>{links}</ul>"

@app.route('/healthz')
def health_check():
    """
    Đây là endpoint để Render kiểm tra "sức khỏe" của ứng dụng.
    """
    try:
        num1 = random.randint(80, 500)
        num2 = random.randint(80, 500)

        addition_result = num1 + num2
        subtraction_result = num1 - num2

        html_output = f"""
        <h1>Máy chủ vẫn khỏe!</h1>
        <p>Số ngẫu nhiên 1: {num1}</p>
        <p>Số ngẫu nhiên 2: {num2}</p>
        <p>Tổng - ({num1} + {num2}) = {addition_result}</p>
        <p>Hiệu - ({num1} - {num2}) = {subtraction_result}</p>
        <p>Tình trạng: Healthy</p>
        """

        # Trả về đối tượng Response, giờ đã hợp lệ vì đã được import
        return Response(html_output, status=200, mimetype='text/html')

    except Exception as e:
        # Xử lý lỗi nếu có
        error_message = f"<h1>Health Check Failed</h1><p>Error: {e}</p>"
        return Response(error_message, status=503, mimetype='text/html')

@app.route("/play/<channel>")
def play_video(channel):
    if channel not in CHANNELS:
        abort(404)
    return f"""
    <!DOCTYPE html><html><head><title>Playing: {channel}</title>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <style>body{{font-family:sans-serif;background:#222;color:#eee;display:grid;place-items:center;height:100vh;margin:0}}video{{max-width:90%;max-height:90%}}</style>
    </head><body>
    <div><h1>Đang phát: {channel.capitalize()}</h1>
    <video id="video" controls autoplay muted></video></div>
    <script>
      var video = document.getElementById('video');
      var videoSrc = '/stream/{channel}/index.m3u8';
      if(Hls.isSupported()) {{
        var hls = new Hls(); hls.loadSource(videoSrc); hls.attachMedia(video);
      }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
        video.src = videoSrc;
      }}
    </script></body></html>
    """

if __name__ == "__main__":
    if os.path.exists(HLS_ROOT):
        shutil.rmtree(HLS_ROOT)
    os.makedirs(HLS_ROOT, exist_ok=True)
    port = int(os.environ.get("PORT", 5000))
    from waitress import serve
    logging.info(f"Starting server in REMUX (Copy Stream) mode on 0.0.0.0:{port}")
    serve(app, host="0.0.0.0", port=port, threads=20)
