from flask import Flask, send_from_directory, abort, request
import subprocess
import threading
import os
import shutil

app = Flask(__name__)

HLS_ROOT = "/tmp/hls"           # Thư mục tạm cho HLS
WATERMARK_TEXT = "DemoCDN"      # Nội dung watermark
FONT_SIZE = 18                  # Cỡ chữ
CRF_VALUE = "30"                # Chất lượng (cao số = nhẹ)
PRESET = "ultrafast"            # Rất nhẹ (độ nén kém hơn veryfast)

CHANNELS = {
    "skymainevent": "https://xem.TruyenHinh.Click/BMT/SkySpMainEv.uk/DoiTac.m3u8",
    "lamdong": "http://118.107.85.5:1935/live/smil:LTV.smil/playlist.m3u",
    "lovenature": "https://d18dyiwu97wm6q.cloudfront.net/playlist2160p.m3u8"
}

processes = {}


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

    # ---------------- FILTER WATERMARK CỰC NHẸ -----------------
    # Nếu muốn hạ độ phân giải input (giảm tải), bỏ dấu # dòng scale.
    # filter_chain = "scale=640:-2,drawtext=..."   # hạ về 640p
    filter_chain = (
        f"drawtext=text='{WATERMARK_TEXT}':"
        f"fontcolor=white@0.6:fontsize={FONT_SIZE}:"
        "x=10:y=10"
    )
    # -----------------------------------------------------------

    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-user_agent", user_agent,
        "-i", channel_url,
        "-vf", filter_chain,
        "-c:v", "libx264",
        "-preset", PRESET,
        "-crf", CRF_VALUE,
        "-c:a", "copy",
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "6",
        "-hls_flags", "delete_segments",
        "-hls_segment_filename", os.path.join(output_dir, "segment_%03d.ts"),
        os.path.join(output_dir, "index.m3u8")
    ]

    # Nếu channel đã chạy, kill cũ
    if channel_name in processes:
        processes[channel_name].kill()

    # Chạy FFmpeg nền
    proc = subprocess.Popen(ffmpeg_cmd)
    processes[channel_name] = proc


@app.route("/stream/<channel>/<path:filename>")
def serve_hls_file(channel, filename):
    print(f"[*] Request {request.remote_addr} -> {request.path}")
    dir_path = os.path.join(HLS_ROOT, channel)
    if not os.path.exists(os.path.join(dir_path, filename)):
        abort(404)
    return send_from_directory(dir_path, filename)


@app.route("/stream/<channel>")
def stream_index(channel):
    if channel not in CHANNELS:
        return "Kênh không tồn tại", 404
    # Khởi động FFmpeg nếu chưa có
    if channel not in processes or processes[channel].poll() is not None:
        threading.Thread(
            target=start_hls_stream,
            args=(channel, CHANNELS[channel]),
            daemon=True
        ).start()
    return f"""
    <video width="640" height="360" controls autoplay>
      <source src="/stream/{channel}/index.m3u8" type="application/x-mpegURL">
      Trình duyệt của bạn không hỗ trợ HTML5 video.
    </video>
    """


@app.route("/")
def index():
    return "<p>Đây là CDN phát sóng. Vui lòng liên hệ nếu bạn muốn thuê truyền dẫn!</p>"


@app.route("/healthz")
def health_check():
    return "OK", 200


if __name__ == "__main__":
    if os.path.exists(HLS_ROOT):
        shutil.rmtree(HLS_ROOT)
    os.makedirs(HLS_ROOT, exist_ok=True)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
