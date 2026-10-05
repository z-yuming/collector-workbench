from __future__ import annotations

import ctypes
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

from social_crawler import preflight, results, workbench, web_app
from social_crawler.settings import Settings
from social_crawler.task_runtime import TaskManager, ProcessTree
from social_crawler.task_store import TaskStore, ACTIVE
from social_crawler.task_worker import execute


def test_settings(root):
    return Settings(project_root=root, output_dir=root/'exports', log_dir=root/'logs', raw_dir=root/'raw', screenshot_dir=root/'screenshots', adb_path=root/'missing-adb.exe')


def sample_payload():
    return {'platform':'sample','mode':'sample','taskType':'keyword','query':'local acceptance','limit':2,'maxPages':1,'comments':False,'checkEvidence':False}


class ManagedTaskTest(unittest.TestCase):
    def test_preflight_blocks_only_phone_mode_when_device_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); settings=test_settings(root)
            phone=preflight.check_task('collect',{'platform':'jd','mode':'adb','taskType':'products','query':'local'},settings)
            self.assertFalse(phone['ready'])
            html=root/'source.html'; html.write_text('<title>Local</title>',encoding='utf-8')
            local=preflight.check_task('collect',{'platform':'generic_web','mode':'html','taskType':'content','query':str(html)},settings)
            self.assertTrue(local['ready'])
            self.assertFalse(any(c['key']=='device' for c in local['checks']))

    def test_preflight_checks_selected_platform_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); settings=test_settings(root); settings.adb_path.touch()
            with patch.object(web_app,'run_adb',side_effect=[{'returncode':0,'stdout':'List of devices attached\nphone1\tdevice\n'}, {'returncode':0,'stdout':'package:/app/jd/base.apk'}]) as adb:
                result=preflight.check_task('collect',{'platform':'jd','mode':'adb','taskType':'products','query':'local'},settings)
            self.assertTrue(result['ready']); self.assertEqual(result['payload']['serial'],'phone1')
            self.assertEqual(adb.call_args.args[1][-1],'com.jingdong.app.mall')
            self.assertEqual(next(c for c in result['checks'] if c['key']=='login')['status'],'warning')

    def test_worker_failure_is_persistent_and_video_credentials_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); settings=test_settings(root); store=TaskStore.for_settings(settings)
            task=store.create('video',{'action':'parse','url':'https://www.douyin.com/video/1'},settings,'video')
            store.update(task['id'],status='running')
            with patch('social_crawler.task_worker.check_task',return_value={'ready':True}), patch.object(workbench,'run_video',side_effect=RuntimeError('视频处理超时，请重试。')):
                execute(store,task['id'])
            saved=store.get(task['id']); self.assertEqual(saved['status'],'failed'); self.assertIn('超时',saved['message'])
            with patch.object(workbench,'SCRAPER_ROOT',root),patch.object(workbench,'VIDEO_ROOT',root):
                listing=results.list_results(settings,source='video',status='failed')
            self.assertEqual(listing['total'],1)

    def test_cancellation_wins_over_a_late_success_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); settings=test_settings(root); store=TaskStore.for_settings(settings)
            task=store.create('collect',sample_payload(),settings,'browser')
            store.update(task['id'],status='running'); store.update(task['id'],status='cancelling')
            store.update(task['id'],expected={'running'},status='success',ok=True)
            self.assertEqual(store.get(task['id'])['status'],'cancelling')

    def test_restart_preserves_queued_and_marks_running_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); settings=test_settings(root); store=TaskStore.for_settings(settings)
            queued=store.create('collect',sample_payload(),settings,'browser')
            running=store.create('collect',sample_payload(),settings,'browser'); store.update(running['id'],status='running')
            store.recover()
            self.assertEqual(store.get(queued['id'])['status'],'queued')
            self.assertEqual(store.get(running['id'])['status'],'interrupted')

    def test_real_worker_exports_and_idempotent_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); settings=test_settings(root); manager=TaskManager(settings)
            try:
                task=manager.submit('collect',sample_payload(),request_key='fixture-request')
                again=manager.submit('collect',sample_payload(),request_key='fixture-request')
                self.assertEqual(task['id'],again['id'])
                result=manager.store.wait(task['id'],timeout=20)
                self.assertEqual(result['status'],'success',result.get('message'))
                self.assertGreater(result['counts']['contents'],0)
                self.assertTrue(list(settings.output_dir.glob('*.xlsx')))
                self.assertEqual(manager.cancel(task['id'])['status'],'success')
            finally: manager.close()

    def test_real_queue_running_cancel_and_queued_cancel(self):
        gate=threading.Event(); entered=threading.Event(); visits=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                visits.append(self.path)
                if self.path=='/slow': entered.set(); gate.wait(20)
                body='<html><title>Local source</title><p>public fixture</p><div>点赞 20 评论 8 收藏 2</div></html>'.encode('utf-8')
                try:
                    self.send_response(200);self.end_headers();self.wfile.write(body)
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory); settings=test_settings(root); manager=TaskManager(settings)
                payload={'platform':'generic_web','mode':'html','taskType':'content','query':f'http://127.0.0.1:{server.server_port}/slow','comments':False,'checkEvidence':False}
                try:
                    first=manager.submit('collect',payload)
                    self.assertTrue(entered.wait(12),'worker did not request local source')
                    queued=manager.submit('collect',{**payload,'query':f'http://127.0.0.1:{server.server_port}/unused'})
                    self.assertEqual(manager.store.get(queued['id'])['status'],'queued')
                    self.assertEqual(manager.cancel(queued['id'])['status'],'cancelled')
                    next_task=manager.submit('collect',{**payload,'query':f'http://127.0.0.1:{server.server_port}/fast'})
                    started=time.monotonic(); manager.cancel(first['id'])
                    self.assertEqual(manager.store.wait(first['id'],5)['status'],'cancelled')
                    self.assertLess(time.monotonic()-started,4)
                    self.assertEqual(manager.store.wait(next_task['id'],20)['status'],'success')
                    self.assertNotIn('/unused',visits)
                finally: manager.close()
        finally: gate.set();server.shutdown();server.server_close()

    @unittest.skipUnless(os.name=='nt','Windows process tree ownership')
    def test_cancellation_terminates_descendant_process(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'child.pid'
            code="import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);Path(sys.argv[1]).write_text(str(p.pid));time.sleep(60)"
            tree=ProcessTree([sys.executable,'-c',code,str(path)])
            try:
                deadline=time.monotonic()+5
                while not path.exists() and time.monotonic()<deadline: time.sleep(.02)
                self.assertTrue(path.exists())
                pid=int(path.read_text()); tree.stop()
                kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                kernel.OpenProcess.restype=ctypes.c_void_p; kernel.CloseHandle.argtypes=[ctypes.c_void_p]
                kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
                handle=kernel.OpenProcess(0x1000,False,pid)
                if handle:
                    try:
                        exit_code=ctypes.c_ulong();kernel.GetExitCodeProcess(handle,ctypes.byref(exit_code));self.assertNotEqual(exit_code.value,259)
                    finally: kernel.CloseHandle(handle)
            finally: tree.close()

    def test_index_filters_dates_and_preserves_missing_old_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);settings=test_settings(root);settings.ensure_dirs()
            rows=[{'id':str(i),'createdAt':f'2026-10-0{i+1}T12:00:00','query':'眼油' if i!=1 else 'other','platform':'taobao','ok':i!=1,'quality':{'status':'ok' if i!=1 else 'failed'}} for i in range(3)]
            (settings.log_dir/'task_history.jsonl').write_text('\n'.join(json.dumps(row) for row in rows),encoding='utf-8')
            with patch.object(workbench,'SCRAPER_ROOT',root),patch.object(workbench,'VIDEO_ROOT',root):
                filtered=results.list_results(settings,limit=1,search='眼油',status='success',start='2026-10-02',end='2026-10-03')
                self.assertEqual(filtered['total'],1);self.assertEqual(filtered['items'][0]['id'],'2')
                self.assertEqual(filtered['sourceCounts'], {'collect': 3, 'scraper': 0, 'video': 0})
                with self.assertRaises(ValueError):results.list_results(settings,start='bad-date')
                self.assertEqual(results.result_detail(settings,'0')['query'],'眼油')

    def test_legacy_preview_exports_preserve_data_and_formula_as_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);settings=test_settings(root)
            with closing(sqlite3.connect(root/'data.db')) as db:
                db.execute('CREATE TABLE scrape_history(id INTEGER,created_at TEXT,platform TEXT,status TEXT,item_count INTEGER,data_json TEXT)')
                db.execute('INSERT INTO scrape_history VALUES(1,?,?,?,?,?)',('2026-10-01','taobao','success',1,json.dumps([{'title':'local','price':'=1+1'}])))
                db.execute('CREATE TABLE crawler_jobs(id INTEGER,created_at TEXT,platform TEXT,status TEXT,output_file TEXT)')
                db.execute('INSERT INTO crawler_jobs VALUES(1,?,?,?,?)',('2026-10-01','taobao','success',''))
                db.commit()
            with patch.object(workbench,'SCRAPER_ROOT',root),patch.object(workbench,'VIDEO_ROOT',root),patch.object(results,'scraper_rows',wraps=results.scraper_rows) as importer:
                results.list_results(settings);detail=results.result_detail(settings,'scraper-scrape_history-1');results.list_results(settings)
                self.assertEqual(importer.call_count,1)
                related=results.result_detail(settings,'scraper-crawler_jobs-1')
                self.assertEqual(related['preview']['table']['rows'][0]['title'],'local')
            self.assertEqual(detail['preview']['table']['rows'][0]['price'],'=1+1')
            from openpyxl import load_workbook
            book=load_workbook(next(settings.output_dir.glob('history_*.xlsx')))
            self.assertEqual(book.active['B2'].data_type,'s');book.close()

    def test_saved_media_survives_repeated_scans(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);settings=test_settings(root);(root/'downloads').mkdir();(root/'downloads/media.mp4').write_bytes(b'fixture')
            with patch.object(workbench,'SCRAPER_ROOT',root),patch.object(workbench,'VIDEO_ROOT',root):
                self.assertEqual(results.list_results(settings)['total'],1)
                results._media_scan.clear()
                self.assertEqual(results.list_results(settings)['total'],1)

    def test_scheduled_job_reuses_exact_saved_payload(self):
        payload={**sample_payload(),'maxPages':7,'maxComments':17,'comments':True,'batchLinks':True}
        manager=Mock();manager.submit.return_value={'id':'managed','status':'queued'}
        with patch.object(web_app,'get_manager',return_value=manager),patch.object(web_app,'_save_schedule'):
            web_app._execute_scheduled_job({'id':'schedule-fixture','payload':payload},Settings())
        manager.submit.assert_called_once_with('collect',payload,schedule_id='schedule-fixture')


if __name__=='__main__': unittest.main()
