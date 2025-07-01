from flask import Flask, Response
import subprocess
import os

app = Flask(__name__)

# Logo PNG vuông, nhỏ gọn
LOGO_PATH = "logo.png"

# Danh sách kênh: key là tên, value là URL m3u8 nguồn
CHANNELS = {
    "btvld": "https://64d0d74b76158.streamlock.net/BTVTV/binhthuantv/playlist.m3u8",
    "vtv3": "https://example.com/stream/vtv3.m3u8"
}

def start_ffmpeg_stream(source_url):
    """Chạy ffmpeg restream kèm overlay logo PNG vuông"""
    command = [
        "ffmpeg",
        "-i", source_url,
        "-i", LOGO_PATH,
        "-filter_complex", "overlay=W-w-10:10",  # Logo góc trên phải
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        "-f", "flv", "pipe:1"  # Output ra stdout
    ]
    return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

@app.route("/stream/<channel>")
def stream(channel):
    if channel not in CHANNELS:
        return "Channel not found", 404

    proc = start_ffmpeg_stream(CHANNELS[channel])

    def generate():
        try:
            while True:
                data = proc.stdout.read(4096)
                if not data:
                    break
                yield data
        finally:
            proc.kill()

    return Response(generate(), content_type="video/x-flv")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, threaded=True)
