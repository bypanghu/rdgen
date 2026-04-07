import json
from pathlib import Path
import shutil
from unittest.mock import Mock, patch

import requests
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import Client
from django.test import SimpleTestCase, TestCase
from django.test.utils import override_settings

from rdgenerator.views import save_png


class MacOSDownloadTemplateTests(SimpleTestCase):
    def test_generated_template_only_uses_macos_aarch64_dmg_name(self):
        html = render_to_string(
            'generated.html',
            {'platform': 'macos', 'filename': 'jutze-remote-desktop', 'uuid': '123'},
        )
        self.assertIn('jutze-remote-desktop-macos-aarch64.dmg', html)
        self.assertNotIn('jutze-remote-desktop-macos-x86_64.dmg', html)

    def test_failure_template_only_uses_macos_aarch64_dmg_name(self):
        html = render_to_string(
            'failure.html',
            {
                'platform': 'macos',
                'filename': 'jutze-remote-desktop',
                'uuid': '123',
                'log_url': 'https://example.com/log',
                'status': 'failure',
            },
        )
        self.assertIn('jutze-remote-desktop-macos-aarch64.dmg', html)
        self.assertNotIn('jutze-remote-desktop-macos-x86_64.dmg', html)


class DownloadViewTests(TestCase):
    def setUp(self):
        self.uuid = 'test-uuid'
        self.exe_dir = Path('exe') / self.uuid
        self.exe_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.exe_dir.parent, ignore_errors=True)

    @patch('rdgenerator.views.requests.get')
    def test_download_accepts_new_macos_name_when_old_file_exists(self, mock_get):
        mock_get.side_effect = requests.RequestException('network error')
        old_name = 'jutze-remote-desktop-aarch64.dmg'
        requested_name = 'jutze-remote-desktop-macos-aarch64.dmg'
        expected_bytes = b'test dmg payload'
        (self.exe_dir / old_name).write_bytes(expected_bytes)

        response = self.client.get(
            '/download',
            {'filename': requested_name, 'uuid': self.uuid},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, expected_bytes)
        self.assertIn(requested_name, response['Content-Disposition'])


@override_settings(
    JFROG_URL='https://bin.jutze.cn/artifactory',
    JFROG_TEMP_REPO_PATH='build-resources/rustdesk',
    JFROG_ARTIFACT_REPO_PATH='releases/rustdesk',
)
class JFrogTempResourceTests(SimpleTestCase):
    def setUp(self):
        self.client = Client()

    @patch('rdgenerator.views.requests.put')
    def test_save_png_uploads_to_jfrog(self, mock_put):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_put.return_value = mock_response

        image = SimpleUploadedFile('icon.png', b'png-bytes', content_type='image/png')
        result = save_png(image, 'uuid-123', 'https://rd.jutze.cn', 'icon.png')

        self.assertEqual(result, ('https://rd.jutze.cn', 'uuid-123', 'icon.png'))
        mock_put.assert_called_once()
        self.assertEqual(
            mock_put.call_args.args[0],
            'https://bin.jutze.cn/artifactory/build-resources/rustdesk/uuid-123/icon.png',
        )
        self.assertEqual(mock_put.call_args.kwargs['data'], b'png-bytes')

    @patch('rdgenerator.views.requests.get')
    def test_get_png_reads_from_jfrog(self, mock_get):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'png-bytes'
        mock_response.headers = {'Content-Type': 'image/png'}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        response = self.client.get('/get_png', {'uuid': 'uuid-123', 'filename': 'icon.png'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'png-bytes')
        mock_get.assert_called_once()
        self.assertEqual(
            mock_get.call_args.args[0],
            'https://bin.jutze.cn/artifactory/build-resources/rustdesk/uuid-123/icon.png',
        )

    @patch('rdgenerator.views.requests.delete')
    def test_cleanup_secrets_deletes_jfrog_temp_folder(self, mock_delete):
        mock_response = Mock()
        mock_response.status_code = 204
        mock_delete.return_value = mock_response

        response = self.client.post(
            '/cleanzip',
            data=json.dumps({'uuid': 'uuid-123'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        mock_delete.assert_called_once()
        self.assertEqual(
            mock_delete.call_args.args[0],
            'https://bin.jutze.cn/artifactory/build-resources/rustdesk/uuid-123',
        )

    @patch('rdgenerator.views.requests.put')
    def test_save_custom_client_uploads_to_jfrog_artifact_repo(self, mock_put):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_put.return_value = mock_response

        binary = SimpleUploadedFile(
            'jutze-remote-desktop-macos-aarch64.dmg',
            b'dmg-bytes',
            content_type='application/x-apple-diskimage',
        )
        response = self.client.post(
            '/save_custom_client',
            {'uuid': 'uuid-123', 'file': binary},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_put.call_args.args[0],
            'https://bin.jutze.cn/artifactory/releases/rustdesk/uuid-123/jutze-remote-desktop-macos-aarch64.dmg',
        )
        self.assertEqual(mock_put.call_args.kwargs['data'], b'dmg-bytes')

    @patch('rdgenerator.views.requests.get')
    def test_download_reads_from_jfrog_artifact_repo(self, mock_get):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'dmg-bytes'
        mock_response.headers = {'Content-Type': 'application/x-apple-diskimage'}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        response = self.client.get(
            '/download',
            {'uuid': 'uuid-123', 'filename': 'jutze-remote-desktop-macos-aarch64.dmg'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'dmg-bytes')
        self.assertEqual(
            mock_get.call_args.args[0],
            'https://bin.jutze.cn/artifactory/releases/rustdesk/uuid-123/jutze-remote-desktop-macos-aarch64.dmg',
        )

    @patch('rdgenerator.views.requests.get')
    def test_download_falls_back_to_local_when_jfrog_unavailable(self, mock_get):
        mock_get.side_effect = requests.RequestException('network error')
        uuid = 'test-uuid-local'
        exe_dir = Path('exe') / uuid
        exe_dir.mkdir(parents=True, exist_ok=True)
        try:
            requested_name = 'jutze-remote-desktop-macos-aarch64.dmg'
            old_name = 'jutze-remote-desktop-aarch64.dmg'
            expected_bytes = b'local dmg payload'
            (exe_dir / old_name).write_bytes(expected_bytes)

            response = self.client.get(
                '/download',
                {'filename': requested_name, 'uuid': uuid},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, expected_bytes)
        finally:
            shutil.rmtree(exe_dir.parent, ignore_errors=True)
