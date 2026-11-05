from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from unittest.mock import patch
from django.test import SimpleTestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from pypdf import PdfReader
from app.converter import convert_epub, InvalidEpub

def sample_epub(chapter=None, encrypted=False):
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('mimetype', 'application/epub+zip')
        archive.writestr('META-INF/container.xml', '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        archive.writestr('OEBPS/content.opf', '<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Leitura de teste</dc:title></metadata><manifest><item id="two" href="two.xhtml" media-type="application/xhtml+xml"/><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="one"/><itemref idref="two"/></spine></package>')
        archive.writestr('OEBPS/one.xhtml', chapter or '<html><body><h1>Olá, Lua!</h1><p>Uma leitura com acentuação: ação, coração e café.</p><p>Texto <strong>em negrito</strong> e <em>itálico</em>.</p><img src="cover.png" alt="Ilustração"/></body></html>')
        archive.writestr('OEBPS/two.xhtml', '<html><body><h1>Segundo capítulo</h1><p>Final da leitura.</p></body></html>')
        from PIL import Image
        buffer = BytesIO()
        Image.new('RGB', (80, 40), '#a8c787').save(buffer, 'PNG')
        archive.writestr('OEBPS/cover.png', buffer.getvalue())
        if encrypted:
            archive.writestr('META-INF/encryption.xml', '<encryption/>')
    return output.getvalue()

class ConversionTests(SimpleTestCase):
    def test_pdf_preserves_reading_order_accents_images_and_page_format(self):
        pdf = PdfReader(BytesIO(convert_epub(sample_epub())))
        self.assertEqual(len(pdf.pages), 2)
        self.assertIn('Olá, Lua!', pdf.pages[0].extract_text())
        self.assertIn('coração e café', pdf.pages[0].extract_text())
        self.assertIn('Segundo capítulo', pdf.pages[1].extract_text())
        self.assertEqual(len(pdf.pages[0].images), 1)
        self.assertAlmostEqual(float(pdf.pages[0].mediabox.width), 595.28, delta=.1)

    def test_letter_size_and_large_text(self):
        pdf = PdfReader(BytesIO(convert_epub(sample_epub(), page_size='LETTER', font_size=14)))
        self.assertEqual(float(pdf.pages[0].mediabox.width), 612)

    def test_long_chapters_paginate(self):
        pdf = PdfReader(BytesIO(convert_epub(sample_epub('<html><body><h1>Longo</h1>' + '<p>Texto de leitura e verificação. </p>' * 180 + '</body></html>'))))
        self.assertGreater(len(pdf.pages), 3)

    def test_remote_images_are_not_fetched_and_scripts_are_removed(self):
        data = sample_epub('<html><body><h1>Seguro</h1><script>segredo</script><p>Texto útil.</p><img src="http://127.0.0.1:1/private" alt="Imagem externa"/></body></html>')
        with patch('urllib.request.urlopen', side_effect=AssertionError('Network must not be used')):
            text = PdfReader(BytesIO(convert_epub(data))).pages[0].extract_text()
        self.assertIn('Texto útil', text)
        self.assertNotIn('segredo', text)
        self.assertIn('Imagem externa', text)

    def test_rejects_invalid_zip(self):
        with self.assertRaises(InvalidEpub):
            convert_epub(b'not a zip')

    def test_rejects_encrypted_epub(self):
        with self.assertRaisesRegex(InvalidEpub, 'criptografados'):
            convert_epub(sample_epub(encrypted=True))

    def test_rejects_zip_bomb_before_reading(self):
        data = BytesIO()
        with ZipFile(data, 'w', ZIP_DEFLATED) as archive:
            archive.writestr('huge.txt', b'0' * (21 * 1024 * 1024))
        with self.assertRaisesRegex(InvalidEpub, '20 MB'):
            convert_epub(data.getvalue())

class ApiTests(SimpleTestCase):
    def test_all_frontend_routes_and_status(self):
        for route in ('/', '/home', '/live', '/live/', '/definicoes', '/mais', '/mais/epub-pdf'):
            self.assertEqual(self.client.get(route).status_code, 200, route)
        self.assertEqual(self.client.get('/api/status').json()['name'], 'Lua MediaPaper')
        self.assertEqual(self.client.get('/does-not-exist').status_code, 404)

    def test_csrf_is_required_for_conversion(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/api/convert').status_code, 403)
        client.get('/api/status')
        response = client.post('/api/convert', {'file': SimpleUploadedFile('book.epub', sample_epub())}, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))

    def test_invalid_file_and_options(self):
        self.assertEqual(self.client.post('/api/convert').status_code, 400)
        self.assertEqual(self.client.post('/api/convert', {'file': SimpleUploadedFile('book.epub', b'bad')}).status_code, 400)
        self.assertEqual(self.client.post('/api/convert', {'file': SimpleUploadedFile('book.epub', sample_epub()), 'fontSize': '999'}).status_code, 400)

    def test_startup_is_unavailable_in_server_mode(self):
        with patch.dict('os.environ', {'LUAMP_DESKTOP':'0'}):
            self.assertEqual(self.client.post('/api/startup', data='{"enabled":true}', content_type='application/json').status_code, 400)

    def test_startup_blocks_remote_clients_and_requires_bool(self):
        with patch.dict('os.environ', {'LUAMP_DESKTOP':'1'}):
            self.assertEqual(self.client.post('/api/startup', data='{"enabled":true}', content_type='application/json', REMOTE_ADDR='192.168.0.2').status_code, 403)
            self.assertEqual(self.client.post('/api/startup', data='{"enabled":"yes"}', content_type='application/json', REMOTE_ADDR='127.0.0.1').status_code, 400)

class NetworkTests(SimpleTestCase):
    def test_all_interfaces_accept_lan_addresses(self):
        from app import network
        with patch.object(network, 'local_addresses', return_value=['192.168.0.20']):
            hosts = network.allowed_hosts('0.0.0.0').split(',')
            self.assertIn('127.0.0.1', hosts)
            self.assertIn('192.168.0.20', hosts)
            self.assertEqual(network.network_urls('0.0.0.0', 8765), ['http://192.168.0.20:8765/'])
        self.assertEqual(network.network_urls('127.0.0.1', 8765), [])
        self.assertNotIn('192.168.0.20', network.allowed_hosts('127.0.0.1'))

    def test_status_lists_network_urls(self):
        from app import network
        with patch.dict('os.environ', {'LUAMP_HOST':'0.0.0.0', 'LUAMP_PORT':'8765'}), patch.object(network, 'local_addresses', return_value=['10.0.0.5']):
            self.assertEqual(self.client.get('/api/status').json()['networkUrls'], ['http://10.0.0.5:8765/'])

class WallpaperTests(SimpleTestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory
        from django.test import override_settings
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(LUAMP_DATA_DIR=self.directory.name)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def change(self, data, client=None):
        import json
        return (client or self.client).patch('/api/wallpaper', data=json.dumps(data), content_type='application/json')

    def test_new_display_has_default_state_and_conditional_reads(self):
        response = self.client.get('/api/wallpaper')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['revision'], 0)
        self.assertTrue(response.json()['preferences']['keepAwake'])
        self.assertEqual(self.client.get('/api/wallpaper', HTTP_IF_NONE_MATCH=response['ETag']).status_code, 304)
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_changes_propagate_to_independent_clients_and_survive_reopening(self):
        from app.wallpaper import read_state, DEFAULT_MEDIA
        media = {**DEFAULT_MEDIA, 'id':'sea', 'url':'/wallpapers/sea.jpg'}
        self.assertEqual(self.change({'media':media, 'preferences':{'clock':False}}).status_code, 200)
        independent = Client().get('/api/wallpaper').json()
        self.assertEqual(independent['media']['url'], '/wallpapers/sea.jpg')
        self.assertFalse(independent['preferences']['clock'])
        self.assertEqual(read_state(), independent)

    def test_partial_edits_do_not_overwrite_other_preferences(self):
        self.change({'preferences':{'clock':False}})
        self.change({'preferences':{'dim':35}})
        state = self.client.get('/api/wallpaper').json()
        self.assertFalse(state['preferences']['clock'])
        self.assertEqual(state['preferences']['dim'], 35)
        self.assertEqual(state['revision'], 2)

    def test_concurrent_edits_are_atomic(self):
        from concurrent.futures import ThreadPoolExecutor
        from app.wallpaper import update_state, read_state
        read_state()
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(lambda key: update_state({'preferences':{key:False}}), ('clock','date','hour24','muted','autoplay','keepAwake')))
        state = read_state()
        self.assertEqual(state['revision'], 6)
        self.assertEqual(len({result['revision'] for result in results}), 6)
        self.assertTrue(all(state['preferences'][key] is False for key in ('clock','date','hour24','muted','autoplay','keepAwake')))

    def test_initial_import_cannot_replace_an_already_initialized_display(self):
        self.assertEqual(self.change({'preferences':{'dim':20}, 'initialRevision':0}).status_code, 200)
        response = self.change({'preferences':{'dim':60}, 'initialRevision':0})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['preferences']['dim'], 20)

    def test_updates_require_csrf_and_readers_receive_a_token(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.change({'preferences':{'dim':20}}, client).status_code, 403)
        client.get('/api/wallpaper')
        response = client.patch('/api/wallpaper', data='{"preferences":{"dim":20}}', content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)

    def test_invalid_protocols_preferences_and_large_payloads_are_rejected(self):
        from app.wallpaper import DEFAULT_MEDIA
        for invalid in ('javascript:alert(1)', 'file:///private', 'data:image/svg+xml,test', 'https://user:password@example.com/a.jpg', '/etc/passwd'):
            self.assertEqual(self.change({'media':{**DEFAULT_MEDIA,'url':invalid}}).status_code, 400)
        for value in ({'clock':'yes'}, {'dim':True}, {'dim':71}, {'fit':'stretch'}, {'unknown':True}):
            self.assertEqual(self.change({'preferences':value}).status_code, 400)
        self.assertEqual(self.change({'other':'bad'}).status_code, 400)
        self.assertEqual(self.change({'media':{'url':'x'*20000}}).status_code, 413)

    def test_revision_changes_invalidate_etag(self):
        initial = self.client.get('/api/wallpaper')
        self.change({'preferences':{'keepAwake':False}})
        current = self.client.get('/api/wallpaper', HTTP_IF_NONE_MATCH=initial['ETag'])
        self.assertEqual(current.status_code, 200)
        self.assertNotEqual(initial['ETag'],current['ETag'])
