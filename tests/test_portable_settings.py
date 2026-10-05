import json
import tempfile
import unittest
from pathlib import Path
from social_crawler.settings import load_settings
from social_crawler.web_app import download_links, make_handler
from urllib.parse import unquote


class PortableSettingsTest(unittest.TestCase):
    def test_relative_paths_resolve_against_the_copied_project(self):
        with tempfile.TemporaryDirectory(prefix='portable Chinese ') as folder:
            root=Path(folder)/'中文目录';(root/'config').mkdir(parents=True)
            config=root/'config/settings.json'
            config.write_text(json.dumps({'project_root':'.','adb_path':'platform-tools/adb.exe','output_dir':'data/exports','log_dir':'data/logs','raw_dir':'data/raw','screenshot_dir':'data/screenshots'}),encoding='utf-8')
            settings=load_settings(config)
            self.assertEqual(settings.project_root,root.resolve())
            self.assertEqual(settings.adb_path,root/'platform-tools/adb.exe')
            self.assertTrue(settings.log_dir.is_dir())
            self.assertTrue(all(path.is_relative_to(root) for path in (settings.output_dir,settings.log_dir,settings.raw_dir,settings.screenshot_dir)))

    def test_existing_absolute_configuration_stays_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'config').mkdir()
            config=root/'config/settings.json'
            data={name:str(root/name) for name in ('output_dir','log_dir','raw_dir','screenshot_dir')}
            data['project_root']=str(root)
            config.write_text(json.dumps(data),encoding='utf-8')
            self.assertEqual(load_settings(config).output_dir,root/'output_dir')

    def test_download_url_is_ascii_and_keeps_unicode_filename(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'config').mkdir()
            config=root/'config/settings.json'
            config.write_text(json.dumps({'project_root':'.','output_dir':'data/exports'}),encoding='utf-8')
            settings=load_settings(config)
            filename='中文 采集.xlsx'
            links=download_links({'excel':settings.output_dir/filename,'outside':root/'data/exports-old/private.xlsx'},settings)
            self.assertEqual(set(links),{'excel'})
            self.assertTrue(links['excel'].isascii())
            self.assertEqual(unquote(links['excel']),'/api/file/'+filename)

    def test_unicode_file_download_has_valid_http_headers_and_body(self):
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from urllib.request import urlopen
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'config').mkdir()
            config=root/'config/settings.json'
            config.write_text(json.dumps({'project_root':'.','output_dir':'data/exports'}),encoding='utf-8')
            settings=load_settings(config)
            file=settings.output_dir/'中文 文件.xlsx'
            file.write_bytes(b'portable download fixture')
            with patch('social_crawler.web_app.get_manager'):
                server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(settings))
            thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                link=download_links({'excel':file},settings)['excel']
                with urlopen(f'http://127.0.0.1:{server.server_port}'+link,timeout=5) as response:
                    self.assertEqual(response.read(),file.read_bytes())
                    disposition=response.headers['Content-Disposition']
                    self.assertTrue(disposition.isascii())
                    self.assertIn(file.name,unquote(disposition))
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5)
