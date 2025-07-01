from flask import Flask, send_from_directory, abort
import subprocess
import threading
import os
import shutil

app = Flask(__name__)

LOGO_PATH = "logo.png"
HLS_ROOT = "/tmp/hls"  # Thư mục tạm chứa HLS segments

CHANNELS = {
    "btv-lamdong": "https://64d0d74b76158.streamlock.net/BTVTV/binhthuantv/playlist.m3u8",
    "vtv1": "https://cdn-live.vtv.vn/OI8rwFWim2ceXA-cU50x3w/1751376187/live/vtv1/vtv1-720p.m3u8",
    "lamdong": "http://118.107.85.5:1935/live/smil:LTV.smil/playlist.m3u"
}

processes = {}

def start_hls_stream(channel_name, channel_url):
    output_dir = os.path.join(HLS_ROOT, channel_name)
    os.makedirs(output_dir, exist_ok=True)

    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-i", channel_url,
        "-i", LOGO_PATH,
        "-filter_complex", "overlay=10:H-h-10",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-c:a", "aac",
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "8",
        "-hls_flags", "delete_segments",
        "-hls_segment_filename", os.path.join(output_dir, "segment_%03d.ts"),
        os.path.join(output_dir, "index.m3u8")
    ]

    # Dừng stream cũ nếu tồn tại
    if channel_name in processes:
        processes[channel_name].kill()

    # proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Bỏ DEVNULL đi để lỗi được in ra console/log
    proc = subprocess.Popen(ffmpeg_cmd)
    processes[channel_name] = proc

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

    # Bắt đầu HLS stream nếu chưa có
    if channel not in processes or processes[channel].poll() is not None:
        threading.Thread(target=start_hls_stream, args=(channel, CHANNELS[channel]), daemon=True).start()

    # Trả về đường dẫn tới m3u8
    return f"""
    <!--<h3>Đang phát kênh: {channel}</h3>-->
    <video width="640" height="360" controls autoplay>
      <!--<source src="/stream/{channel}/index.m3u8" type="application/x-mpegURL">-->
      Trình duyệt của bạn không hỗ trợ HTML5 video.
    </video>
    """

@app.route("/")
def index():
    links = "".join(f"<p>It works!</p>" for name in CHANNELS)
    return f"<p>Hello</p>"

@app.route("/healthz")
def health_check():
    return "OK", 200

if __name__ == "__main__":
    if os.path.exists(HLS_ROOT):
        shutil.rmtree(HLS_ROOT)
    os.makedirs(HLS_ROOT, exist_ok=True)

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
