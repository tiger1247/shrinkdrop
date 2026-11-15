"""ShrinkDrop engine: HEIC -> JPG, photo shrinking and video shrinking. No UI code here."""
import json
import os
import shutil
import sys
import tempfile
import time

APP_NAME = "ShrinkDrop"
APP_ID = "ShrinkDrop"


def is_packaged():
    """True when running from the MSIX (Microsoft Store) package."""
    import ctypes
    length = ctypes.c_uint32(0)
    try:
        return ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None) != 15700
    except (AttributeError, OSError):
        return False


PACKAGED = is_packaged()
DIRECT = os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "DIRECT_EDITION"))
APPDATA_DIR = os.environ.get("SD_DATA_DIR") or os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_ID)
CONFIG_PATH = os.path.join(APPDATA_DIR, "config.json")
TEMP_DIR = os.path.join(tempfile.gettempdir(), APP_ID)

PHOTO_EXT = {".heic", ".heif", ".hif", ".avif", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
HEIF_EXT = {".heic", ".heif", ".hif", ".avif"}
VIDEO_EXT = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".wmv", ".webm", ".3gp", ".mts", ".m2ts"}

# ---- settings ----------------------------------------------------------------
DEFAULTS = {
    "photo_size": 0,          # longest edge in px; 0 = keep original size
    "photo_quality": 85,      # JPEG quality
    "photo_format": "jpg",    # "jpg" or "keep" (shrink in the original format where possible)
    "video_mode": "mb",       # "mb" = target size, "quality" = good quality, smaller file
    "video_mb": 25,
    "video_height": 1080,     # max height; 0 = keep
    "keep_dates": True,
    "out_mode": "same",       # "same" = next to the original, "folder" = out_dir
    "out_dir": "",
}


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            s.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    os.makedirs(APPDATA_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, CONFIG_PATH)


# ---- helpers -----------------------------------------------------------------
def kind_of(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in PHOTO_EXT:
        return "photo"
    if ext in VIDEO_EXT:
        return "video"
    return None


def expand(paths):
    """Files and folders -> list of supported files (folders are searched recursively)."""
    out, seen = [], set()
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d != "ShrinkDrop"]
                for f in sorted(files):
                    fp = os.path.join(root, f)
                    if kind_of(fp) and fp not in seen:
                        seen.add(fp)
                        out.append(fp)
        elif os.path.isfile(p) and kind_of(p) and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def human(n):
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


def output_path(src, new_ext, settings, tag=" (small)"):
    folder = os.path.dirname(src)
    if settings.get("out_mode") == "folder" and settings.get("out_dir"):
        folder = settings["out_dir"]
    elif os.path.normcase(folder).startswith(os.path.normcase(TEMP_DIR)):
        # Shared from an app like Photos: the "original" is our temp copy, so save somewhere findable.
        folder = os.path.join(os.path.expanduser("~"), "Pictures", "ShrinkDrop")
    os.makedirs(folder, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src))[0]
    same_folder = os.path.normcase(folder) == os.path.normcase(os.path.dirname(src))
    heic_to_jpg = new_ext == ".jpg" and os.path.splitext(src)[1].lower() in HEIF_EXT
    # Next to the original: IMG_1.HEIC -> IMG_1.jpg, but IMG_1.MOV -> IMG_1 (small).mp4.
    name = stem + (tag if same_folder and not heic_to_jpg else "") + new_ext
    return unique_path(os.path.join(folder, name))


def copy_dates(src, dst):
    st = os.stat(src)
    os.utime(dst, (st.st_atime, st.st_mtime))


class Cancelled(Exception):
    pass


# ---- photos ------------------------------------------------------------------
_heif_ready = False


def _ensure_heif():
    global _heif_ready
    if not _heif_ready:
        import pillow_heif
        pillow_heif.register_heif_opener()
        _heif_ready = True


