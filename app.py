from flask import Flask, send_from_directory, abort
import subprocess
import threading
import os
import shutil

app = Flask(__name__)

HLS_ROOT = "/tmp/hls"  # Thư mục tạm chứa HLS segments

# LƯU Ý QUAN TRỌNG: Bạn vẫn nên tìm link gốc .m3u8 để thay thế vào đây!
CHANNELS = {
    "lamdong": "http://118.107.85.5:1935/live/smil:LTV.smil/playlist.m3u",
    "lovenature": "https://d18dyiwu97wm6q.cloudfront.net/playlist2160p.m3u8"
}

processes = {}

def start_hls_stream(channel_name, channel_url):
    output_dir = os.path.join(HLS_ROOT, channel_name)
    os.makedirs(output_dir, exist_ok=True)

    # Sử dụng User-Agent của ExoPlayer (TiviMate, Televizo...)
    user_agent = "ExoPlayerLib/2.15.1"

    # --- BẮT ĐẦU PHẦN THAY ĐỔI ---
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-user_agent", user_agent,
        "-i", channel_url,
        
        # "-c copy" là chìa khóa!
        # Nó ra lệnh cho ffmpeg sao chép cả luồng video và audio mà không encode lại.
        # CPU sử dụng sẽ gần như bằng 0.
        "-c", "copy",
        
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "6",
        "-hls_flags", "delete_segments",
        "-hls_segment_filename", os.path.join(output_dir, "segment_%03d.ts"),
        os.path.join(output_dir, "index.m3u8")
    ]
    # --- KẾT THÚC PHẦN THAY ĐỔI ---

    # Dừng stream cũ nếu tồn tại
    if channel_name in processes:
        processes[channel_name].kill()

    proc = subprocess.Popen(ffmpeg_cmd)
    processes[channel_name] = proc

# ... Các route còn lại giữ nguyên ...
@app.route("/stream/<channel>/<path:filename>")
def serve_hls_file(channel, filename):
    dir_path = os.path.join(HLS_ROOT, channel)
    if not os.path.exists(os.path.join(dir_path, filename)):
        abort(404)
    return send_from_directory(dir_path, filename)

@app.route("/stream/<channel>")
def stream_index(channel):
    if channel not in CHANNELS:
        return "Kênh không tồn tại", 404
    if channel not in processes or processes[channel].poll() is not None:
        threading.Thread(target=start_hls_stream, args=(channel, CHANNELS[channel]), daemon=True).start()
    return f"""
    <video width="640" height="360" controls autoplay>
      <source src="/stream/{channel}/index.m3u8" type="application/x-mpegURL">
      Trình duyệt của bạn không hỗ trợ HTML5 video.
    </video>
    """

@app.route("/")
def index():
    return "<p>Hello</p>"

@app.route("/healthz")
def health_check():
    return "OK", 200

if __name__ == "__main__":
    if os.path.exists(HLS_ROOT):
        shutil.rmtree(HLS_ROOT)
    os.makedirs(HLS_ROOT, exist_ok=True)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
