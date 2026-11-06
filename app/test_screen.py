import json
import tempfile
from io import BytesIO
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from PIL import Image
from app.wallpaper import read_state

def png():
    output = BytesIO()
    Image.new('RGB', (64, 40), '#c1e697').save(output, 'PNG')
    return output.getvalue()

class UploadTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(LUAMP_DATA_DIR=self.directory.name)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def upload(self, name, content):
        return self.client.post('/api/upload', {'file': SimpleUploadedFile(name, content)})

    def test_upload_applies_the_file_and_deletes_the_previous_one(self):
        from pathlib import Path
        first = self.upload('Minha foto.png', png())
        self.assertEqual(first.status_code, 200)
        media = read_state()['media']
        self.assertEqual((media['name'], media['type']), ('Minha foto', 'image'))
        served = self.client.get(media['url'])
        self.assertEqual((served.status_code, served['Content-Type']), (200, 'image/png'))
        video = b'\x00\x00\x00\x18ftypmp42' + b'\x00' * 200
        self.assertEqual(self.upload('clip.mp4', video).status_code, 200)
        self.assertEqual(read_state()['media']['type'], 'video')
        self.assertEqual(self.client.get(media['url']).status_code, 404)
        files = [p.name for p in (Path(self.directory.name) / 'media').iterdir()]
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith('.mp4'))
        self.assertEqual(self.upload('anim.gif', png()).status_code, 400)  # A PNG renamed to .gif.

    def test_rejects_wrong_content_and_types(self):
        self.assertEqual(self.upload('script.exe', b'MZ').status_code, 400)
        self.assertEqual(self.upload('photo.jpg', b'not an image').status_code, 400)
        self.assertEqual(self.upload('clip.mp4', b'not a video at all').status_code, 400)

    def test_requires_csrf(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/api/upload', {'file': SimpleUploadedFile('a.png', png())}).status_code, 403)

class ScreenPreferenceTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(LUAMP_DATA_DIR=self.directory.name)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def change(self, preferences):
        return self.client.patch('/api/wallpaper', data=json.dumps({'preferences': preferences}), content_type='application/json')

    def test_idle_and_city(self):
        self.assertEqual(read_state()['preferences']['idle'], 15)
        self.assertEqual(self.change({'idle': 60, 'weather': True, 'city': {'name': 'São Paulo, Brasil', 'lat': -23.5, 'lon': -46.6}}).status_code, 200)
        for bad in ({'idle': 7}, {'city': {'name': 'X', 'lat': 200, 'lon': 0}}, {'city': 'Lisboa'}, {'weather': 'sim'}):
            self.assertEqual(self.change(bad).status_code, 400, bad)

    def test_weather_uses_the_city_and_caches(self):
        self.change({'weather': True, 'city': {'name': 'Recife, Pernambuco, Brasil', 'lat': -8.05, 'lon': -34.9}})
        reply = {'current': {'temperature_2m': 28.6, 'weather_code': 2, 'is_day': 1}}
        with patch('app.views._fetch_json', return_value=reply) as fetch:
            data = self.client.get('/api/weather').json()
            self.client.get('/api/weather')
        self.assertEqual((data['temperature'], data['city'], data['description']), (29, 'Recife', 'Parcialmente nublado'))
        self.assertEqual(fetch.call_count, 1)
        self.change({'weather': False})
        self.assertEqual(self.client.get('/api/weather').json(), {'enabled': False})
