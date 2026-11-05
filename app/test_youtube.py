import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch
from django.test import SimpleTestCase, override_settings, Client
from app import youtube
from app.wallpaper import _connection, update_state, read_state, DEFAULT_MEDIA

class YouTubeTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(LUAMP_DATA_DIR=self.directory.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.old_worker = youtube._worker
        youtube._worker = None
        self.addCleanup(setattr, youtube, '_worker', self.old_worker)
        self.root = Path(self.directory.name)
        self.media, self.staging = youtube._paths()

    def job(self):
        job = {'id':uuid.uuid4().hex, 'url':'https://www.youtube.com/watch?v=jNQXAC9IVRw', 'status':'checking'}
        connection = _connection()
        connection.execute('INSERT OR REPLACE INTO youtube_job VALUES (1,?)', (json.dumps(job),))
        connection.commit()
        connection.close()
        return job

    def previous(self):
        name = uuid.uuid4().hex + '.mp4'
        path = self.media / name
        path.write_bytes(b'previous-video')
        update_state({'media':{**DEFAULT_MEDIA,'url':'/media/'+name,'type':'video'}})
        return path

    def run_fake(self, job, duration=20, download=None):
        downloader = MagicMock()
        downloader.__enter__.return_value = downloader
        downloader.extract_info.return_value = {'id':'jNQXAC9IVRw','title':'Vídeo de teste', 'duration':duration,'height':2160, 'requested_formats':[{'filesize':20}]}
        def default_download(info, **kwargs):
            (self.staging / job['id'] / 'source.mp4').write_bytes(b'new-video')
        downloader.process_ie_result.side_effect = download or default_download
        with patch('yt_dlp.YoutubeDL', return_value=downloader), patch.object(youtube,'tool',return_value='/tools/ffmpeg'), patch.object(youtube,'_probe',return_value=(20,2160)):
            youtube._run(job)
        return downloader

    def test_only_normalized_youtube_video_urls_are_accepted(self):
        canonical = 'https://www.youtube.com/watch?v=jNQXAC9IVRw'
        for link in ('https://youtu.be/jNQXAC9IVRw?t=10',canonical+'&list=example','https://m.youtube.com/shorts/jNQXAC9IVRw','https://www.youtube.com/embed/jNQXAC9IVRw'):
            self.assertEqual(youtube.normalize_url(link),canonical)
        for link in ('http://127.0.0.1/private','https://youtube.com.evil.test/watch?v=jNQXAC9IVRw','https://www.youtube.com/playlist?list=abc','https://user:password@youtube.com/watch?v=jNQXAC9IVRw','file:///tmp/a',None):
            with self.assertRaises(youtube.ImportError):
                youtube.normalize_url(link)

    def test_twenty_minutes_is_allowed_and_longer_or_live_is_rejected(self):
        self.assertEqual(youtube.validate_metadata({'duration':1200}),1200)
        for info in ({'duration':1200.01},{'duration':None},{'duration':float('nan')},{'duration':True},{'duration':0},{'duration':30,'is_live':True},{'duration':30,'_type':'playlist'}):
            with self.assertRaises(youtube.ImportError):
                youtube.validate_metadata(info)

    def test_real_format_selector_chooses_4k_instead_of_1080p_or_8k(self):
        from yt_dlp import YoutubeDL
        formats = [{'format_id':str(height),'url':f'https://example.test/{height}.mp4','height':height,'width':height*16//9,'ext':'mp4','vcodec':'avc1','acodec':'none','tbr':height*2} for height in (1080,2160,4320)]
        formats.append({'format_id':'audio','url':'https://example.test/audio.m4a','ext':'m4a','vcodec':'none','acodec':'mp4a','abr':128})
        with YoutubeDL({'format':youtube.FORMAT,'quiet':True,'no_warnings':True}) as downloader:
            selected = downloader.process_ie_result({'id':'test','title':'Test','duration':20,'formats':formats},download=False)
        self.assertEqual(selected['height'],2160)
        self.assertEqual(selected['requested_formats'][0]['format_id'],'2160')

    def test_success_activates_new_video_before_removing_the_previous_one(self):
        old = self.previous()
        job = self.job()
        self.run_fake(job)
        self.assertFalse(old.exists())
        self.assertEqual([p.name for p in self.media.iterdir()],[job['id']+'.mp4'])
        self.assertEqual(read_state()['media']['sourceUrl'],job['url'])
        self.assertEqual(youtube.read_job()['status'],'ready')
        self.assertFalse((self.staging / job['id']).exists())

    def test_duration_rejection_does_not_download_or_delete_the_current_video(self):
        old = self.previous()
        job = self.job()
        downloader = self.run_fake(job,duration=1201)
        downloader.process_ie_result.assert_not_called()
        self.assertTrue(old.exists())
        self.assertEqual(youtube.read_job()['status'],'error')
        self.assertIn('20 minutos',youtube.read_job()['message'])
        self.assertFalse((self.staging / job['id']).exists())

    def test_download_failure_preserves_current_video_and_cleans_partial_files(self):
        old=self.previous()
        job=self.job()
        def fail(info,**kwargs):
            (self.staging/job['id']/'source.mp4.part').write_bytes(b'partial')
            raise RuntimeError('Network failed')
        self.run_fake(job,download=fail)
        self.assertTrue(old.exists())
        self.assertEqual(youtube.read_job()['status'],'error')
        self.assertEqual(list(self.staging.iterdir()),[])

    def test_manual_wallpaper_change_cancels_pending_download_and_removes_cache(self):
        old=self.previous()
        job=self.job()
        def replace(info,**kwargs):
            (self.staging/job['id']/'source.mp4').write_bytes(b'candidate')
            response=self.client.patch('/api/wallpaper',data=json.dumps({'media':DEFAULT_MEDIA}),content_type='application/json')
            self.assertEqual(response.status_code,200)
        self.run_fake(job,download=replace)
        self.assertFalse(old.exists())
        self.assertEqual(read_state()['media'],DEFAULT_MEDIA)
        self.assertEqual(youtube.read_job()['status'],'cancelled')
        self.assertEqual(list(self.media.iterdir()),[])

    def test_cancelling_an_import_does_not_replace_the_existing_video(self):
        old=self.previous()
        job=self.job()
        def cancel(info,**kwargs):
            (self.staging/job['id']/'source.mp4').write_bytes(b'candidate')
            youtube.cancel()
        self.run_fake(job,download=cancel)
        self.assertTrue(old.exists())
        self.assertEqual(youtube.read_job()['status'],'cancelled')
        self.assertFalse((self.staging/job['id']).exists())

    def test_serving_supports_byte_ranges_head_and_rejects_retired_files(self):
        path=self.previous()
        response=self.client.get('/media/'+path.name,HTTP_RANGE='bytes=2-5')
        self.assertEqual(response.status_code,206)
        self.assertEqual(b''.join(response.streaming_content),b'evio')
        self.assertEqual(response['Content-Range'],'bytes 2-5/14')
        suffix=self.client.get('/media/'+path.name,HTTP_RANGE='bytes=-5')
        self.assertEqual(b''.join(suffix.streaming_content),b'video')
        self.assertEqual(self.client.head('/media/'+path.name).status_code,200)
        for header in ('bytes=99-100','bytes=5-2','bytes=0-1,3-4','bytes=-0'):
            self.assertEqual(self.client.get('/media/'+path.name,HTTP_RANGE=header).status_code,416)
        update_state({'media':DEFAULT_MEDIA})
        self.assertEqual(self.client.get('/media/'+path.name).status_code,404)

    def test_csrf_protects_import_and_cancel_and_bad_urls_do_not_start_jobs(self):
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/api/youtube',data='{}',content_type='application/json').status_code,403)
        self.assertEqual(client.delete('/api/youtube').status_code,403)
        client.get('/api/youtube')
        response=client.post('/api/youtube',data='{"url":"https://example.com/a.mp4"}',content_type='application/json',HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code,400)
        self.assertEqual(youtube.read_job()['status'],'idle')

    def test_restart_cleans_abandoned_work_and_only_managed_media_files(self):
        old=self.previous()
        retired=self.media/(uuid.uuid4().hex+'.mp4')
        retired.write_bytes(b'obsolete')
        note=self.media/'notes.txt'
        note.write_text('keep')
        job=self.job()
        directory=self.staging/job['id']
        directory.mkdir()
        (directory/'fragment.part').write_bytes(b'partial')
        youtube.initialize()
        self.assertTrue(old.exists())
        self.assertFalse(retired.exists())
        self.assertTrue(note.exists())
        self.assertFalse(directory.exists())
        self.assertEqual(youtube.read_job()['status'],'error')

    def test_recursive_cleanup_never_leaves_the_staging_root(self):
        outside=self.root/uuid.uuid4().hex
        outside.mkdir()
        (outside/'important.txt').write_text('keep')
        youtube._safe_remove_work(outside)
        self.assertTrue((outside/'important.txt').exists())

    def test_bot_check_has_clear_message_and_keeps_previous_video(self):
        old = self.previous()
        job = self.job()
        def blocked(info, **kwargs):
            raise Exception("ERROR: [youtube] jNQXAC9IVRw: Sign in to confirm you’re not a bot.")
        self.run_fake(job, download=blocked)
        current = youtube.read_job()
        self.assertEqual(current['status'], 'error')
        self.assertIn('anti-robô', current['message'])
        self.assertTrue(old.exists())
        self.assertEqual(list(self.staging.iterdir()), [])
