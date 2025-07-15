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

# --- CẤU HÌNH TRANSCODING ---
HLS_ROOT = "/tmp/hls"
WATERMARK_TEXT = "Dung. Media"
FONT_SIZE = 16
CRF_VALUE = "32"                # Tăng lên để giảm tải CPU (32-35 là hợp lý)
PRESET = "ultrafast"            # Preset nhẹ nhất có thể
# !!! THAY ĐỔI QUAN TRỌNG NHẤT ĐỂ CÓ THỂ CHẠY ĐƯỢC !!!
# Bắt đầu với 360p để thử nghiệm. 1080p sẽ không chạy được.
SCALE_RESOLUTION = "640:-2"     # Hạ độ phân giải xuống 360p. Thử "854:-2" cho 480p.

CHANNELS = {
    "skymainevent": "https://7pal.short.gy/SSMEuhd",
    "lamdong": "http://118.107.85.5:1935/live/smil:LTV.smil/playlist.m3u",
    "lovenature": "https://d18dyiwu97wm6q.cloudfront.net/playlist720p.m3u8"
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
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logging.warning(f"FFmpeg for {channel} did not terminate gracefully. Killing.")
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

    user_agent = "ExoPlayerLib/2.15.1"

    # --- LỆNH FFMPEG TRANSCODING (CÁCH 2) ---
    filter_chain = (
        f"scale={SCALE_RESOLUTION},"
        f"drawtext=text='{WATERMARK_TEXT}':"
        f"fontcolor=white@0.6:fontsize={FONT_SIZE}:x=10:y=10"
    )
    
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-user_agent", user_agent,
        "-i", channel_url,
        "-vf", filter_chain,
        "-c:v", "libx264",
        "-preset", PRESET,
        "-crf", CRF_VALUE,
        "-tune", "zerolatency",
        "-threads", "1", # Chỉ dùng 1 thread CPU
        "-c:a", "aac",   # Phải encode lại audio nếu source không phải AAC
        "-b:a", "96k",   # Bitrate audio thấp để giảm tải
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "6",
        "-hls_flags", "delete_segments+program_date_time",
        "-hls_segment_filename", os.path.join(output_dir, "segment_%03d.ts"),
        os.path.join(output_dir, "index.m3u8")
    ]

    logging.warning(f"Starting TRANSCODING for '{channel_name}'. This is CPU-intensive!")
    logging.info(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
    
    # Chạy FFmpeg nền, ghi lại lỗi để debug
    proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    processes[channel_name] = proc

def ensure_stream_is_running(channel):
    """Kiểm tra và khởi động stream nếu cần. Trả về True nếu stream vừa được khởi động."""
    # Kiểm tra xem tiến trình có tồn tại và còn đang chạy không
    if channel not in processes or processes[channel].poll() is not None:
        logging.info(f"Process for '{channel}' not found or has exited. Starting new transcode process.")
        
        # Kill tiến trình cũ (nếu có) trước khi tạo mới
        if channel in processes:
            processes[channel].kill()

        thread = threading.Thread(
            target=start_hls_stream,
            args=(channel, CHANNELS[channel]),
            daemon=True
        )
        thread.start()
        return True # Báo hiệu rằng stream vừa được khởi động
    return False # Báo hiệu stream đã chạy từ trước

@app.route("/stream/<channel>/index.m3u8")
def serve_m3u8(channel):
    """Endpoint chính để player gọi. Sẽ tự khởi động stream nếu cần."""
    if channel not in CHANNELS:
        abort(404, "Kênh không tồn tại")
    
    stream_just_started = ensure_stream_is_running(channel)
    
    output_file = os.path.join(HLS_ROOT, channel, "index.m3u8")

    # Nếu stream vừa được khởi động, ta phải đợi file index.m3u8 được tạo ra
    if stream_just_started:
        timeout = 15  # Tăng timeout vì transcode có thể khởi động chậm
        for i in range(timeout):
            if os.path.exists(output_file):
                logging.info(f"index.m3u8 for {channel} created after {i+1} seconds.")
                break
            # Kiểm tra xem FFmpeg có chết ngay lúc khởi động không
            if processes[channel].poll() is not None:
                error_output = processes[channel].stderr.read().decode('utf-8', errors='ignore')
                logging.error(f"FFmpeg for {channel} exited prematurely. Error: {error_output[-1000:]}")
                abort(503, "Stream process failed to start. Check logs for errors.")
            time.sleep(1)
        else:
            logging.error(f"Timeout waiting for index.m3u8 for channel '{channel}'.")
            abort(503, "Stream timed out on startup.")
            
    # Kiểm tra lại một lần cuối trước khi gửi file
    if not os.path.exists(output_file):
        logging.error(f"File {output_file} not found even after waiting.")
        abort(404)

    return send_from_directory(os.path.join(HLS_ROOT, channel), "index.m3u8")

@app.route("/stream/<channel>/<string:filename>")
def serve_ts_segment(channel, filename):
    """Endpoint này chỉ phục vụ các file .ts"""
    if not filename.endswith('.ts'):
        abort(404)
        
    dir_path = os.path.join(HLS_ROOT, channel)
    if not os.path.exists(os.path.join(dir_path, filename)):
        abort(404)
        
    return send_from_directory(dir_path, filename)


# Giữ lại các trang giao diện để dễ test
@app.route("/")
def index():
    links = "".join([f'<li><a href="/play/{c}">{c.capitalize()}</a></li>' for c in CHANNELS])
    return f"<h1>Kênh có sẵn (chế độ Transcode):</h1><ul>{links}</ul>"

@app.route("/play/<channel>")
def play_video(channel):
    if channel not in CHANNELS:
        abort(404)
    # Giao diện player sử dụng hls.js
    return f"""
    <!DOCTYPE html><html><head><title>Playing: {channel}</title>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <style>body{{font-family:sans-serif;background:#222;color:#eee}}video{{max-width:100%}}</style>
    </head><body><h1>Đang phát: {channel.capitalize()} (Transcoding)</h1>
    <video id="video" width="960" height="540" controls autoplay muted></video>
    <script>
      var video = document.getElementById('video');
      var videoSrc = '/stream/{channel}/index.m3u8';
      if(Hls.isSupported()) {{
        var hls = new Hls();
        hls.loadSource(videoSrc);
        hls.attachMedia(video);
      }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
        video.src = videoSrc;
      }}
    </script></body></html>
    """

@app.route("/healthz")
def health_check():
    return "OK", 200

if __name__ == "__main__":
    if os.path.exists(HLS_ROOT):
        shutil.rmtree(HLS_ROOT)
    os.makedirs(HLS_ROOT, exist_ok=True)
    port = int(os.environ.get("PORT", 5000))
    from waitress import serve
    logging.info(f"Starting server in TRANSCODING mode on 0.0.0.0:{port}")
    serve(app, host="0.0.0.0", port=port, threads=10)