def shrink_photo(src, settings, progress=None):
    """Returns the output path."""
    from PIL import Image, ImageOps
    _ensure_heif()
    ext = os.path.splitext(src)[1].lower()
    with Image.open(src) as im:
        exif = im.info.get("exif")
        icc = im.info.get("icc_profile")
        im.load()
        if ext not in HEIF_EXT:  # HEIF decoders already apply rotation
            im = ImageOps.exif_transpose(im)
        limit = int(settings.get("photo_size") or 0)
        if limit and max(im.size) > limit:
            im.thumbnail((limit, limit), Image.LANCZOS)

        keep = settings.get("photo_format") == "keep" and ext in (".png", ".webp", ".jpg", ".jpeg")
        if keep and ext == ".png":
            out_ext, fmt = ".png", "PNG"
        elif keep and ext == ".webp":
            out_ext, fmt = ".webp", "WEBP"
        else:
            out_ext, fmt = ".jpg", "JPEG"

        if fmt == "JPEG" and im.mode not in ("RGB", "L"):
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.getchannel("A"))
                im = bg
            else:
                im = im.convert("RGB")

        dst = output_path(src, out_ext, settings)
        kw = {}
        if exif:
            try:  # orientation is now baked into the pixels
                ex = Image.Exif()
                ex.load(exif)
                ex[0x0112] = 1
                kw["exif"] = ex.tobytes()
            except Exception:
                kw["exif"] = exif
        if icc:
            kw["icc_profile"] = icc
        tmp = dst + ".part"
        if fmt == "JPEG":
            im.save(tmp, "JPEG", quality=int(settings.get("photo_quality", 85)), optimize=True,
                    progressive=True, subsampling="4:2:0", **kw)
        elif fmt == "PNG":
            im.save(tmp, "PNG", optimize=True, **{k: v for k, v in kw.items() if k == "icc_profile"})
        else:
            im.save(tmp, "WEBP", quality=int(settings.get("photo_quality", 85)), method=5, **kw)
    os.replace(tmp, dst)
    if settings.get("keep_dates", True):
        copy_dates(src, dst)
    if progress:
        progress(1.0)
    return dst


# ---- videos ------------------------------------------------------------------
AUDIO_KBPS = 96


def probe_video(src):
    import av
    with av.open(src) as c:
        v = next((s for s in c.streams.video), None)
        a = next((s for s in c.streams.audio), None)
        dur = float(c.duration) / 1e6 if c.duration else None
        if not dur and v is not None and v.duration and v.time_base:
            dur = float(v.duration * v.time_base)
        info = {"duration": dur or 0.0, "has_audio": a is not None}
        if v is not None:
            info.update(width=v.codec_context.width, height=v.codec_context.height,
                        fps=float(v.average_rate or v.guessed_rate or 30))
            rot = 0
            try:  # iPhone videos are often stored sideways with a rotation flag
                for fr in c.decode(video=0):
                    rot = int(getattr(fr, "rotation", 0) or 0)
                    break
            except Exception:
                pass
            info["rotation"] = rot
        return info


def _plan(info, settings):
    """Pick output size and bitrate. Returns (width, height, video_kbps or None, crf or None)."""
    w, h = info.get("width", 1920), info.get("height", 1080)
    rot = abs(info.get("rotation", 0)) % 180 == 90
    if rot:
        w, h = h, w
    short_cap = int(settings.get("video_height") or 0)  # cap the shorter side, so portrait works too
    kbps = crf = None
    if settings.get("video_mode") == "mb":
        dur = max(info.get("duration") or 1.0, 0.5)
        total_kbit = float(settings.get("video_mb", 25)) * 8 * 1024 * 0.93  # 7% headroom for the container
        audio = AUDIO_KBPS if info.get("has_audio") else 0
        kbps = max(80, total_kbit / dur - audio)
        # Fewer pixels look much better than a starved bitrate.
        for cap, need in ((1080, 2500), (720, 1100), (540, 600), (360, 0)):
            if kbps >= need:
                auto_cap = cap
                break
        short_cap = min(short_cap or 10**6, auto_cap)
    else:
        crf = 26
    short = min(w, h)
    if short_cap and short > short_cap:
        scale = short_cap / short
        w, h = w * scale, h * scale
    w, h = int(round(w / 2)) * 2, int(round(h / 2)) * 2
    return max(2, w), max(2, h), kbps, crf


