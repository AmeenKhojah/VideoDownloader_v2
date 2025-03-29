import os
import uuid
import logging
import glob
import time
import urllib.parse
from flask import (Flask, render_template, request, jsonify,
                   Response, stream_with_context, after_this_request) # Removed unused after_this_request
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
    temp_title = '-'.join(temp_title.split()) # Consolidate whitespace to single dash
    safe_title = temp_title or "video"
    safe_title = safe_title[:100] # Limit length
    return f"{safe_title}-{quality}.{extension}"

def fetch_video_info(url):
    """Uses yt-dlp to get video metadata."""
    logger.info(f"Fetching info for URL: {url}")
    ydl_opts = {
        'quiet': True, 'no_warnings': True, 'skip_download': True,
        'forcejson': True, 'socket_timeout': 15,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
        title = info_dict.get('title', 'Untitled Video')
        thumbnail_url = info_dict.get('thumbnail')
        formats = info_dict.get('formats', [])
        webpage_url = info_dict.get('webpage_url', url)
        available_heights = set()
        for f in formats:
            height = f.get('height')
            # Ensure it's a video format with a valid height
            if height and isinstance(height, int) and f.get('vcodec', 'none') != 'none':
                available_heights.add(height)
        if not available_heights:
             # Check for audio-only
             if any(f.get('vcodec', 'none') == 'none' and f.get('acodec', 'none') != 'none' for f in formats):
                 logger.warning(f"No video resolutions found, potentially audio-only: {url}")
                 return None, "No video resolutions found (might be audio-only)."
             else:
                 logger.warning(f"No video or audio formats found for: {url}")
                 return None, "No compatible video formats found."
        sorted_heights = sorted(list(available_heights), reverse=True)
        quality_options = {f"{h}p": h for h in sorted_heights}
        return {'title': title, 'thumbnail_url': thumbnail_url, 'quality_options': quality_options, 'webpage_url': webpage_url}, None
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError fetching info for {url}: {e}")
        error_msg = f"Could not process link. Is it valid and accessible? (Error: {e})"
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
        time.sleep(0.1) # Short delay before starting
        found_files = glob.glob(file_pattern)
        if not found_files: logger.info(f"Cleanup: No files found matching pattern {file_pattern}"); return

        for f_path in found_files:
            max_retries = 3; retry_delay = 0.3
            for attempt in range(max_retries):
                try:
                    if os.path.exists(f_path):
                         os.remove(f_path); logger.info(f"Successfully deleted temp file {f_path} (attempt {attempt + 1})."); break
                    else: logger.info(f"Cleanup: File {f_path} already gone (attempt {attempt + 1})."); break
                except OSError as e:
                    is_lock_error = (hasattr(e, 'winerror') and e.winerror == 32) or (hasattr(e, 'errno') and e.errno in [13, 16])
                    if is_lock_error and attempt < max_retries - 1: logger.warning(f"Cleanup attempt {attempt + 1} for {f_path} failed (lock error). Retrying in {retry_delay}s..."); time.sleep(retry_delay)
                    else:
                        if is_lock_error: logger.error(f"Could not remove temp file {f_path} after {max_retries} attempts (lock error): {e}")
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
                 # Yield chunk must happen *before* checking if it's empty
                 # An empty chunk signifies EOF.
                 if not chunk:
                     logger.info(f"Generator: Reached EOF for {file_path}.")
                     break
                 yield chunk # Yield the actual data
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
    url = request.json.get('url')
    if not url: return jsonify({'error': 'URL is required.'}), 400
    video_info, error = fetch_video_info(url)
    if error: status_code = 400 if "Unsupported" in error or "unavailable" in error or "valid" in error else 500; return jsonify({'error': error}), status_code
    if not video_info: return jsonify({'error': 'Could not retrieve video information.'}), 500
    return jsonify(video_info)

@app.route('/download', methods=['GET'])
def handle_download():
    """Handles the video download request ensuring mobile compatibility."""
    url = request.args.get('url')
    quality = request.args.get('quality')
    title = request.args.get('title', 'video')

    if not url or not quality: logger.warning("Download request missing URL or quality parameter."); return "Missing URL or quality parameter.", 400

    temp_id = str(uuid.uuid4())
    temp_filepath_pattern_for_delete = os.path.join(TEMP_FOLDER, f'{temp_id}.*')
    final_temp_filepath = None

    try:
        try: height = int(quality.replace('p', ''))
        except ValueError: logger.error(f"Invalid quality format received: {quality}"); _cleanup_temp_files(temp_filepath_pattern_for_delete); return "Invalid quality format.", 400

        # --- !!! UPDATED FORMAT SELECTOR FOR MOBILE COMPATIBILITY !!! ---
        # Prioritize H.264 (avc) video and AAC audio in MP4/M4A containers
        # Use vcodec^=avc means "starts with avc" (e.g. avc1.xxxxx)
        # Use acodec^=aac means "starts with aac" (less common, mp4a is often used for AAC in MP4)
        # Adjusted to prefer mp4a for audio in mp4/m4a containers.
        format_selector = (
            # Most compatible: H264 video in MP4 + AAC audio in M4A (yt-dlp merges this well into final MP4)
            f'bestvideo[height<={height}][vcodec^=avc][ext=mp4]+bestaudio[acodec=mp4a][ext=m4a]/'
            # H264 video in MP4 + AAC audio (any container extension)
            f'bestvideo[height<={height}][vcodec^=avc][ext=mp4]+bestaudio[acodec=mp4a]/'
            # H264 video (any ext) + AAC audio (any ext) - relies more on ffmpeg merge/convert
            f'bestvideo[height<={height}][vcodec^=avc]+bestaudio[acodec=mp4a]/'
            # Fallback: Best MP4 video + Best M4A audio (likely AAC)
            f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/'
            # Fallback: Best H264 video + best audio overall
            f'bestvideo[height<={height}][vcodec^=avc]+bestaudio/'
            # Fallback: Best MP4 video + best audio overall
            f'bestvideo[height<={height}][ext=mp4]+bestaudio/'
            # General Fallback: Best video + best audio (might be VP9/Opus etc.)
            f'bestvideo[height<={height}]+bestaudio/'
            # Single file fallbacks (less likely needed for YouTube > 720p)
            f'best[height<={height}][ext=mp4]/' # Best combined MP4 up to height
            f'best[height<={height}]/'          # Best combined any format up to height
            f'best'                             # Overall best single file
        )
        preferred_ext = 'mp4' # We always want the final output to be mp4
        temp_filepath_pattern_ydl = os.path.join(TEMP_FOLDER, f'{temp_id}.%(ext)s')

        # --- !!! UPDATED ydl_opts with postprocessor_args for compatibility !!! ---
        ydl_opts = {
            'format': format_selector,
            'outtmpl': temp_filepath_pattern_ydl,
            'quiet': True, 'no_warnings': True, 'socket_timeout': 20, 'retries': 3,
            'merge_output_format': 'mp4', # Explicitly merge to mp4
            # Removed postprocessors list as args handle needed flags
            # 'postprocessors': [], # Can be empty or removed if only using args
             # Pass arguments directly to FFmpeg during merge/conversion
             'postprocessor_args': {
                 # Use the 'after_move' key so args apply *after* merging/conversion to the target format
                 'after_move': [
                     '-movflags', '+faststart', # Move metadata atom to beginning
                     '-pix_fmt', 'yuv420p',      # Ensure compatible pixel format
                 ]
                 # We avoid forcing re-encoding unless absolutely necessary:
                 # '-c:a', 'aac',        # Force AAC audio (use if selection fails)
                 # '-b:a', '128k',       # Example audio bitrate if forcing
                 # '-c:v', 'libx264',    # Force H.264 video (slow!)
                 # '-preset','fast',     # If forcing vcodec (speed vs size)
                 # '-crf', '22'          # If forcing vcodec (quality vs size)
             }
        }

        logger.info(f"Starting download ({temp_id}) for URL: {url}, Quality: {quality} [Mobile Compatibility Mode]")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([url])

        # File finding logic remains the same
        downloaded_files = glob.glob(os.path.join(TEMP_FOLDER, f'{temp_id}.*'))
        if not downloaded_files: logger.error(f"Download finished ({temp_id}) but output file not found."); raise FileNotFoundError("Downloaded file could not be located on server.")

        final_temp_filepath = downloaded_files[0]
        actual_filename, actual_extension = os.path.splitext(os.path.basename(final_temp_filepath))
        actual_extension = actual_extension.lstrip('.')
        # Ensure the final extension reflects the container we aimed for
        if actual_extension.lower() != preferred_ext:
             logger.warning(f"Final file extension '{actual_extension}' differs from preferred '{preferred_ext}'. Mimetype/Filename based on actual.")

        logger.info(f"Download ({temp_id}) complete. Found file: {final_temp_filepath}")

        suggested_filename_raw = get_clean_filename(title, quality, actual_extension or preferred_ext)
        suggested_filename_encoded = urllib.parse.quote(suggested_filename_raw)

        if not os.path.exists(final_temp_filepath): logger.error(f"File {final_temp_filepath} disappeared before streaming."); raise FileNotFoundError("File disappeared before streaming.")

        file_size = os.path.getsize(final_temp_filepath); mime_type = f'video/{actual_extension or preferred_ext}'
        headers = {'Content-Disposition': f"attachment; filename*=UTF-8''{suggested_filename_encoded}", 'Content-Length': str(file_size), 'Content-Type': mime_type}

        # Streaming and cleanup call remain the same
        stream = stream_with_context(generate_file_chunks_and_cleanup(final_temp_filepath, temp_filepath_pattern_for_delete))
        logger.info(f"Preparing to stream {final_temp_filepath} as {suggested_filename_raw} ({file_size} bytes).")
        return Response(stream, headers=headers)

    # --- Exception Handling (includes cleanup calls) ---
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError during download ({temp_id}): {e}")
        err_str = str(e).lower(); user_message = f"Download failed: {e}"
        # Check for specific FFmpeg errors within the DownloadError
        if 'ffmpeg' in err_str or 'postprocessor' in err_str:
             user_message = "Download failed: FFmpeg processing error during merge/conversion."
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
    # IMPORTANT: debug=False should be used for production/deployment
    app.run(debug=False, host='0.0.0.0', port=port)
