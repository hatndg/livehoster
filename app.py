from flask import Flask, send_from_directory, abort
import subprocess
import threading
import os
import shutil

app = Flask(__name__)

LOGO_PATH = "logo.png"
HLS_ROOT = "/tmp/hls"  # Thư mục tạm chứa HLS segments

CHANNELS = {
    "test": "https://7pal.short.gy/nowhkp1"
}

processes = {}

def start_hls_stream(channel_name, channel_url):
    output_dir = os.path.join(HLS_ROOT, channel_name)
    os.makedirs(output_dir, exist_ok=True)

    # --- BẮT ĐẦU PHẦN THAY ĐỔI ---
    # MỚI: Thêm bộ lọc 'scale=-1:720' để resize video.
    # GIẢI THÍCH:
    # [0:v]scale=-1:720[scaled] -> Lấy luồng video đầu vào ([0:v]), resize nó về chiều cao 720px.
    #                                Chiều rộng (-1) sẽ được tự động tính toán để giữ đúng tỉ lệ khung hình.
    #                                Đặt tên cho luồng đã resize là [scaled].
    # [scaled][1:v]overlay=... -> Lấy luồng [scaled] và luồng logo ([1:v]) để thực hiện chèn logo.
    video_filter = "[0:v]scale=-1:720[scaled]; [scaled][1:v]overlay=10:H-h-10"
    # --- KẾT THÚC PHẦN THAY ĐỔI ---


    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-i", channel_url,
        "-i", LOGO_PATH,
        "-filter_complex", video_filter, # SỬ DỤNG BIẾN LỌC MỚI Ở ĐÂY
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