def shrink_video(src, settings, progress=None, cancel=None, _attempt=0):
    import av
    info = probe_video(src)
    if "width" not in info:
        raise ValueError("No video track in this file")
    w, h, kbps, crf = _plan(info, settings)
    if _attempt:
        kbps = kbps * (0.82 ** _attempt) if kbps else None
        if crf:
            crf += 3 * _attempt
    dst = output_path(src, ".mp4", settings) if not _attempt else settings["_dst"]
    tmp = dst + ".part.mp4"
    dur = info["duration"] or 0
    fps = info.get("fps") or 30
    if fps > 61:
        fps = 60

    inp = av.open(src)
    out = av.open(tmp, "w", format="mp4", options={"movflags": "+faststart"})
    try:
        vin = inp.streams.video[0]
        vin.thread_type = "AUTO"
        from fractions import Fraction
        rate = Fraction(fps).limit_denominator(1001)
        vout = out.add_stream("libx264", rate=rate)
        vout.width, vout.height = w, h
        vout.pix_fmt = "yuv420p"
        opts = {"preset": "veryfast", "profile": "high"}
        if kbps:
            vout.bit_rate = int(kbps * 1000)
            opts.update(maxrate=f"{int(kbps * 1.3)}k", bufsize=f"{int(kbps * 2)}k")
        else:
            opts["crf"] = str(crf)
        vout.options = opts
        vout.codec_context.time_base = Fraction(1, 90000)

        ain = inp.streams.audio[0] if inp.streams.audio else None
        aout = None
        if ain is not None:
            aout = out.add_stream("aac", rate=min(ain.rate or 48000, 48000))
            aout.bit_rate = AUDIO_KBPS * 1000
            resampler = av.AudioResampler(format="fltp", layout="stereo" if (ain.channels or 2) >= 2 else "mono",
                                          rate=aout.rate)
        rotation = info.get("rotation", 0)
        streams = [vin] + ([ain] if ain is not None else [])
        last = 0.0
        for packet in inp.demux(*streams):
            if cancel and cancel():
                raise Cancelled()
            for frame in packet.decode():
                if packet.stream.type == "video":
                    t = float(frame.pts * vin.time_base) if frame.pts is not None else last
                    img = frame
                    if rotation:
                        img = _rotate(frame, rotation)
                    img = img.reformat(width=w, height=h, format="yuv420p")
                    img.pts = int(round(t * 90000))
                    img.time_base = Fraction(1, 90000)
                    for p in vout.encode(img):
                        out.mux(p)
                    if progress and dur and t - last > 0.25:
                        last = t
                        progress(min(0.99, t / dur))
                elif aout is not None:
                    frame.pts = None
                    for rf in resampler.resample(frame):
                        for p in aout.encode(rf):
                            out.mux(p)
        for p in vout.encode():
            out.mux(p)
        if aout is not None:
            for rf in resampler.resample(None):
                for p in aout.encode(rf):
                    out.mux(p)
            for p in aout.encode():
                out.mux(p)
    except BaseException:
        out.close()
        inp.close()
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    out.close()
    inp.close()

    # Single-pass bitrate targeting can overshoot a little: retry smaller if we missed the limit.
    limit = float(settings.get("video_mb", 25)) * 1024 * 1024
    if kbps and os.path.getsize(tmp) > limit and _attempt < 3:
        os.remove(tmp)
        return shrink_video(src, dict(settings, _dst=dst), progress, cancel, _attempt + 1)
    os.replace(tmp, dst)
    if settings.get("keep_dates", True):
        copy_dates(src, dst)
    if progress:
        progress(1.0)
    return dst


def _rotate(frame, rotation):
    """Bake a rotation flag into the pixels (PyAV reports it counter-clockwise in degrees)."""
    import av
    from PIL import Image
    img = frame.to_image()
    rot = rotation % 360
    if rot == 90:
        img = img.transpose(Image.Transpose.ROTATE_90)
    elif rot == 180:
        img = img.transpose(Image.Transpose.ROTATE_180)
    elif rot == 270:
        img = img.transpose(Image.Transpose.ROTATE_270)
    nf = av.VideoFrame.from_image(img)
    return nf


def process(path, settings, progress=None, cancel=None):
    k = kind_of(path)
    if k == "photo":
        return shrink_photo(path, settings, progress)
    if k == "video":
        return shrink_video(path, settings, progress, cancel)
    raise ValueError("Unsupported file type")
