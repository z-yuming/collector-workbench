"""Build an allowlisted source snapshot and a Windows x64 portable ZIP.

Never copy histories, credentials, browser profiles, old archives or Git metadata.
Run with the current main environment on the maintained Windows build machine.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.3.0'
HELPER = 'tools/VideoDownloadHelper-windows-v0.2.4-20260706-141912'
SKIP_DIRS = {'.git', '.venv', 'venv', '__pycache__', '.cache', 'node_modules', 'data', 'cookies', 'downloads', 'browser_profile', 'browser_data', 'schedule_jobs', 'captured-media', 'logs', 'crawler_output', 'exports', 'raw', 'screenshots'}
SOURCE_SUFFIXES = {'.py','.js','.html','.css','.json','.toml','.txt','.md','.yml','.yaml','.xml','.sql','.svg','.png','.ico','.cmd','.ps1','.lock'}


def copy_source_tree(source, destination):
    for folder, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS and not name.startswith('.') and not name.endswith(('.egg-info','.dist-info'))]
        for name in files:
            path = Path(folder) / name
            if path.is_symlink() or path.suffix.lower() not in SOURCE_SUFFIXES and path.name != 'LICENSE':
                continue
            if path.name.startswith('.') or any(word in path.name.lower() for word in ('cookie', 'tracked_videos', 'screenshot', 'install_log', 'install_err')):
                continue
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def source_snapshot(destination):
    destination.mkdir(parents=True, exist_ok=True)
    for name in ['src','tests','docs/third-party']:
        copy_source_tree(ROOT/name, destination/name)
    for name in ['pyproject.toml','requirements.txt','requirements-main.lock.txt','requirements-video.lock.txt','requirements-media.lock.txt','requirements-helper.lock.txt','README.md','THIRD_PARTY_NOTICES.md','LICENSE','Start-Workbench.cmd','Stop-Workbench.cmd','Start-Video-Login.cmd']:
        shutil.copy2(ROOT/name,destination/name)
    for name in ['portable_launcher.py','build_portable.py','Check-Workbench.ps1']:
        (destination/'scripts').mkdir(exist_ok=True)
        shutil.copy2(ROOT/'scripts'/name,destination/'scripts'/name)
    (destination/'.gitignore').write_text('data/\nruntime/\nrelease/\nbackups/\n.venv/\n**/__pycache__/\n**/cookies/\n**/downloads/\n**/browser_profile/\n**/browser_data/\n**/data.db*\n**/*.sqlite*\n**/douyin_cookie.txt\n**/config.json\n**/schedule_jobs/\n.env\n*.log\n',encoding='utf-8')
    scraper = destination/'modules/scraper'
    scraper.mkdir(parents=True,exist_ok=True)
    for name in ['app.py','vision_client.py','vision_api_server.py','crawler_requirements.txt']:
        shutil.copy2(ROOT/'modules/scraper'/name,scraper/name)
    for name in ['shared','static','templates','crawler_scripts','douyin_crawler']:
        copy_source_tree(ROOT/'modules/scraper'/name,scraper/name)
    media_source = ROOT/'modules/scraper/media_crawler'
    media_target = scraper/'media_crawler'
    for name in ['api','base','cache','cmd_arg','config','constant','database','libs','media_platform','model','proxy','store','tools']:
        copy_source_tree(media_source/name,media_target/name)
    for name in ['main.py','var.py','LICENSE','README.md','pyproject.toml','requirements.txt','package.json','package-lock.json','uv.lock']:
        target=media_target/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(media_source/name,target)
    video = destination/'modules/video-parser';video.mkdir(parents=True,exist_ok=True)
    for name in ['hermes_douyin.py','douyin_video_parser.py','abogus.py','xbogus.py','qt_app.py','qt_app_slim.py','README.md']:
        shutil.copy2(ROOT/'modules/video-parser'/name,video/name)
    copy_source_tree(ROOT/HELPER/'capture-server',destination/HELPER/'capture-server')
    copy_source_tree(ROOT/HELPER/'video-download-helper-extension',destination/HELPER/'video-download-helper-extension')
    helper_server = destination/HELPER/'capture-server/capture_server.py'
    text=helper_server.read_text(encoding='utf-8')
    text=text.replace('server = ThreadingHTTPServer(("127.0.0.1", 8766), Handler)', 'port = int(os.environ.get("VIDEO_DOWNLOAD_HELPER_PORT", "8766"))\n    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)')
    text=text.replace('print("capture server listening on http://127.0.0.1:8766")','print(f"capture server listening on http://127.0.0.1:{port}")')
    helper_server.write_text(text,encoding='utf-8')
    (destination/HELPER/'start_windows.bat').write_text('@echo off\r\n"%~dp0..\\..\\runtime\\python311\\python.exe" "%~dp0capture-server\\capture_server.py"\r\n',encoding='ascii')
    config={'project_root':'.','adb_path':'platform-tools/adb.exe','output_dir':'data/exports','log_dir':'data/logs','screenshot_dir':'data/screenshots','raw_dir':'data/raw','default_serial':None,'enable_mitm':False,'platforms':{name:{'package_name':package} for name,package in {'douyin':'com.ss.android.ugc.aweme','taobao':'com.taobao.taobao','jd':'com.jingdong.app.mall','pinduoduo':'com.xunmeng.pinduoduo'}.items()}}
    (destination/'config').mkdir(exist_ok=True);(destination/'config/settings.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    (destination/'examples').mkdir(exist_ok=True);shutil.copy2(ROOT/'tests/fixtures/generic_social_public.html',destination/'examples/local-demo.html')
    audit_source(destination)


def audit_source(root):
    failures=[]
    forbidden = re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)')
    for path in root.rglob('*'):
        if not path.is_file(): continue
        rel=path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts) or path.suffix in {'.db','.sqlite','.sqlite3','.xlsx','.csv','.jsonl'}:
            failures.append(str(rel)+' forbidden runtime data')
        if path.suffix in {'.py','.js','.json','.txt','.md','.html'}:
            text=path.read_text(encoding='utf-8-sig',errors='replace')
            if forbidden.search(text): failures.append(str(rel)+' credential-like content')
        if path.suffix=='.py':
            tree=ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node,ast.Assign) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):
                    names=[n.id.lower() for n in node.targets if isinstance(n,ast.Name)]
                    if names and any(name in {'cookies','cookie','api_key','secret_key','access_token','refresh_token'} for name in names) and len(node.value.value)>12:
                        failures.append(f'{rel}:{node.lineno} hardcoded credential field')
    if failures: raise RuntimeError('Publication audit failed: '+ '; '.join(failures))
    print('Source audit passed:',sum(1 for p in root.rglob('*') if p.is_file()),'allowlisted files',flush=True)


def copy_runtime(base, site, target, source_paths):
    target.mkdir(parents=True,exist_ok=True)
    for name in ['python.exe','pythonw.exe','python3.dll','python311.dll','python313.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt']:
        if (base/name).is_file(): shutil.copy2(base/name,target/name)
    for name in ['DLLs','Lib','tcl']:
        if (base/name).is_dir():
            shutil.copytree(base/name,target/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('site-packages','__pycache__','test','tests','idlelib','ensurepip'))
    shutil.copytree(site,target/'Lib/site-packages',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pth','*.egg-link','direct_url.json','__editable__*','social_data_crawler*','douyin_product_crawler*'))
    version='313' if (target/'python313.dll').is_file() else '311'
    (target/f'python{version}._pth').write_text('\n'.join(['DLLs','Lib','Lib/site-packages',*source_paths,'import site'])+'\n',encoding='utf-8')
    print('Runtime copied:',target.name,flush=True)


def portable_files(source, destination):
    shutil.copytree(source,destination)
    runtime=destination/'runtime';runtime.mkdir()
    copy_runtime(Path(sys.base_prefix),ROOT/'.venv/Lib/site-packages',runtime/'python311',['../../src','../../modules/scraper',f'../../{HELPER}/capture-server'])
    helper_site=ROOT/'data/video-helper/runtime/.venv/Lib/site-packages'
    for name in ['imageio_ffmpeg','imageio_ffmpeg-0.6.0.dist-info']:
        if (helper_site/name).is_dir(): shutil.copytree(helper_site/name,runtime/'python311/Lib/site-packages'/name,ignore=shutil.ignore_patterns('__pycache__'))
    copy_runtime(Path(sys.base_prefix),ROOT/'modules/scraper/media_crawler/.venv/Lib/site-packages',runtime/'media311',['../../modules/scraper/media_crawler'])
    copy_runtime(ROOT/'runtimes/python313',ROOT/'modules/video-parser/venv/Lib/site-packages',runtime/'video313',['../../modules/video-parser'])
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p: browser_root=Path(p.chromium.executable_path).parents[2]
    media_cfg=json.loads((ROOT/'modules/scraper/media_crawler/.venv/Lib/site-packages/playwright/driver/package/browsers.json').read_text(encoding='utf-8'))
    main_cfg=json.loads((ROOT/'.venv/Lib/site-packages/playwright/driver/package/browsers.json').read_text(encoding='utf-8'))
    video_cfg=json.loads((ROOT/'modules/video-parser/venv/Lib/site-packages/playwright/driver/package/browsers.json').read_text(encoding='utf-8'))
    browser_names={f"{b['name'].replace('-','_')}-{b['revision']}" for config in (media_cfg,main_cfg,video_cfg) for b in config['browsers'] if b['name'] in {'chromium','chromium-headless-shell','ffmpeg','winldd'}}
    for name in sorted(browser_names):
        candidate=ROOT/'release/browser-cache'/name
        if not candidate.is_dir(): candidate=browser_root/name
        if not candidate.is_dir(): candidate=Path(os.environ.get('LOCALAPPDATA',''))/'ms-playwright'/name
        if not candidate.is_dir(): candidate=ROOT/'release/browser-cache'/name
        if not candidate.is_dir(): raise RuntimeError('Required installed browser missing: '+name)
        shutil.copytree(candidate,runtime/'browsers'/name,ignore=shutil.ignore_patterns('__pycache__'))
        print('Browser copied:',name,flush=True)
    (runtime/'node').mkdir();shutil.copy2(Path(shutil.which('node.exe')),runtime/'node/node.exe')
    node_license=Path(shutil.which('node.exe')).parent/'LICENSE'
    if not node_license.exists(): node_license=ROOT/'release/licenses/Node-LICENSE.txt'
    if node_license.exists():shutil.copy2(node_license,runtime/'node/LICENSE')
    adb=destination/'platform-tools';adb.mkdir()
    for name in ['adb.exe','AdbWinApi.dll','AdbWinUsbApi.dll','NOTICE.txt','source.properties']:
        shutil.copy2(ROOT/'platform-tools'/name,adb/name)
    (destination/'data').mkdir()
    (destination/'README-FIRST.txt').write_text('采集工作台 Windows 64位便携版\n\n1. 解压整个压缩包到可写的目录。\n2. 双击 Start-Workbench.cmd。无需安装 Python、Node 或管理员服务。\n3. 页面打开后先执行采集前检查。账号由你自己登录，手机需要连接并授权USB调试。\n4. 双击 Stop-Workbench.cmd 可停止本包启动的服务。\n5. 所有结果与账号配置保存在本文件夹，升级前保留 data、cookies 和浏览器登录目录。\n\n演示采集：公开网页 + 已保存网页，填写 examples/local-demo.html，关闭评论后采集。\n\n浏览器视频捕获：Chrome/Edge需手动加载 tools 内的 video-download-helper-extension；分享链接解析不需要加载此扩展。\n\n完整说明、功能边界和第三方许可见 README.md 与 THIRD_PARTY_NOTICES.md。\n',encoding='utf-8-sig')
    print('Portable folder complete:',destination,flush=True)


def archive(directory,path):
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as output:
        paths=[p for p in directory.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.log'}]
        for index,file in enumerate(paths):
            output.write(file,directory.name+'/'+file.relative_to(directory).as_posix())
            if index and index%2000==0:print('ZIP progress:',index,'/',len(paths),flush=True)
    with path.open('rb') as input_file:
        digest=hashlib.file_digest(input_file,'sha256').hexdigest()
    path.with_suffix(path.suffix+'.sha256').write_text(digest+'  '+path.name+'\n',encoding='ascii')
    print('ZIP ready:',path.name,round(path.stat().st_size/1024**2,1),'MB',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['source','runtime','zip'],required=True)
    args=parser.parse_args();release=ROOT/'release';release.mkdir(exist_ok=True)
    source=release/'source';portable=release/f'CollectorWorkbench-{VERSION}-windows-x64'
    if args.stage=='source': source_snapshot(source)
    elif args.stage=='runtime': portable_files(source,portable)
    else: archive(portable,release/(portable.name+'.zip'))
