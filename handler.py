import runpod
import requests
import os
import random
import cloudinary
import cloudinary.uploader
from cloudinary import CloudinaryVideo
import tempfile
import shutil
import yt_dlp
from datetime import datetime

# Opsi yt-dlp
YTDL_OPTS = {
    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
    'noplaylist': True,
    'quiet': True,
}

# --- Konfigurasi cloudinary ---
CLOUDINARY_NAME = os.environ.get("CLOUDINARY_NAME") 
CLOUDINARY_NAME_API = os.environ.get("CLOUDINARY_NAME_API")
CLOUDINARY_SECRET = os.environ.get("CLOUDINARY_SECRET")

# --- Validasi Konfigurasi DO Spaces ---
if not all([CLOUDINARY_NAME, CLOUDINARY_NAME_API, CLOUDINARY_SECRET]):
    print("WARNING: Konfigurasi cloudinary tidak lengkap. Upload akan dilewati.")
    CLOUDINARY_ENABLED = False
else:
    CLOUDINARY_ENABLED = True
    print(f"cloudinary client diaktifkan.")
    # Inisialisasi client S3 untuk DO Spaces
    cloudinary.config(
            cloud_name = CLOUDINARY_NAME,
            api_key = CLOUDINARY_NAME_API,
            api_secret = CLOUDINARY_SECRET
    )

# --- Fungsi Helper ---
def upload_temp_file(username, files):
    try:
        date_str = datetime.today().strftime("%d-%m-%Y")
        options = {
            "quality": "auto:good",
            "asset_folder" : f"temp/{username}/{date_str}", 
            "public_id" : str(f"temp_{username}_{random.randint(1, 1000000)}"),
            "overwrite" : True,
            "resource_type": "video"
        }
        try:
            uploading = cloudinary.uploader.upload_large(files, **options)
            return uploading
        except Exception as e:
            print(str(e))
            return None
    
    except Exception as e:
        print(str(e))
        return None
    
def download_video(url, download_path, username):
    try:
        # === LOKASI OUTPUT FILE ===
        output_template = os.path.join(download_path, f"{username}_downloaded_video.%(ext)s")

        # === DOWNLOAD DENGAN yt-dlp ===
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': output_template,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_filename = ydl.prepare_filename(info)
            if not video_filename.endswith(".mp4"):
                # Rename ke .mp4 jika format bukan mp4
                base, ext = os.path.splitext(video_filename)
                new_filename = base + ".mp4"
                os.rename(video_filename, new_filename)
                video_filename = new_filename

        # === UPLOAD KE CLOUDINARY ===
        res = upload_temp_file(username, video_filename)

        try:
            # === HAPUS FILE VIDEO SETELAH DIUPLOAD ===
            if os.path.exists(video_filename):
                os.remove(video_filename)
        except Exception as e:
            print(str(e))

        return res
    except Exception as e:
        print(f"Error saat mengunduh video: {e}")
        raise

def send_hook(hook_url, data):
    req = requests.post(hook_url, json=data)

# --- Handler RunPod ---
def handler(job):
    """
    Handler utama untuk job RunPod Serverless.
    """
    job_input = job.get('input', None)

    if not job_input:
        return {"error": "Input tidak ditemukan dalam job payload."}

    youtube_url = job_input.get('youtube_url')
    start_time = job_input.get('start_time')
    end_time = job_input.get('end_time')
    webhook = job_input.get('webhook')

    if not youtube_url or start_time is None or end_time is None:
        return {"error": "Parameter 'youtube_url', 'start_time', dan 'end_time' wajib ada."}

    temp_dir = tempfile.mkdtemp()
    print(f"Direktori kerja sementara dibuat: {temp_dir}")
    output_url = None # Inisialisasi

    try:
        # 1. Unduh video
        uploaded = download_video(youtube_url, temp_dir, "daffyshaci")

        # 2. callback ke kreator ai
        if webhook:
            send_hook(webhook, uploaded)

        # 3. doing transformation
        public_id = uploaded.get('public_id')
        output_url = CloudinaryVideo(public_id).build_url(secure=True, transformation=[
            {"start_offset": start_time, "end_offset": end_time},
        ])

        # 5. Kembalikan hasil (URL jika upload berhasil)
        print(f"Proses selesai. Output URL: {output_url}")
        return {
            "message": "Video berhasil dipotong dan diupload.",
            "output_url": output_url,
        }

    except FileNotFoundError as e:
         print(f"Error: {e}")
         return {"error": f"Gagal menemukan file: {e}"}
    except yt_dlp.utils.DownloadError as e:
        print(f"Error Download: {e}")
        # Mencoba mengambil pesan error yang lebih spesifik jika ada
        err_msg = str(e)
        if hasattr(e, 'msg'): err_msg = e.msg
        return {"error": f"Gagal mengunduh video: {err_msg}"}
    except Exception as e:
        print(f"Error tak terduga: {e}")
        import traceback
        traceback.print_exc() # Print traceback ke log server untuk debugging
        return {"error": f"Terjadi kesalahan internal: {type(e).__name__}"}
    finally:
        # Bersihkan direktori sementara
        if os.path.exists(temp_dir):
            print(f"Membersihkan direktori sementara: {temp_dir}")
            shutil.rmtree(temp_dir)

# Mulai server RunPod jika script dijalankan langsung
if __name__ == "__main__":
    print("Memulai worker RunPod...")
    runpod.serverless.start({"handler": handler})