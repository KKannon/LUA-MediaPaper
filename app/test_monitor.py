import asyncio
import json
import tempfile
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from app import monitor
from app.browser import normalize_url
from app.edge_input import region_at, crossed_back, leave_point

BOUNDS = (0, 0, 1920, 1080)

class EdgeGeometryTests(SimpleTestCase):
    def test_entering_from_each_side_maps_to_the_device_edge(self):
        right = {'device': 'r', 'side': 'right', 'start': 100, 'width': 800, 'height': 600}
        left = {'device': 'l', 'side': 'left', 'start': 0, 'width': 400, 'height': 900}
        bottom = {'device': 'b', 'side': 'bottom', 'start': 500, 'width': 700, 'height': 400}
        regions = [right, left, bottom]
        self.assertEqual(region_at(regions, 1919, 400, BOUNDS), (right, (0, 300)))
        self.assertEqual(region_at(regions, 0, 50, BOUNDS), (left, (399, 50)))
        self.assertEqual(region_at(regions, 600, 1079, BOUNDS), (bottom, (100, 0)))
        self.assertEqual(region_at(regions, 1919, 50, BOUNDS), (None, None))  # Above the device's segment.
        self.assertEqual(region_at(regions, 1000, 500, BOUNDS), (None, None))  # Not at an edge.

    def test_leaving_returns_to_the_same_edge(self):
        self.assertTrue(crossed_back('right', -1, 10, 800, 600))
        self.assertFalse(crossed_back('right', 0, 10, 800, 600))
        self.assertTrue(crossed_back('left', 400, 10, 400, 600))
        self.assertTrue(crossed_back('top', 10, 600, 800, 600))
        self.assertEqual(leave_point('right', 100, 300, BOUNDS), (1917, 400))
        self.assertEqual(leave_point('bottom', 500, 100, BOUNDS), (600, 1077))
        self.assertEqual(leave_point('left', 0, 5000, BOUNDS), (2, 1079))  # Clamped to the screen.

    def test_addresses_typed_in_the_os(self):
        self.assertEqual(normalize_url('youtube.com'), 'https://youtube.com')
        self.assertEqual(normalize_url('192.168.0.5:8080/x'), 'http://192.168.0.5:8080/x')
        self.assertEqual(normalize_url('gatos fofos'), 'https://www.google.com/search?q=gatos+fofos')
        for unsafe in ('file:///etc/passwd', 'javascript:alert(1)', 'chrome://settings'):
            self.assertTrue(normalize_url(unsafe).startswith('https://www.google.com/search?q='), unsafe)

class FakeBrowser:
    def __init__(self):
        self.calls = []
    async def send(self, method, params=None, session=None, wait=True):
        self.calls.append((method, params, session))

class FakeConnection:
    def __init__(self):
        self.sent = []
    async def send(self, message):
        self.sent.append(json.loads(message))

class HubTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(LUAMP_DATA_DIR=self.directory.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.hub = monitor.Hub()
        self.hub.browser = FakeBrowser()
        self.device = FakeConnection()
        self.hub.connections['dev'] = self.device
        monitor.save_devices({'dev': {'id': 'dev', 'name': 'Tablet', 'approved': True, 'side': 'right', 'offset': 0, 'width': 1000, 'height': 700}})
        self.hub.windows['w1'] = {'id': 'w1', 'device': 'dev', 'target': 't1', 'session': 's1', 'url': '', 'title': '', 'loading': False, 'w': 600, 'h': 400, 'scale': 1, 'frame': None}
        self.hub.screens['dev'] = {'rects': [{'win': 'w1', 'x': 100, 'y': 138, 'w': 600, 'h': 400, 'fx': 100, 'fy': 100, 'fw': 600, 'fh': 438}], 'focus': None}

    def edge(self, **event):
        asyncio.run(self.hub._edge_event({'device': 'dev', **event}))

    def test_pc_cursor_over_a_window_drives_the_hidden_browser(self):
        self.edge(type='move', x=150, y=200)
        self.edge(type='button', button='left', down=True, x=150, y=200, modifiers=0)
        self.edge(type='button', button='left', down=False, x=150, y=200, modifiers=0)
        events = [params for method, params, session in self.hub.browser.calls if method == 'Input.dispatchMouseEvent']
        self.assertEqual([(e['type'], e['x'], e['y']) for e in events], [('mouseMoved', 50, 62), ('mousePressed', 50, 62), ('mouseReleased', 50, 62)])
        self.assertEqual(self.hub.screens['dev']['focus'], 'w1')
        self.assertIn({'type': 'focus', 'win': 'w1'}, self.device.sent)
        self.edge(type='key', down=True, vk=65, key='a', code='KeyA', text='a', modifiers=0)
        key = [params for method, params, session in self.hub.browser.calls if method == 'Input.dispatchKeyEvent'][-1]
        self.assertEqual((key['type'], key['text']), ('keyDown', 'a'))

    def test_title_bar_and_desktop_clicks_go_to_the_device(self):
        self.edge(type='button', button='left', down=True, x=150, y=110, modifiers=0)  # Title bar.
        self.edge(type='button', button='left', down=True, x=900, y=650, modifiers=0)  # Desktop.
        pointers = [m for m in self.device.sent if m['type'] == 'pointer']
        self.assertEqual([(m['x'], m['y']) for m in pointers], [(150, 110), (900, 650)])
        self.assertFalse(any(method == 'Input.dispatchMouseEvent' for method, _, _ in self.hub.browser.calls))
        self.edge(type='key', down=True, vk=65, key='a', code='KeyA', text='a', modifiers=0)
        self.assertEqual(self.device.sent[-1]['type'], 'key')  # No focused window: the shell types it.

    def test_a_drag_started_in_a_window_stays_there(self):
        self.edge(type='button', button='left', down=True, x=150, y=200, modifiers=0)
        self.edge(type='move', x=900, y=650)
        self.edge(type='button', button='left', down=False, x=900, y=650, modifiers=0)
        last = [params for method, params, _ in self.hub.browser.calls if method == 'Input.dispatchMouseEvent'][-1]
        self.assertEqual((last['type'], last['x']), ('mouseReleased', 800))

    def test_unapproved_devices_cannot_open_windows(self):
        monitor.save_devices({'dev': {'id': 'dev', 'name': 'Tablet', 'approved': False, 'width': 1000, 'height': 700}})
        asyncio.run(self.hub._message('dev', {'type': 'open', 'url': 'https://example.com'}))
        asyncio.run(self.hub._message('dev', {'type': 'mouse', 'win': 'w1', 'action': 'down', 'x': 1, 'y': 1}))
        self.assertEqual(self.hub.browser.calls, [])

    def test_devices_cannot_control_other_devices_windows(self):
        monitor.save_devices({'other': {'id': 'other', 'name': 'Outro', 'approved': True, 'width': 1000, 'height': 700}, **monitor.load_devices()})
        asyncio.run(self.hub._message('other', {'type': 'close', 'win': 'w1'}))
        self.assertIn('w1', self.hub.windows)

class MonitorApiTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(LUAMP_DATA_DIR=self.directory.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        monitor.save_devices({'abc12345': {'id': 'abc12345', 'name': 'Tablet', 'approved': False, 'side': None, 'offset': 0, 'width': 1000, 'height': 700}})

    def patch(self, body, **extra):
        return self.client.patch('/api/monitors/abc12345', data=json.dumps(body), content_type='application/json', **extra)

    def test_list_approve_and_arrange(self):
        self.assertEqual(self.client.get('/api/monitors').json()['devices'][0]['name'], 'Tablet')
        self.assertEqual(self.patch({'approved': True, 'side': 'left', 'offset': 120, 'name': '  Tablet   da Lua '}).status_code, 200)
        device = monitor.load_devices()['abc12345']
        self.assertEqual((device['approved'], device['side'], device['offset'], device['name']), (True, 'left', 120, 'Tablet da Lua'))
        self.assertEqual(self.patch({'side': 'diagonal'}).status_code, 400)
        self.assertEqual(self.patch({'hack': 1}).status_code, 400)
        self.assertEqual(self.client.patch('/api/monitors/missing', data='{}', content_type='application/json').status_code, 404)
        self.assertEqual(self.client.delete('/api/monitors/abc12345').status_code, 200)
        self.assertEqual(monitor.load_devices(), {})

    def test_portable_app_only_approves_or_removes_from_the_pc(self):
        with patch.dict('os.environ', {'LUAMP_DESKTOP': '1'}):
            self.assertEqual(self.patch({'approved': True}, REMOTE_ADDR='192.168.0.9').status_code, 403)
            self.assertEqual(self.client.delete('/api/monitors/abc12345', REMOTE_ADDR='192.168.0.9').status_code, 403)
            self.assertEqual(self.patch({'side': 'right'}, REMOTE_ADDR='192.168.0.9').status_code, 200)
            self.assertEqual(self.patch({'approved': True}, REMOTE_ADDR='127.0.0.1').status_code, 200)

    def test_changes_require_csrf(self):
        from django.test import Client
        self.assertEqual(Client(enforce_csrf_checks=True).patch('/api/monitors/abc12345', data='{}', content_type='application/json').status_code, 403)

class PinnedAppTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(LUAMP_DATA_DIR=self.directory.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.hub = monitor.Hub()
        self.hub.browser = FakeBrowser()
        self.device = FakeConnection()
        self.hub.connections['dev'] = self.device
        monitor.save_devices({'dev': {'id': 'dev', 'name': 'Tablet', 'approved': True, 'width': 1000, 'height': 700, 'scale': 1, 'apps': monitor.default_apps()}})
        self.hub.windows['w1'] = {'id': 'w1', 'device': 'dev', 'target': 't1', 'session': 's1', 'url': 'https://www.netflix.com/browse', 'title': 'netflix.com/browse', 'loading': False, 'w': 600, 'h': 400, 'scale': 1, 'frame': None}

    def apps(self):
        return monitor.load_devices()['dev']['apps']

    def test_pin_names_the_app_and_reopens_the_last_page(self):
        asyncio.run(self.hub._message('dev', {'type': 'pin', 'win': 'w1'}))
        app = self.apps()[-1]
        self.assertEqual((app['host'], app['name'], app['url']), ('netflix.com', 'Netflix', 'https://www.netflix.com/'))
        asyncio.run(self.hub._message('dev', {'type': 'pin', 'win': 'w1'}))
        self.assertEqual(len(self.apps()), 5)  # Same site is not pinned twice.
        # The page title arrives later and the user keeps browsing: both are remembered.
        window = self.hub.windows['w1']
        window['url'], window['title'] = 'https://www.netflix.com/title/123', 'Série boa | Netflix'
        async def remember():
            self.hub._remember(window)
        asyncio.run(remember())
        app = self.apps()[-1]
        self.assertEqual((app['name'], app['last']), ('Netflix', 'https://www.netflix.com/title/123'))
        # Launching an app whose site is open focuses that window instead of opening another.
        asyncio.run(self.hub._message('dev', {'type': 'launch', 'app': app['id']}))
        self.assertEqual(self.device.sent[-1], {'type': 'focus', 'win': 'w1'})
        del self.hub.windows['w1']
        opened = []
        async def fake_open(url, width, height, scale):
            opened.append(url)
            return 't2', 's2'
        self.hub.browser.open = fake_open
        asyncio.run(self.hub._message('dev', {'type': 'launch', 'app': app['id']}))
        self.assertEqual(opened, ['https://www.netflix.com/title/123'])

    def test_unpin(self):
        first = self.apps()[0]
        asyncio.run(self.hub._message('dev', {'type': 'unpin', 'app': first['id']}))
        self.assertNotIn(first['id'], [app['id'] for app in self.apps()])
        self.assertEqual(self.device.sent[-1]['type'], 'apps')

    def test_app_names(self):
        self.assertEqual(monitor.app_name('Home / X', 'x.com'), ('X', True))
        self.assertEqual(monitor.app_name('Vídeo legal - YouTube', 'youtube.com'), ('YouTube', True))
        self.assertEqual(monitor.app_name('192.168.0.5:8080/', '192.168.0.5'), ('192.168.0.5', False))
