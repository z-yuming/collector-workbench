"""Launch a relocatable Windows workbench without installing system services."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'data/launcher.json'


def health(port):
    try:
        with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
            return json.load(response)
    except Exception:
        return {}


def available_port(start):
    for port in range(start, start + 200, 10):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    raise RuntimeError('No local port is available. Close an old workbench and retry.')


def saved_instance():
    try:
        state = json.loads(STATE.read_text(encoding='utf-8'))
        status = health(state['port'])
        if status.get('pid') == state['pid'] and Path(status.get('projectRoot', '')).resolve() == ROOT:
            return state
    except (OSError, ValueError, KeyError):
        pass
    return None


def environment(ports):
    runtime = ROOT / 'runtime'
    return {
        **os.environ,
        'COLLECTOR_PORTABLE': '1',
        'COLLECTOR_PROJECT_ROOT': str(ROOT),
        'COLLECTOR_PYTHON': str(runtime / 'python311/python.exe'),
        'SCRAPER_WORKBENCH_PORT': str(ports['scraper']),
        'SCRAPER_UI_PORT': str(ports['scraper']),
        'VIDEO_DOWNLOAD_HELPER_PORT': str(ports['helper']),
        'VIDEO_HELPER_PYTHON': str(runtime / 'python311/python.exe'),
        'VIDEO_PARSER_PYTHON': str(runtime / 'video313/python.exe'),
        'MEDIA_CRAWLER_PYTHON': str(runtime / 'media311/python.exe'),
        'PLAYWRIGHT_BROWSERS_PATH': str(runtime / 'browsers'),
        'PYTHONIOENCODING': 'utf-8',
        'PYTHONPATH': str(ROOT / 'src'),
        'PATH': str(runtime / 'node') + os.pathsep + str(ROOT / 'platform-tools') + os.pathsep + os.environ.get('PATH', ''),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-open-browser', action='store_true')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    existing = saved_instance()
    if args.stop:
        if existing:
            subprocess.run(['taskkill.exe', '/PID', str(existing['pid']), '/T', '/F'], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            STATE.unlink(missing_ok=True)
        return
    if existing:
        if not args.no_open_browser:
            webbrowser.open(f"http://127.0.0.1:{existing['port']}/")
        return
    python = ROOT / 'runtime/python311/python.exe'
    if not python.is_file():
        raise RuntimeError('Runtime missing. Download the Windows portable ZIP from Releases and extract the whole folder.')
    ports = {'main': available_port(args.port), 'scraper': available_port(5566), 'helper': available_port(8766)}
    logs = ROOT / 'data/logs'
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / 'launcher.log').open('ab') as output:
        process = subprocess.Popen([str(python), '-m', 'social_crawler.cli', 'app', '--host', '127.0.0.1', '--port', str(ports['main']), '--no-open-browser'], cwd=ROOT, env=environment(ports), stdout=output, stderr=output, creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(60):
        status = health(ports['main'])
        if status.get('pid') == process.pid and Path(status.get('projectRoot', '')).resolve() == ROOT:
            STATE.write_text(json.dumps({'pid':process.pid, 'port':ports['main'], 'ports':ports}), encoding='utf-8')
            if not args.no_open_browser:
                webbrowser.open(f"http://127.0.0.1:{ports['main']}/")
            return
        if process.poll() is not None:
            break
        time.sleep(.25)
    if process.poll() is None:
        process.terminate()
    raise RuntimeError('Workbench could not start. See data/logs/launcher.log for the error.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        if sys.stdout is not None:
            print(str(error), file=sys.stderr)
        else:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(error), 'Collector Workbench', 0x10)
        raise SystemExit(1)
