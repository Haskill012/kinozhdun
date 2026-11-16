import unittest
from website.vk_upload_check import allowed_upload_url, upload_check_handler, send_poster
import json
from unittest.mock import AsyncMock
from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web


class UploadURLTests(unittest.TestCase):
    def test_only_vk_upload_hosts_without_credentials_or_redirect_destinations(self):
        for url in ['https://pu.vk.com/c123/upload.php?act=wall', 'https://psv4.userapi.com/upload']:
            self.assertTrue(allowed_upload_url(url), url)
        for url in ['http://pu.vk.com/upload', 'https://pu.vk.com.evil.test/upload',
                    'https://127.0.0.1/upload', 'https://localhost/upload',
                    'https://user:pass@pu.vk.com/upload', 'https://pu.vk.com:8080/upload',
                    'https://pu.vk.com/upload#fragment', 'https://vk.com/upload', None]:
            self.assertFalse(allowed_upload_url(url), url)


class UploadRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_bulk_field_and_legacy_empty_receipt_fallback(self):
        class Response:
            status = 200
            def __init__(self, receipt):
                self.content = type('Content', (), {'read': AsyncMock(return_value=json.dumps(receipt).encode())})()
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
        class Session:
            def __init__(self, receipts): self.receipts, self.fields = list(receipts), []
            def post(self, url, data, allow_redirects):
                self.fields.append(data._fields[0][0]['name'])
                self.assert_no_redirect = not allow_redirects
                return Response(self.receipts.pop(0))
        receipt = {'photo': 'accepted', 'server': 123, 'hash': 'SECRET'}
        bulk = Session([receipt])
        self.assertEqual(await send_poster(bulk, 'https://pu.vk.com/photo/bulk_upload', b'jpeg'), receipt)
        self.assertEqual(bulk.fields, ['file1'])
        legacy = Session([{'photo': '[]', 'server': 123}, receipt])
        self.assertEqual(await send_poster(legacy, 'https://pu.vk.com/upload.php', b'jpeg'), receipt)
        self.assertEqual(legacy.fields, ['photo', 'file1'])
        failed = Session([{'files': {'file1': {'secret': 'SECRET'}}, 'hash': 'SECRET'}])
        with self.assertRaises(web.HTTPBadGateway) as caught:
            await send_poster(failed, 'https://pu.vk.com/bulk_upload', b'jpeg')
        self.assertNotIn('SECRET', caught.exception.text)
        self.assertEqual(failed.fields, ['file1'])

    async def test_untrusted_upload_url_rejected_before_any_network_or_catalog_access(self):
        app = web.Application()
        app.router.add_post('/upload', upload_check_handler('missing-file.json'))
        async with TestClient(TestServer(app)) as client:
            response = await client.post('/upload', json={'upload_url': 'https://127.0.0.1/secret'})
            self.assertEqual(response.status, 400)
            self.assertNotIn('127.0.0.1', await response.text())
