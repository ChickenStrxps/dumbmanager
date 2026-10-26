"""Explicit chat uploads. Temporary bytes only, fixed T3 API, bounded video sampling."""
import base64
import http.client
import json
import mimetypes
import re
import shutil
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from .common import APIError
from .t3 import T3, rpc

MAX_UPLOAD = 50 * 1024 * 1024
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def frameboard(source, folder, root):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise APIError("Video frameboards need FFmpeg and FFprobe. Images and files still work.", "unavailable", 503)
    options = dict(capture_output=True, timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), cwd=folder)
    try:
        probe = subprocess.run([ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries", "format=duration",
                                "-of", "json", str(source)], **options)
        duration = float(json.loads(probe.stdout)["format"]["duration"])
        if not .1 <= duration <= 120:
            raise APIError("For a lightweight frameboard, trim the clip to 0.1–120 seconds. Or choose Original file.")
        font = Path(root).parent / "dumbmanager/web/fonts/IBMPlexMono.ttf"
        if not font.is_file():
            raise APIError("The bundled timestamp font is missing. Restore DumbManager's fonts.", "unavailable", 503)
        shutil.copyfile(font, folder / "font.ttf")
        out = folder / "frameboard.jpg"
        # Timestamp before tiling. One process, one 1440x810 board, no audio.
        filters = (f"fps={9/duration:.8f}:round=up,scale=480:270:force_original_aspect_ratio=decrease,"
                   "pad=480:270:(ow-iw)/2:(oh-ih)/2:color=0x131411,setsar=1,"
                   "drawtext=fontfile=font.ttf:text='%{pts\\:hms}':x=8:y=h-th-8:fontsize=17:fontcolor=white:box=1:boxcolor=black@0.8,"
                   "tile=3x3:nb_frames=9:padding=6:margin=6:color=0x131411")
        result = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-protocol_whitelist", "file,pipe",
                                 "-threads", "1", "-i", str(source), "-an", "-vf", filters,
                                 "-frames:v", "1", "-q:v", "4", "-threads", "1", str(out)], **options)
        if result.returncode or not out.is_file() or not 0 < out.stat().st_size <= 2*1024*1024:
            raise ValueError()
        return out, duration
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        raise APIError("Could not make a frameboard from this clip. Try a short MP4/WebM, or attach the original file.", "video_unavailable", 422) from None


def upload(config, stream, size, name, mime, video_mode="frameboard"):
    """Called by the authenticated host with request bytes, never a user path."""
    if not 0 < size <= MAX_UPLOAD:
        raise APIError("Attach a nonempty file up to 50 MiB.", "too_large", 413)
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", name).strip()[:220] or "attachment"
    mime = mime.lower().split(";", 1)[0].strip()
    if not re.fullmatch(r"[\w.+-]+/[\w.+-]+", mime):
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    if mime in IMAGE_TYPES and size > 10*1024*1024:
        raise APIError("T3 images must be at most 10 MiB. Resize the image first.", "too_large", 413)
    if video_mode not in ("frameboard", "original"):
        raise APIError("Choose frameboard or original video mode.")
    connection = T3(config).connection()
    temporary = config.data / "upload-temp"
    temporary.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="chat-", dir=temporary) as folder_name:
        folder = Path(folder_name)
        source = folder / ("input" + Path(name).suffix[:12])
        with source.open("wb") as output:
            remaining = size
            while remaining:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    raise APIError("The upload was interrupted. Pick the file again.")
                output.write(chunk); remaining -= len(chunk)
        note, thumbnail = "", None
        if mime.startswith("video/") and video_mode == "frameboard":
            source, duration = frameboard(source, folder, config.root)
            name = Path(name).stem[:150] + f"-frameboard-{duration:.1f}s-no-audio.jpg"
            size, mime = source.stat().st_size, "image/jpeg"
            note = f"9 sampled frames across {duration:.1f}s · timestamps · no audio. Original video is not sent."
            thumbnail = base64.b64encode(source.read_bytes()).decode("ascii")
        elif mime.startswith("video/"):
            note = "Original video file · native video understanding depends on the selected T3 provider."
        kind = "image" if mime in IMAGE_TYPES else "file"
        try:
            issued = rpc(connection, "attachments.createUploadUrl", {"type": kind, "name": name, "mimeType": mime, "sizeBytes": size})
            route, identifier = issued.get("relativeUrl", ""), issued.get("attachmentId", "")
            if not re.fullmatch(r"/api/attachments/upload/[A-Za-z0-9_.-]{1,4096}", route) or not re.fullmatch(r"[\w-]{1,128}", identifier):
                raise ValueError()
            url = urlsplit(connection["url"])
            with source.open("rb") as data, closing(http.client.HTTPConnection(url.hostname, url.port, timeout=30)) as client:
                client.request("POST", route, data, {"Content-Type": mime, "Content-Length": str(size)})
                response = client.getresponse()
                response.read(16384)
                if not 200 <= response.status < 300:
                    raise ValueError()
            return {"attachment": {"id": identifier, "type": kind, "name": name, "mimeType": mime, "sizeBytes": size},
                    "note": note, "thumbnail": thumbnail}
        except (OSError, ValueError, http.client.HTTPException):
            raise APIError("T3 could not accept this file. Your message is kept; retry the upload.", "t3_unavailable", 503) from None
