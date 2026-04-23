import os
import subprocess
import json
import uuid
import time
import sys
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, send_from_directory, session
from pathlib import Path
import threading
import shutil
import re

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(32))

# Configuration
DATA_DIR = Path("./data")
EXCEL_FILE = DATA_DIR / "Return.xlsx"  # kept for legacy downloads but not relied upon by UI
ENV_FILE = Path(".env")
CONFIG_FILE = Path("config.json")
PROJECT_ROOT = Path(__file__).resolve().parent

# Simple in-memory job manager
jobs = {}
# Lock to protect jobs dictionary and job entries from concurrent access
jobs_lock = threading.Lock()
# job structure: {
#   job_id: { 'running': bool, 'message': str, 'start_time': str, 'end_time': str or None, 'file': filename or None, 'log': log_path }
# }


def load_config():
    """Load configuration from config.json"""
    base = {
        "username": "",
        "password": "",
        "admin_email": "",
        "admin_password": "",
        "webapp_url": "",
        "courier_webapp_url": "",
        "google_web_app_url": ""
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
            base.update({k: data.get(k, base[k]) for k in base.keys()})
        except Exception:
            return base
    return base


def detect_compose_cmd():
    """Return a compose command list depending on system availability.
    Prefer 'docker compose' if docker CLI is present and 'docker-compose' otherwise.
    """
    # Prefer 'docker compose' if it actually works; otherwise try 'docker-compose'.
    try:
        if shutil.which('docker'):
            # test if 'docker compose version' runs
            res = subprocess.run(['docker', 'compose', 'version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0:
                return ['docker', 'compose']
    except Exception:
        pass

    if shutil.which('docker-compose'):
        try:
            res = subprocess.run(['docker-compose', 'version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0:
                return ['docker-compose']
        except Exception:
            pass

    # last resort: prefer ['docker', 'compose'] even if test failed (may work on some systems)
    return ['docker', 'compose']


# determine compose command once
COMPOSE_CMD = detect_compose_cmd()


essential_env_comment = """# SteadFast Credentials
STEADFAST_USERNAME={username}
STEADFAST_PASSWORD={password}

# Target Date
# Use 'today' for current date, or specify a date in YYYY-MM-DD format
# Examples: today, 2024-01-30, 2024-12-25
TARGET_DATE=today
"""


def save_config(username, password, admin_email=None, admin_password=None, webapp_url=None, courier_webapp_url=None, google_web_app_url=None):
    """Save configuration to config.json and .env file"""
    existing = load_config()
    config = {
        "username": username if username is not None else existing.get('username', ''),
        "password": password if password is not None else existing.get('password', ''),
        "admin_email": admin_email if admin_email is not None else existing.get('admin_email', ''),
        "admin_password": admin_password if admin_password is not None else existing.get('admin_password', ''),
        "webapp_url": webapp_url if webapp_url is not None else existing.get('webapp_url', ''),
        "courier_webapp_url": courier_webapp_url if courier_webapp_url is not None else existing.get('courier_webapp_url', ''),
        "google_web_app_url": google_web_app_url if google_web_app_url is not None else existing.get('google_web_app_url', '')
    }

    # Save to JSON
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

    # Update .env file (SteadFast creds + optional Google web app url)
    env_content = essential_env_comment.format(username=config['username'], password=config['password'])
    # Append Google Web App URL if present
    if config.get('google_web_app_url'):
        env_content += f"\n# Google Web App URL for Parcel Monitor\nGOOGLE_WEB_APP_URL={config.get('google_web_app_url')}\n"
    with open(ENV_FILE, 'w') as f:
        f.write(env_content)


def run_batch_job(job_id, start_date, end_date, output_file):
    """Run the return scraper for a date range, accumulating results into one Excel, then post-process."""
    job = jobs[job_id]
    job['running'] = True
    job['message'] = f"Batch scraping from {start_date} to {end_date}..."
    job['start_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    job['task'] = 'scrape-range'

    # Prepare environment
    env = os.environ.copy()
    env['DATA_DIR'] = str(DATA_DIR.resolve())
    env['PYTHONUNBUFFERED'] = '1'

    # Log file per job
    log_path = DATA_DIR / f"job_{job_id}.log"
    job['log'] = str(log_path)

    # Determine days list (inclusive)
    try:
      sd = datetime.strptime(start_date, '%Y-%m-%d').date()
      ed = datetime.strptime(end_date, '%Y-%m-%d').date()
    except Exception:
      job['running'] = False
      job['message'] = 'Invalid date format (expected YYYY-MM-DD)'
      job['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
      return

    if ed < sd:
      job['running'] = False
      job['message'] = 'End date must be on/after start date'
      job['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
      return

    days = []
    d = sd
    while d <= ed:
      days.append(d.strftime('%Y-%m-%d'))
      d = d + timedelta(days=1)

    # Use a single output filename for the whole batch
    container_output = f"/app/data/{output_file.name}"

    try:
        for idx, day in enumerate(days, start=1):
            job['message'] = f"[{idx}/{len(days)}] Scraping {day}..."
            with open(log_path, 'a', encoding='utf-8') as lf:
                lf.write(f"\n==== Running return_scraper.py for {day} ({idx}/{len(days)}) ====\n")

            # Build docker compose run command with credentials (if configured)
            container_name = f"steadfast_range_{job_id}_{idx}"
            env_flags = ['-e', f'TARGET_DATE={day}', '-e', 'PYTHONUNBUFFERED=1']
            # For subsequent days, instruct the scraper not to delete existing output
            if idx > 1:
                env_flags += ['-e', 'APPEND_TO_EXISTING=1']
            try:
                conf = load_config()
                if conf.get('username'):
                    env_flags += ['-e', f"STEADFAST_USERNAME={conf.get('username')}"]
                if conf.get('password'):
                    env_flags += ['-e', f"STEADFAST_PASSWORD={conf.get('password')}"]
            except Exception:
                pass

            cmd = COMPOSE_CMD + ['run', '--rm', '--name', container_name] + env_flags + ['return-scraper', 'python', '-u', 'return_scraper.py', '--date', day, '--output', container_output]
            job['container'] = container_name

            with open(log_path, 'a', encoding='utf-8') as lf:
                proc = subprocess.Popen(cmd, env=env, stdout=lf, stderr=lf)
                job['proc'] = proc
                proc.wait()

            if proc.returncode != 0:
                job['running'] = False
                job['message'] = f'Batch run failed on {day} (exit {proc.returncode})'
                job['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                job['proc'] = None
                return

        # All daily runs succeeded; copy stable Return.xlsx and post-process with automate_returns.py
        job['file'] = output_file.name

        # Best-effort: copy to stable Return.xlsx for legacy
        try:
            stable = DATA_DIR / 'Return.xlsx'
            if output_file.exists():
                shutil.copy2(str(output_file), str(stable))
        except Exception:
            pass

        job['message'] = 'Post-processing (prices and quantity) started...'
        with open(log_path, 'a', encoding='utf-8') as lf:
            lf.write("\n==== Starting post-processing with automate_returns.py ====\n")

        try:
            post_env = os.environ.copy()
            post_env['EXCEL_FILE_PATH'] = str(output_file.resolve())
            post_env['PYTHONUNBUFFERED'] = '1'
            try:
                conf = load_config()
                if conf.get('admin_email'):
                    post_env['ADMIN_EMAIL'] = conf.get('admin_email')
                if conf.get('admin_password'):
                    post_env['ADMIN_PASSWORD'] = conf.get('admin_password')
            except Exception:
                pass
            cmd2 = [sys.executable, '-u', 'automate_returns.py', '--excel', str(output_file.resolve())]
            with open(log_path, 'a', encoding='utf-8') as lf:
                proc2 = subprocess.Popen(cmd2, env=post_env, stdout=lf, stderr=lf)
                proc2.wait()

            if proc2.returncode == 0:
                job['running'] = False
                job['message'] = f'Batch completed; output: {output_file.name}'
                job['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            else:
                job['running'] = False
                job['message'] = f'Batch completed, but post-processing failed (exit {proc2.returncode})'
                job['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            job['running'] = False
            job['message'] = f'Post-processing error: {e}'
            job['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        finally:
            job['proc'] = None

    except Exception as e:
        job['running'] = False
        job['message'] = f'Error: {str(e)}'
        job['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def run_job(job_id, target_date, output_file):
    """Run the scraper process for a specific job id."""
    job = jobs[job_id]
    job['running'] = True
    job['message'] = f"Scraping data for {target_date}..."
    job['start_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Prepare environment
    env = os.environ.copy()
    env['TARGET_DATE'] = target_date
    env['DATA_DIR'] = str(DATA_DIR.resolve())

    # Log file per job
    log_path = DATA_DIR / f"job_{job_id}.log"
    job['log'] = str(log_path)

    try:
        # Run scraper inside Docker using docker-compose so container environment is used
        # The compose service `return-scraper` mounts ./data to /app/data, so pass output path inside container
        container_output = f"/app/data/{output_file.name}"
        # Build environment flags and include configured credentials if available
        env_flags = ['-e', f'TARGET_DATE={target_date}', '-e', 'PYTHONUNBUFFERED=1']
        try:
            conf = load_config()
            if conf.get('username'):
                env_flags += ['-e', f"STEADFAST_USERNAME={conf.get('username')}"]
            if conf.get('password'):
                env_flags += ['-e', f"STEADFAST_PASSWORD={conf.get('password')}"]
        except Exception:
            pass

        # set a predictable container name so we can remove it on cancel
        container_name = f"steadfast_run_{job_id}"
        cmd = COMPOSE_CMD + ['run', '--rm', '--name', container_name] + env_flags + ['return-scraper', 'python', '-u', 'return_scraper.py', '--date', target_date, '--output', container_output]
        job['container'] = container_name

        with open(log_path, 'w', encoding='utf-8') as lf:
            proc = subprocess.Popen(cmd, env=env, stdout=lf, stderr=lf)
            # store process handle so it can be cancelled
            job['proc'] = proc
            proc.wait()

        if proc.returncode == 0:
            # Phase 1 done -> kick off post-processing (automate_returns.py)
            job['file'] = output_file.name
            # Wait for the file to appear on host (docker may take a moment)
            wait_seconds = 30
            interval = 1
            found = False
            for _ in range(int(wait_seconds / interval)):
                if output_file.exists():
                    found = True
                    break
                time.sleep(interval)

            # Copy (or overwrite) a stable Return.xlsx for legacy downloads
            stable = DATA_DIR / 'Return.xlsx'
            try:
                if found and output_file.exists():
                    shutil.copy2(str(output_file), str(stable))
                else:
                    # If not found, we'll still proceed to mark completion, but post-step may fail
                    pass
            except Exception:
                pass

            # Phase 2: run automate_returns.py against the just-created file
            job['message'] = 'Post-processing (prices and quantity) started...'
            with open(log_path, 'a', encoding='utf-8') as lf:
                lf.write("\n==== Starting post-processing with automate_returns.py ====:\n")
            try:
                # Run directly on host (not container) so it can use Selenium/Chrome from host.
                # Provide EXCEL_FILE_PATH via CLI and env mapping.
                post_env = os.environ.copy()
                post_env['EXCEL_FILE_PATH'] = str(output_file.resolve())
                post_env['PYTHONUNBUFFERED'] = '1'
                # Pass admin creds from config if available
                try:
                    conf = load_config()
                    if conf.get('admin_email'):
                        post_env['ADMIN_EMAIL'] = conf.get('admin_email')
                    if conf.get('admin_password'):
                        post_env['ADMIN_PASSWORD'] = conf.get('admin_password')
                except Exception:
                    pass
                cmd2 = [
                    sys.executable, '-u', 'automate_returns.py', '--excel', str(output_file.resolve())
                ]
                with open(log_path, 'a', encoding='utf-8') as lf:
                    proc2 = subprocess.Popen(cmd2, env=post_env, stdout=lf, stderr=lf)
                    proc2.wait()

                if proc2.returncode == 0:
                    job['running'] = False
                    job['message'] = f'Completed successfully; output: {output_file.name}'
                    job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                else:
                    job['running'] = False
                    job['message'] = f'Completed first phase, but post-processing failed (exit {proc2.returncode})'
                    job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                job['running'] = False
                job['message'] = f'Completed first phase, but post-processing error: {e}'
                job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            job['running'] = False
            job['message'] = f'Failed (exit code {proc.returncode})'
            job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # clear proc handle
        job['proc'] = None
    except Exception as e:
        job['running'] = False
        job['message'] = f'Error: {str(e)}'
        job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_monitor_job(job_id):
    """Run the steadfast_monitor.py inside docker-compose as a separate job."""
    job = jobs[job_id]
    job['running'] = True
    job['message'] = 'Starting parcel monitor...'
    job['start_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Prepare env and log
    env = os.environ.copy()
    log_path = DATA_DIR / f"job_{job_id}.log"
    job['log'] = str(log_path)

    # Read config for GOOGLE_WEB_APP_URL
    conf = load_config()
    g_url = conf.get('google_web_app_url') or conf.get('courier_webapp_url') or ''

    try:
        container_name = f"steadfast_monitor_{job_id}"
        cmd = COMPOSE_CMD + ['run', '--rm', '--name', container_name, '-e', f'STEADFAST_USERNAME={conf.get("username")}', '-e', f'STEADFAST_PASSWORD={conf.get("password")}', '-e', f'GOOGLE_WEB_APP_URL={g_url}', 'return-scraper', 'python', '-u', 'steadfast_monitor.py']
        job['container'] = container_name

        with open(log_path, 'w', encoding='utf-8') as lf:
            proc = subprocess.Popen(cmd, env=env, stdout=lf, stderr=lf)
            job['proc'] = proc
            max_seconds = int(os.environ.get('MONITOR_MAX_SECONDS', '0') or '0')
            if max_seconds > 0:
                try:
                    proc.wait(timeout=max_seconds)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    job['running'] = False
                    job['message'] = 'Monitor timed out'
                    job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    return
            else:
                proc.wait()

        if proc.returncode == 0:
            job['running'] = False
            job['message'] = 'Monitor completed'
            job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            job['running'] = False
            job['message'] = f'Monitor failed (exit {proc.returncode})'
            job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    except Exception as e:
        job['running'] = False
        job['message'] = f'Monitor error: {e}'
        job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@app.route('/monitor', methods=['POST'])
def monitor():
    """Start parcel monitor job"""
    job_id = uuid.uuid4().hex[:8]
    with jobs_lock:
        jobs[job_id] = {
            'running': False,
            'message': 'Queued',
            'start_time': None,
            'end_time': None,
            'file': None,
            'log': None,
            'proc': None,
            'task': 'monitor'
        }

    thread = threading.Thread(target=run_monitor_job, args=(job_id,))
    thread.daemon = True
    thread.start()

    return jsonify({'success': True, 'job_id': job_id, 'message': 'Monitor started'})


@app.route('/')
def index():
    """Home page with date picker and run button"""
    config = load_config()
    return render_template('index.html',
                           config=config,
                           excel_exists=EXCEL_FILE.exists())


@app.route('/scrape', methods=['POST'])
def scrape():
    """Start the scraping process with a uniquely named output file"""
    data = request.get_json()
    target_date = data.get('date', 'today')
    # create unique job
    job_id = uuid.uuid4().hex[:8]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_date = re.sub(r'[^0-9A-Za-z_-]', '-', target_date)
    filename = f"Return_{safe_date}_{timestamp}_{job_id}.xlsx"
    output_file = DATA_DIR / filename

    with jobs_lock:
        jobs[job_id] = {
            'task': 'scrape',
            'running': False,
            'message': 'Queued',
            'start_time': None,
            'end_time': None,
            'file': None,
            'log': None
        }

    # ensure data directory exists
    DATA_DIR.mkdir(exist_ok=True)

    # start background thread
    thread = threading.Thread(target=run_job, args=(job_id, target_date, output_file))
    thread.daemon = True
    thread.start()

    return jsonify({
        'success': True,
        'job_id': job_id,
        'message': f'Job {job_id} started',
        'file': filename
    })


@app.route('/scrape_range', methods=['POST'])
def scrape_range():
    data = request.get_json() or {}
    start = data.get('start')
    end = data.get('end')
    if not start or not end:
        return jsonify({'success': False, 'message': 'start and end are required (YYYY-MM-DD)'}), 400

    # Validate quick format
    try:
        sd = datetime.strptime(start, '%Y-%m-%d')
        ed = datetime.strptime(end, '%Y-%m-%d')
        if ed < sd:
            return jsonify({'success': False, 'message': 'End date must be on/after start date'}), 400
    except Exception:
        return jsonify({'success': False, 'message': 'Invalid date format; expected YYYY-MM-DD'}), 400

    # create unique job
    job_id = uuid.uuid4().hex[:8]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"Return_batch_{start}_to_{end}_{timestamp}_{job_id}.xlsx"
    output_file = DATA_DIR / filename

    with jobs_lock:
        jobs[job_id] = {
            'task': 'scrape-range',
            'running': False,
            'message': 'Queued',
            'start_time': None,
            'end_time': None,
            'file': None,
            'log': None
        }

    DATA_DIR.mkdir(exist_ok=True)

    thread = threading.Thread(target=run_batch_job, args=(job_id, start, end, output_file))
    thread.daemon = True
    thread.start()

    return jsonify({'success': True, 'job_id': job_id, 'message': f'Batch job {job_id} started', 'file': filename})

@app.route('/status')
def status():
    """Get current scraper status or job status if job_id provided"""
    job_id = request.args.get('job_id')
    if job_id:
        job = jobs.get(job_id)
        if not job:
            return jsonify({'success': False, 'message': 'Job not found'}), 404
        return jsonify(job)
    # overall summary
    # include lightweight job summary
    summaries = []
    for jid, j in jobs.items():
        summaries.append({
            'job_id': jid,
            'task': j.get('task', 'unknown'),
            'running': j.get('running', False),
            'message': j.get('message', '')
        })
    return jsonify({'jobs': summaries})


@app.route('/download')
def download():
    """Download a specific excel file from data directory. Use ?file=<filename>"""
    filename = request.args.get('file')
    if not filename:
        # Fallback: serve stable Return.xlsx for legacy clients
        stable = DATA_DIR / 'Return.xlsx'
        if stable.exists():
            return send_from_directory(directory=str(DATA_DIR.resolve()), path=stable.name, as_attachment=True)
        return jsonify({'success': False, 'message': 'file parameter is required and Return.xlsx not found'}), 400

    safe_path = DATA_DIR / filename
    try:
        # Ensure the requested file is inside DATA_DIR
        safe_path_resolved = safe_path.resolve()
        if DATA_DIR.resolve() not in safe_path_resolved.parents and safe_path_resolved != DATA_DIR.resolve():
            return jsonify({'success': False, 'message': 'Invalid file path'}), 400
    except Exception:
        return jsonify({'success': False, 'message': 'Invalid file path'}), 400

    if not safe_path.exists():
        return jsonify({'success': False, 'message': 'File not found'}), 404

    return send_from_directory(directory=str(DATA_DIR.resolve()), path=filename, as_attachment=True)


@app.route('/log')
def get_log():
    """Return last lines of job log. Use ?job_id=...&lines=..."""
    job_id = request.args.get('job_id')
    if not job_id:
        return jsonify({'success': False, 'message': 'job_id required'}), 400
    job = jobs.get(job_id)
    if not job:
        return jsonify({'success': False, 'message': 'Job not found'}), 404
    log_path = job.get('log')
    if not log_path:
        return jsonify({'success': False, 'message': 'Log not available'}), 404

    lines = int(request.args.get('lines', '200'))
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as lf:
            # Read last N lines efficiently
            lf.seek(0, os.SEEK_END)
            file_size = lf.tell()
            buffer = 2048
            data = ''
            while file_size > 0 and data.count('\n') <= lines:
                read_size = min(buffer, file_size)
                lf.seek(file_size - read_size)
                chunk = lf.read(read_size)
                data = chunk + data
                file_size -= read_size
            result_lines = data.splitlines()[-lines:]
            return jsonify({'success': True, 'log': '\n'.join(result_lines)})
    except FileNotFoundError:
        return jsonify({'success': False, 'message': 'Log file not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/cancel', methods=['POST'])
def cancel_job():
    data = request.get_json() or {}
    job_id = data.get('job_id')
    if not job_id:
        return jsonify({'success': False, 'message': 'job_id required'}), 400
    # Acquire lock to read/modify job state
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({'success': False, 'message': 'Job not found'}), 404
        proc = job.get('proc')
        # mark that cancellation was requested
        job['cancel_requested'] = True

    if not proc:
        # nothing to kill; ensure job state updated
        with jobs_lock:
            job['running'] = False
            job['message'] = 'Not running'
            job['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return jsonify({'success': False, 'message': 'Job not running'}), 400

    # Try to kill the process; best-effort container removal follows
    try:
        try:
            proc.kill()
        except Exception:
            # ignore kill errors but continue updating state
            pass

        with jobs_lock:
            job['running'] = False
            job['message'] = 'Cancelled by user'
            job['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            job['proc'] = None

        # Best-effort: remove docker container started for this job (if named)
        container_name = job.get('container')
        if container_name:
            try:
                # prefer direct docker command to remove container
                if shutil.which('docker'):
                    subprocess.run(['docker', 'rm', '-f', container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    # fallback: docker-compose rm -f
                    subprocess.run(['docker-compose', 'rm', '-f', container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

        # Prepare a safe job summary to return (avoid returning unserializable objects)
        with jobs_lock:
            js = {
                'job_id': job_id,
                'running': job.get('running', False),
                'message': job.get('message', ''),
                'start_time': job.get('start_time'),
                'end_time': job.get('end_time'),
                'file': job.get('file')
            }
        return jsonify({'success': True, 'message': f'Job {job_id} cancelled', 'job': js})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/file_log')
def get_file_log():
    """Return last lines of a log derived from a given output file name.
    Use ?file=<Return_xxx_<jobid>.xlsx>&lines=...
    """
    filename = request.args.get('file', '')
    if not filename:
        return jsonify({'success': False, 'message': 'file required'}), 400

    # Expect job id is the last underscore-delimited token before extension
    m = re.match(r"^.+_([0-9a-fA-F]{8})\.xlsx$", filename)
    if not m:
        return jsonify({'success': False, 'message': 'Could not infer job id from filename'}), 400
    job_id = m.group(1)
    log_path = DATA_DIR / f"job_{job_id}.log"

    if not log_path.exists():
        return jsonify({'success': False, 'message': 'Log file not found'}), 404

    lines = int(request.args.get('lines', '200'))
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as lf:
            lf.seek(0, os.SEEK_END)
            file_size = lf.tell()
            buffer = 2048
            data = ''
            while file_size > 0 and data.count('\n') <= lines:
                read_size = min(buffer, file_size)
                lf.seek(file_size - read_size)
                chunk = lf.read(read_size)
                data = chunk + data
                file_size -= read_size
            result_lines = data.splitlines()[-lines:]
            return jsonify({'success': True, 'log': '\n'.join(result_lines)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/config', methods=['GET', 'POST'])
def config():
    """Configuration page for credentials (SteadFast + Automate Returns + Parcel WebApp URL)"""
    if request.method == 'POST':
        data = request.get_json() or {}
        current = load_config()

        username = data.get('username', None)
        password = data.get('password', None)
        admin_email = data.get('admin_email', None)
        admin_password = data.get('admin_password', None)
        webapp_url = data.get('webapp_url', None)
        courier_webapp_url = data.get('courier_webapp_url', None)

        # If one of a pair is provided, the other must be provided too
        if (username is not None) ^ (password is not None):
            return jsonify({"success": False, "message": "Both SteadFast username and password must be provided together."}), 400
        if (admin_email is not None) ^ (admin_password is not None):
            return jsonify({"success": False, "message": "Both Admin email and password must be provided together."}), 400

        # Fill with existing if None
        if username is None:
            username = current.get('username', '')
        if password is None:
            password = current.get('password', '')
        if admin_email is None:
            admin_email = current.get('admin_email', '')
        if admin_password is None:
            admin_password = current.get('admin_password', '')
        if webapp_url is None:
            webapp_url = current.get('webapp_url', '')
        if courier_webapp_url is None:
            courier_webapp_url = current.get('courier_webapp_url', '')

        google_web_app_url = data.get('google_web_app_url', None)
        save_config(username, password, admin_email, admin_password, webapp_url, courier_webapp_url, google_web_app_url)

        return jsonify({
            "success": True,
            "message": "Configuration saved successfully"
        })

    # GET request - return current config
    config_data = load_config()
    return jsonify(config_data)


@app.route('/jobs')
def jobs_list():
    summaries = []
    for jid, j in jobs.items():
        summaries.append({
            'job_id': jid,
            'task': j.get('task', j.get('task') or j.get('message','unknown')),
            'running': j.get('running', False),
            'message': j.get('message','')
        })
    # sort by start_time or job_id
    return jsonify({'jobs': summaries})


@app.route('/files')
def list_files():
    """List all Excel files in data directory with inferred job id and log availability"""
    if not DATA_DIR.exists():
        return jsonify({"files": []})

    files = []
    for file in DATA_DIR.glob("*.xlsx"):
        # infer job id from filename (last _ segment, 8 hex chars)
        job_id = None
        m = re.match(r"^.+_([0-9a-fA-F]{8})\.xlsx$", file.name)
        if m:
            job_id = m.group(1)
        log_path = DATA_DIR / f"job_{job_id}.log" if job_id else None
        files.append({
            "name": file.name,
            "size": file.stat().st_size,
            "modified": datetime.fromtimestamp(file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "job_id": job_id,
            "has_log": bool(log_path and log_path.exists())
        })

    # sort by modified desc
    files.sort(key=lambda f: f['modified'], reverse=True)

    return jsonify({"files": files})


# Parcel Update job runner

def run_parcel_job(job_id):
    job = jobs[job_id]
    job['running'] = True
    job['message'] = 'Parcel Status Update started...'
    job['start_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log_path = DATA_DIR / f"job_{job_id}.log"
    job['log'] = str(log_path)

    post_env = os.environ.copy()
    # Push credentials and WEBAPP_URL from config
    try:
        conf = load_config()
        if conf.get('username'):
            post_env['STEADFAST_USERNAME'] = conf.get('username')
        if conf.get('password'):
            post_env['STEADFAST_PASSWORD'] = conf.get('password')
        if conf.get('webapp_url'):
            post_env['WEBAPP_URL'] = conf.get('webapp_url')
    except Exception:
        pass
    post_env['PYTHONUNBUFFERED'] = '1'

    cmd = [
        sys.executable, '-u', 'Parcel Update.py'
    ]

    try:
        with open(log_path, 'w', encoding='utf-8') as lf:
            proc = subprocess.Popen(cmd, env=post_env, stdout=lf, stderr=lf)
            proc.wait()

        if proc.returncode == 0:
            job['running'] = False
            job['message'] = 'Parcel update completed successfully'
            job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            job['running'] = False
            job['message'] = f'Parcel update failed (exit {proc.returncode})'
            job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        job['running'] = False
        job['message'] = f'Parcel update error: {e}'
        job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@app.route('/parcel', methods=['POST'])
def parcel():
    """Start the Parcel Update processing job"""
    job_id = uuid.uuid4().hex[:8]
    with jobs_lock:
        jobs[job_id] = {
            'task': 'parcel',
            'running': False,
            'message': 'Queued',
            'start_time': None,
            'end_time': None,
            'file': None,
            'log': None
        }
    thread = threading.Thread(target=run_parcel_job, args=(job_id,))
    thread.daemon = True
    thread.start()
    return jsonify({'success': True, 'job_id': job_id, 'message': f'Parcel job {job_id} started'})


# Moderator's Name Scrapper job runner

def run_moderator_name_scraper_job(job_id):
    job = jobs[job_id]
    job['running'] = True
    job['message'] = "Moderator's Name Scrapper started..."
    job['start_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log_path = DATA_DIR / f"job_{job_id}.log"
    job['log'] = str(log_path)

    env = os.environ.copy()
    try:
        conf = load_config()
        if conf.get('admin_email'):
            env['ADMIN_EMAIL'] = conf.get('admin_email')
        if conf.get('admin_password'):
            env['ADMIN_PASSWORD'] = conf.get('admin_password')
        # Use the same WebApp URL setting as Parcel Update
        if conf.get('webapp_url'):
            env['WEBAPP_URL'] = conf.get('webapp_url')
    except Exception:
        pass
    env['PYTHONUNBUFFERED'] = '1'

    cmd = [sys.executable, '-u', 'name_script.py']

    try:
        with open(log_path, 'w', encoding='utf-8') as lf:
            proc = subprocess.Popen(cmd, env=env, stdout=lf, stderr=lf)
            proc.wait()

        if proc.returncode == 0:
            job['running'] = False
            job['message'] = "Moderator's Name Scrapper completed successfully"
            job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            job['running'] = False
            job['message'] = f"Moderator's Name Scrapper failed (exit {proc.returncode})"
            job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        job['running'] = False
        job['message'] = f"Moderator's Name Scrapper error: {e}"
        job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@app.route('/moderator_name_scraper', methods=['POST'])
def moderator_name_scraper():
    """Start Moderator's Name Scrapper job"""
    job_id = uuid.uuid4().hex[:8]
    with jobs_lock:
        jobs[job_id] = {
            'task': 'moderator-name-scraper',
            'running': False,
            'message': 'Queued',
            'start_time': None,
            'end_time': None,
            'file': None,
            'log': None
        }
    thread = threading.Thread(target=run_moderator_name_scraper_job, args=(job_id,))
    thread.daemon = True
    thread.start()
    return jsonify({'success': True, 'job_id': job_id, 'message': f"Moderator's Name Scrapper job {job_id} started"})


# Courier charge & payment updates job runner

def run_courier_receive_updates_job(job_id):
    job = jobs[job_id]
    job['running'] = True
    job['message'] = 'Courier Charge & Payment Updates started...'
    job['start_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log_path = DATA_DIR / f"job_{job_id}.log"
    job['log'] = str(log_path)

    post_env = os.environ.copy()
    try:
        conf = load_config()
        if conf.get('username'):
            post_env['STEADFAST_USERNAME'] = conf.get('username')
        if conf.get('password'):
            post_env['STEADFAST_PASSWORD'] = conf.get('password')
        if conf.get('webapp_url'):
            post_env['WEBAPP_URL'] = conf.get('webapp_url')
    except Exception:
        pass
    post_env['PYTHONUNBUFFERED'] = '1'
    # Ensure courier_receive_updater can save merged XLSX into the app data directory
    try:
        post_env['DATA_DIR'] = str(DATA_DIR.resolve())
    except Exception:
        post_env['DATA_DIR'] = str(DATA_DIR)

    cmd = [sys.executable, '-u', 'courier_receive_updater.py']

    try:
        # snapshot existing XLSX files so we can detect new merged files created by the job
        existing_files_before = {}
        try:
            if DATA_DIR.exists():
                for f in DATA_DIR.glob('*.xlsx'):
                    existing_files_before[f.name] = f.stat().st_mtime
        except Exception:
            existing_files_before = {}

        with open(log_path, 'w', encoding='utf-8') as lf:
            proc = subprocess.Popen(cmd, env=post_env, stdout=lf, stderr=lf)
            proc.wait()

        if proc.returncode == 0:
            # detect any new/updated .xlsx files in DATA_DIR and attach to job record
            new_files = []
            try:
                if DATA_DIR.exists():
                    for f in DATA_DIR.glob('*.xlsx'):
                        mtime = f.stat().st_mtime
                        prev = existing_files_before.get(f.name)
                        if not prev or mtime > prev:
                            new_files.append((f.name, mtime))
                # sort by mtime desc
                new_files.sort(key=lambda x: x[1], reverse=True)
                file_names = [n for n, _ in new_files]
                if file_names:
                    job['files'] = file_names
                    job['file'] = file_names[0]
            except Exception:
                pass

            job['running'] = False
            job['message'] = 'Courier charge & payment updates completed successfully'
            job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            job['running'] = False
            job['message'] = f'Courier charge & payment updates failed (exit {proc.returncode})'
            job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        job['running'] = False
        job['message'] = f'Courier charge & payment updates error: {e}'
        job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@app.route('/courier_receive_updates', methods=['POST'])
def courier_receive_updates():
    """Start Courier Charge & Payment Updates job"""
    job_id = uuid.uuid4().hex[:8]
    with jobs_lock:
        jobs[job_id] = {
            'task': 'courier-receive-updates',
            'running': False,
            'message': 'Queued',
            'start_time': None,
            'end_time': None,
            'file': None,
            'log': None
        }
    thread = threading.Thread(target=run_courier_receive_updates_job, args=(job_id,))
    thread.daemon = True
    thread.start()
    return jsonify({'success': True, 'job_id': job_id, 'message': f'Courier updates job {job_id} started'})

# Courier Shipment job runner

def run_courier_job(job_id, date=None):
    job = jobs[job_id]
    job['running'] = True
    job['message'] = "Shipment's Data Scraper started..."
    job['start_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log_path = DATA_DIR / f"job_{job_id}.log"
    job['log'] = str(log_path)

    env = os.environ.copy()
    try:
        conf = load_config()
        if conf.get('admin_email'):
            env['ADMIN_EMAIL'] = conf.get('admin_email')
        if conf.get('admin_password'):
            env['ADMIN_PASSWORD'] = conf.get('admin_password')
        if conf.get('courier_webapp_url'):
            env['COURIER_WEBAPP_URL'] = conf.get('courier_webapp_url')
    except Exception:
        pass
    env['PYTHONUNBUFFERED'] = '1'
    if date:
        env['TARGET_DATE'] = date

    cmd = [sys.executable, '-u', 'website_script.py']

    try:
        with open(log_path, 'w', encoding='utf-8') as lf:
            proc = subprocess.Popen(cmd, env=env, stdout=lf, stderr=lf)
            proc.wait()
        if proc.returncode == 0:
            job['running'] = False
            job['message'] = "Shipment's data scraper completed successfully"
            job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            job['running'] = False
            job['message'] = f"Shipment's data scraper failed (exit {proc.returncode})"
            job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        job['running'] = False
        job['message'] = f"Shipment's data scraper error: {e}"
        job['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@app.route('/shipment', methods=['POST'])
def shipment():
    data = request.get_json() or {}
    date = data.get('date')
    if not date:
        return jsonify({'success': False, 'message': 'No date provided for shipment data.'}), 400
    job_id = uuid.uuid4().hex[:8]
    with jobs_lock:
        jobs[job_id] = {
            'task': 'shipment',
            'running': False,
            'message': 'Queued',
            'start_time': None,
            'end_time': None,
            'file': None,
            'log': None,
            'date': date
        }
    thread = threading.Thread(target=run_courier_job, args=(job_id, date))
    thread.daemon = True
    thread.start()
    return jsonify({'success': True, 'job_id': job_id, 'message': f"Shipment job {job_id} started"})
@app.route('/jobs', methods=['GET'])
def list_jobs():
    """Return all known jobs with minimal info for UI tabs"""
    out = []
    for jid, j in jobs.items():
        out.append({
            'job_id': jid,
            'task': j.get('task', 'unknown'),
            'running': j.get('running', False),
            'message': j.get('message', ''),
            'start_time': j.get('start_time'),
            'end_time': j.get('end_time'),
            'file': j.get('file')
        })
    # newest first (by start_time string if present)
    out.sort(key=lambda x: x.get('start_time') or '', reverse=True)
    return jsonify({'jobs': out})

def safe_path(rel_path: str) -> Path:
    rel_path = (rel_path or '').lstrip('/\\')
    target = (PROJECT_ROOT / rel_path).resolve()
    root = PROJECT_ROOT.resolve()

    try:
        target.relative_to(root)
    except Exception:
        raise ValueError('Invalid path')

    return target


def _require_fs_unlocked():
    if not session.get('fs_unlocked'):
        return jsonify({'success': False, 'message': 'Advance Config is locked'}), 401
    return None


@app.route('/fs/unlock', methods=['POST'])
def fs_unlock():
    data = request.get_json(silent=True) or {}
    pin = str(data.get('pin', '')).strip()
    if pin == '863091619':
        session['fs_unlocked'] = True
        return jsonify({'success': True})
    session['fs_unlocked'] = False
    return jsonify({'success': False, 'message': 'Invalid PIN'}), 401


@app.route('/fs/list', methods=['GET'])
def fs_list():
    locked = _require_fs_unlocked()
    if locked:
        return locked
    rel = request.args.get('path', '')
    try:
        p = safe_path(rel)
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid path'}), 400

    if not p.exists():
        return jsonify({'success': False, 'message': 'Not found'}), 404
    if not p.is_dir():
        return jsonify({'success': False, 'message': 'Not a directory'}), 400

    items = []
    for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        try:
            child_rel = child.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
        except Exception:
            continue
        st = child.stat()
        modified = datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        items.append({
            'name': child.name,
            'path': child_rel,
            'type': ('dir' if child.is_dir() else 'file'),
            'size': (st.st_size if child.is_file() else 0),
            'modified': modified
        })

    return jsonify({'success': True, 'path': rel or '', 'items': items})


@app.route('/fs/read', methods=['GET'])
def fs_read():
    locked = _require_fs_unlocked()
    if locked:
        return locked
    rel = request.args.get('path', '')
    if not rel:
        return jsonify({'success': False, 'message': 'path is required'}), 400

    try:
        p = safe_path(rel)
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid path'}), 400

    if not p.exists():
        return jsonify({'success': False, 'message': 'Not found'}), 404
    if not p.is_file():
        return jsonify({'success': False, 'message': 'Not a file'}), 400

    try:
        content = p.read_text(encoding='utf-8', errors='replace')
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to read file: {e}'}), 500

    return jsonify({'success': True, 'path': rel, 'content': content})


@app.route('/fs/write', methods=['POST'])
def fs_write():
    locked = _require_fs_unlocked()
    if locked:
        return locked
    data = request.get_json(silent=True) or {}
    rel = data.get('path', '')
    content = data.get('content', '')
    if not rel:
        return jsonify({'success': False, 'message': 'path is required'}), 400

    if not isinstance(content, str):
        return jsonify({'success': False, 'message': 'content must be a string'}), 400

    if len(content.encode('utf-8', errors='replace')) > 1024 * 1024:
        return jsonify({'success': False, 'message': 'File too large (max 1MB)'}), 413

    try:
        p = safe_path(rel)
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid path'}), 400

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding='utf-8')
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to write file: {e}'}), 500

    return jsonify({'success': True, 'path': rel})


if __name__ == '__main__':
    DATA_DIR.mkdir(exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5000)
