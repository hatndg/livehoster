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
WATERMARK_TEXT = "DemoCDN"
FONT_SIZE = 16
CRF_VALUE = "32"
PRESET = "ultrafast"
SCALE_RESOLUTION = "640:-2" # 360p

# --- CẤU HÌNH TIMEOUT ---
USER_TIMEOUT = 15  # Thời gian chờ cho người dùng thông thường (giây)
API_TIMEOUT = 300  # Thời gian chờ cho API call (5 phút)

CHANNELS = {
    "skymainevent": "https://xem.TruyenHinh.Click/BMT/SkySpMainEv.uk/DoiTac.m3u8",
    "lamdong": "http://118.107.85.5:1935/live/smil:LTV.smil/playlist.m3u",
    "lovenature": "https://d18dyiwu97wm6q.cloudfront.net/playlist2160p.m3u8"
}

processes = {}
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
    """Kiểm tra và khởi động stream nếu cần."""
    if channel not in processes or processes[channel].poll() is not None:
        logging.info(f"Process for '{channel}' not found or has exited. Starting new process.")
        if channel in processes:
            processes[channel].kill()
        thread = threading.Thread(target=start_hls_stream, args=(channel, CHANNELS[channel]), daemon=True)
        thread.start()
        return True
    return False

def wait_for_m3u8(channel, timeout):
    """Hàm chuyên chờ đợi file m3u8 được tạo ra."""
    output_file = os.path.join(HLS_ROOT, channel, "index.m3u8")
    
    for i in range(timeout):
        # Nếu file đã tồn tại, trả về thành công
        if os.path.exists(output_file):
            logging.info(f"index.m3u8 for {channel} is ready after {i+1} second(s).")
            return True
        
        # Nếu tiến trình đã chết, báo lỗi ngay lập tức
        if processes[channel].poll() is not None:
            error_output = processes[channel].stderr.read().decode('utf-8', errors='ignore')
            logging.error(f"FFmpeg for {channel} exited prematurely. Error: {error_output[-1000:]}")
            abort(503, "Stream process failed to start. Check logs.")
        
        # Đợi 1 giây rồi kiểm tra lại
        time.sleep(1)
        
    # Nếu hết thời gian chờ mà file vẫn chưa có, trả về thất bại
    logging.error(f"Timeout ({timeout}s) waiting for index.m3u8 for channel '{channel}'.")
    return False

@app.route("/stream/<channel>/index.m3u8")
def serve_m3u8(channel):
    """
    Endpoint chính, hỗ trợ 2 chế độ:
    - Mặc định: Timeout ngắn cho người dùng.
    - API: Thêm '?wait=true' vào URL để chờ lâu hơn (long polling).
    """
    if channel not in CHANNELS:
        abort(404, "Kênh không tồn tại")
    
    # Kiểm tra xem có phải là API call không
    is_api_call = request.args.get('wait') == 'true'
    timeout = API_TIMEOUT if is_api_call else USER_TIMEOUT
    
    if is_api_call:
        logging.info(f"API request for '{channel}' detected. Using long poll timeout: {timeout}s.")

    # Khởi động stream nếu cần
    stream_just_started = ensure_stream_is_running(channel)
    
    # Nếu stream vừa được bật, ta phải chờ file được tạo ra
    if stream_just_started:
        if not wait_for_m3u8(channel, timeout):
            # Nếu hết thời gian chờ mà vẫn không thành công
            abort(503, "Stream timed out on startup.")
            
    # Gửi file m3u8
    return send_from_directory(os.path.join(HLS_ROOT, channel), "index.m3u8")

# (Các hàm serve_ts_segment, index, play_video, health_check, __main__ giữ nguyên)
@app.route("/stream/<channel>/<string:filename>")
def serve_ts_segment(channel, filename):
    if not filename.endswith('.ts'):
        abort(404)
    dir_path = os.path.join(HLS_ROOT, channel)
    if not os.path.exists(os.path.join(dir_path, filename)):
        abort(404)
    return send_from_directory(dir_path, filename)

@app.route("/")
def index():
    links = "".join([f'<li><a href="/play/{c}">{c.capitalize()}</a></li>' for c in CHANNELS])
    return f"<h1>Kênh có sẵn (chế độ Transcode):</h1><ul>{links}</ul>"

@app.route("/play/<channel>")
def play_video(channel):
    if channel not in CHANNELS:
        abort(404)
    return f"""<!DOCTYPE html><html><head><title>Playing: {channel}</title><script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script><style>body{{font-family:sans-serif;background:#222;color:#eee}}video{{max-width:100%}}</style></head><body><h1>Đang phát: {channel.capitalize()} (Transcoding)</h1><video id="video" width="960" height="540" controls autoplay muted></video><script>var video=document.getElementById('video');var videoSrc='/stream/{channel}/index.m3u8';if(Hls.isSupported()){{var hls=new Hls();hls.loadSource(videoSrc);hls.attachMedia(video);}}else if(video.canPlayType('application/vnd.apple.mpegurl')){{video.src=videoSrc;}}</script></body></html>"""

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
