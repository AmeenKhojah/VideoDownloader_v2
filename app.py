import os
import uuid
import logging
import glob
import time
import urllib.parse
from flask import (Flask, render_template, request, jsonify,
                   Response, stream_with_context, abort) # Added abort back
import yt_dlp
import requests

# --- Configuration ---
app = Flask(__name__)
TEMP_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp_downloads')
if not os.path.exists(TEMP_FOLDER):
    try: os.makedirs(TEMP_FOLDER)
    except OSError as e:
        if not os.path.isdir(TEMP_FOLDER): raise
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Helper Functions ---

def get_clean_filename(title, quality, extension):
    """Creates a filename safe for HTTP headers and filesystems, preserving more characters."""
    forbidden_chars = r'<>:"/\|?*'
    temp_title = "".join(c if c not in forbidden_chars else '_' for c in title)
    temp_title = temp_title.strip().strip('._')
    temp_title = '-'.join(temp_title.split())
    safe_title = temp_title or "video"
    safe_title = safe_title[:100]
    return f"{safe_title}-{quality}.{extension}"

def fetch_video_info(url):
    """Uses yt-dlp to get video metadata, including better thumbnail handling."""
    logger.info(f"Fetching info for URL: {url}")
    ydl_opts = {
        'quiet': True, 'no_warnings': True, 'skip_download': True,
        'forcejson': True, 'socket_timeout': 15,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
        title = info_dict.get('title', 'Untitled Video')
        webpage_url = info_dict.get('webpage_url', url)
        thumbnail_url = info_dict.get('thumbnail')
        if not thumbnail_url:
            thumbnails_list = info_dict.get('thumbnails')
            if isinstance(thumbnails_list, list) and thumbnails_list:
                thumbnail_url = thumbnails_list[-1].get('url') or thumbnails_list[0].get('url')
                if thumbnail_url: logger.info(f"Using thumbnail from 'thumbnails' list for {url}")
        proxy_thumbnail_url = None
        if thumbnail_url:
            proxy_thumbnail_url = f"/thumbnail_proxy?url={urllib.parse.quote_plus(thumbnail_url)}"
        else: logger.warning(f"Could not find a source thumbnail URL for {url}")

        formats = info_dict.get('formats', [])
        available_heights = set()
        for f in formats:
            height = f.get('height')
            if height and isinstance(height, int) and f.get('vcodec', 'none') != 'none':
                available_heights.add(height)
        if not available_heights:
             if any(f.get('vcodec', 'none') == 'none' and f.get('acodec', 'none') != 'none' for f in formats): return None, "No video resolutions found (might be audio-only)."
             else: return None, "No compatible video formats found."
        sorted_heights = sorted(list(available_heights), reverse=True)
        quality_options = {f"{h}p": h for h in sorted_heights}
        return {'title': title, 'thumbnail_url': proxy_thumbnail_url, 'quality_options': quality_options, 'webpage_url': webpage_url}, None
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError fetching info for {url}: {e}")
        error_msg = f"Could not process link: {e}"
        if e.args and isinstance(e.args[0], str):
             if "Unsupported URL" in e.args[0]: error_msg = "Unsupported URL."
             elif "video unavailable" in e.args[0].lower(): error_msg = "Video unavailable/private."
             elif "urlopen error" in e.args[0].lower(): error_msg = "Network error fetching info."
        return None, error_msg
    except Exception as e:
        logger.error(f"Unexpected error fetching info for {url}: {e}", exc_info=True)
        return None, f"An unexpected server error occurred fetching info."

def _cleanup_temp_files(file_pattern):
    """Safely removes files matching a pattern, with retries."""
    try:
        logger.info(f"Attempting cleanup initiated for pattern: {file_pattern}")
        time.sleep(0.1)
        found_files = glob.glob(file_pattern)
        if not found_files: logger.info(f"Cleanup: No files found matching pattern {file_pattern}"); return
        for f_path in found_files:
            max_retries = 3; retry_delay = 0.3
            for attempt in range(max_retries):
                try:
                    if os.path.exists(f_path): os.remove(f_path); logger.info(f"Successfully deleted temp file {f_path} (attempt {attempt + 1})."); break
                    else: logger.info(f"Cleanup: File {f_path} already gone (attempt {attempt + 1})."); break
                except OSError as e:
                    is_lock_error = (hasattr(e, 'winerror') and e.winerror == 32) or (hasattr(e, 'errno') and e.errno in [13, 16])
                    if is_lock_error and attempt < max_retries - 1: logger.warning(f"Cleanup attempt {attempt + 1} for {f_path} failed (lock error). Retrying..."); time.sleep(retry_delay)
                    else:
                        if is_lock_error: logger.error(f"Could not remove temp file {f_path} after retries (lock error): {e}")
                        else: logger.error(f"Error removing temporary file {f_path}: {e}")
                        break
                except Exception as e: logger.error(f"Unexpected error during cleanup attempt {attempt + 1} for {f_path}: {e}"); break
            else: logger.error(f"Cleanup for {f_path} failed after all retries.")
    except Exception as e: logger.error(f"Unexpected error during glob matching for cleanup {file_pattern}: {e}")

def generate_file_chunks_and_cleanup(file_path, cleanup_pattern, chunk_size=8192):
    """Generator yields file chunks & triggers cleanup in finally block."""
    try:
        if not os.path.exists(file_path): logger.error(f"Generator: File {file_path} does not exist at start."); return
        with open(file_path, 'rb') as f:
            logger.info(f"Generator: Opened {file_path} for reading.")
            while True:
                 chunk = f.read(chunk_size)
                 if not chunk: logger.info(f"Generator: Reached EOF for {file_path}."); break
                 yield chunk
        logger.info(f"Generator: Finished yielding & closed {file_path}.")
    except Exception as e: logger.error(f"Error during chunk generation for {file_path}: {e}")
    finally:
        logger.info(f"Generator finally block reached for {file_path}. Triggering cleanup.")
        _cleanup_temp_files(cleanup_pattern)

# --- Flask Routes ---

@app.route('/')
def index(): return render_template('index.html')

@app.route('/fetch_info', methods=['POST'])
def handle_fetch_info():
    """Handles AJAX request to get video info."""
    url = request.json.get('url')
    if not url: return jsonify({'error': 'URL is required.'}), 400
    video_info, error = fetch_video_info(url)
    if error: status_code = 400 if "Unsupported" in error or "unavailable" in error or "valid" in error else 500; return jsonify({'error': error}), status_code
    if not video_info: return jsonify({'error': 'Could not retrieve video information.'}), 500
    return jsonify(video_info)

@app.route('/thumbnail_proxy')
def thumbnail_proxy():
    """Fetches thumbnail from original URL and streams it back."""
    image_url = request.args.get('url')
    if not image_url: abort(400, 'Missing image URL parameter.')
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    timeout = 10
    try:
        logger.info(f"Proxying thumbnail from: {image_url}")
        r = requests.get(image_url, stream=True, headers=headers, timeout=timeout)
        r.raise_for_status()
        content_type = r.headers.get('Content-Type')
        if not content_type or not content_type.lower().startswith('image/'): logger.error(f"Invalid content type '{content_type}' for proxy: {image_url}"); abort(400, 'URL did not point to a valid image.')
        response = Response(stream_with_context(r.iter_content(chunk_size=8192)), content_type=content_type)
        return response
    except requests.exceptions.Timeout: logger.error(f"Timeout fetching thumbnail for proxy: {image_url}"); abort(504, 'Timeout fetching thumbnail image.')
    except requests.exceptions.RequestException as e: logger.error(f"Error fetching thumbnail for proxy: {image_url} - {e}"); abort(502, f'Error fetching thumbnail image: {e}')
    except Exception as e: logger.error(f"Unexpected error in thumbnail proxy for {image_url}: {e}", exc_info=True); abort(500, 'Internal server error during thumbnail proxy.')


@app.route('/download', methods=['GET'])
def handle_download():
    """Handles video download, forcing re-encode to H.264 Baseline/AAC for compatibility."""
    url = request.args.get('url')
    quality = request.args.get('quality')
    title = request.args.get('title', 'video')

    if not url or not quality: logger.warning("Download request missing URL/quality."); return "Missing URL or quality parameter.", 400

    temp_id = str(uuid.uuid4())
    temp_filepath_pattern_for_delete = os.path.join(TEMP_FOLDER, f'{temp_id}.*')
    final_temp_filepath = None

    try:
        try: height = int(quality.replace('p', ''))
        except ValueError: logger.error(f"Invalid quality: {quality}"); _cleanup_temp_files(temp_filepath_pattern_for_delete); return "Invalid quality format.", 400

        # Simple format selector - let FFmpeg do the heavy lifting
        format_selector = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]/best'
        preferred_ext = 'mp4'
        temp_filepath_pattern_ydl = os.path.join(TEMP_FOLDER, f'{temp_id}.%(ext)s')

        # --- !!! UPDATED ydl_opts: FORCE RE-ENCODE WITH SPECIFIC MOBILE PROFILE !!! ---
        # WARNING: CPU-intensive! Targets maximum compatibility.
        ydl_opts = {
            'format': format_selector,
            'outtmpl': temp_filepath_pattern_ydl,
            'quiet': True, 'no_warnings': True, 'socket_timeout': 20, 'retries': 3,
            'merge_output_format': 'mp4', # Merge to MP4 before final adjustments if needed
             'postprocessor_args': {
                 # Apply these FFmpeg arguments during the final output stage
                 'default': [
                     '-c:v', 'libx264',
                     '-profile:v', 'baseline', # Max compatibility profile
                     '-level', '3.1',          # Compatible level
                     '-crf', '23',             # Quality (adjust as needed)
                     '-preset', 'fast',        # Encoding speed (faster = larger)
                     '-pix_fmt', 'yuv420p',     # Pixel format
                     '-c:a', 'aac',             # Audio codec
                     '-b:a', '128k',            # Audio bitrate
                     '-movflags', '+faststart', # Web/Mobile optimized
                 ]
             }
             # Removed explicit FFmpegVideoConvertor postprocessor key
             # The presence of codec args in postprocessor_args forces conversion.
        }
        # --- End of ydl_opts update ---


        logger.info(f"Starting download ({temp_id}) URL: {url}, Q: {quality} [FORCE MOBILE RE-ENCODE MODE]")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([url])

        # Look for the final .mp4 file, as conversion should result in .mp4
        final_mp4_path = os.path.join(TEMP_FOLDER, f'{temp_id}.{preferred_ext}')
        if not os.path.exists(final_mp4_path):
            other_files = glob.glob(os.path.join(TEMP_FOLDER, f'{temp_id}.*'))
            if other_files: logger.warning(f"Final MP4 not found, using first other file: {other_files[0]}"); final_temp_filepath = other_files[0]
            else: logger.error(f"Output MP4 file not found: {final_mp4_path}"); raise FileNotFoundError("Final MP4 file not found.")
        else: final_temp_filepath = final_mp4_path


        actual_filename, actual_extension = os.path.splitext(os.path.basename(final_temp_filepath)); actual_extension = actual_extension.lstrip('.')
        output_extension = preferred_ext # Expect MP4 due to forced conversion
        if actual_extension.lower() != preferred_ext: logger.warning(f"Final file extension '{actual_extension}' differs from expected '{preferred_ext}'.")

        logger.info(f"Download/Re-encode ({temp_id}) complete. Found: {final_temp_filepath}")

        suggested_filename_raw = get_clean_filename(title, quality, output_extension)
        suggested_filename_encoded = urllib.parse.quote(suggested_filename_raw)

        if not os.path.exists(final_temp_filepath): logger.error(f"File {final_temp_filepath} gone before streaming."); raise FileNotFoundError("File disappeared before streaming.")

        file_size = os.path.getsize(final_temp_filepath); mime_type = f'video/{output_extension}'
        headers = {'Content-Disposition': f"attachment; filename*=UTF-8''{suggested_filename_encoded}", 'Content-Length': str(file_size), 'Content-Type': mime_type}
        stream = stream_with_context(generate_file_chunks_and_cleanup(final_temp_filepath, temp_filepath_pattern_for_delete))
        logger.info(f"Streaming {final_temp_filepath} as {suggested_filename_raw} ({file_size} bytes).")
        return Response(stream, headers=headers)

    # --- Exception Handling ---
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError during download/re-encode ({temp_id}): {e}")
        err_str = str(e).lower(); user_message = f"Download failed: {e}"
        if 'ffmpeg' in err_str or 'postprocessor' in err_str or 'Conversion failed' in str(e) or 'encoder' in err_str:
            user_message = "Download failed: Error during FFmpeg video re-encoding." # Make message clearer
        elif "urlopen error" in err_str or "timed out" in err_str: user_message = "Download failed: Network error/timeout."
        logger.info(f"Cleaning up ({temp_id}) after download error."); _cleanup_temp_files(temp_filepath_pattern_for_delete)
        return user_message, 500
    except FileNotFoundError as e:
         logger.error(f"File not found error ({temp_id}): {e}"); logger.info(f"Cleaning up ({temp_id}) after FileNotFoundError."); _cleanup_temp_files(temp_filepath_pattern_for_delete)
         return "Download process error: file could not be found or disappeared.", 500
    except Exception as e:
        logger.error(f"Unexpected error during download ({temp_id}): {e}", exc_info=True); logger.info(f"Cleaning up ({temp_id}) after unexpected error."); _cleanup_temp_files(temp_filepath_pattern_for_delete)
        return f"An unexpected server error occurred during download.", 500

# --- Main Execution ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Flask app starting.")
    app.run(debug=False, host='0.0.0.0', port=port)
