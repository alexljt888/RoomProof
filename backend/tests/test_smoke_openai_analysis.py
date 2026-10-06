"""Manual harness tests: synthetic bytes/credentials, stub provider, blocked network."""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from backend.scripts import smoke_openai_analysis as smoke
from test_openai_analyzer import StubClient, image_bytes, response


class SmokeTests(unittest.TestCase):
    def setUp(self):
        for owner, name in ((socket, 'getaddrinfo'), (socket.socket, 'connect'), (socket.socket, 'connect_ex')):
            guard = patch.object(owner, name, side_effect=AssertionError('network forbidden'))
            guard.start()
            self.addCleanup(guard.stop)
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'private-image.png'
        self.path.write_bytes(image_bytes())

    def run_main(self, client=None, argv=None):
        output = io.StringIO()
        with patch.object(smoke, 'OpenAI') as factory, contextlib.redirect_stdout(output):
            factory.return_value.__enter__.return_value = client or StubClient(response())
            code = smoke.main(argv if argv is not None else [str(self.path)])
        return code, output.getvalue(), factory

    def test_import_safety(self):
        with patch('openai.OpenAI') as client, patch.object(Path, 'open', side_effect=AssertionError('no file access')):
            importlib.reload(smoke)
            client.assert_not_called()
        importlib.reload(smoke)  # Restore the real constructor binding after the import probe.

    def test_missing_and_blank_key(self):
        for key in (None, '', ' \t '):
            if key is not None:
                os.environ['OPENAI_API_KEY'] = key
            code, output, client = self.run_main()
            self.assertEqual(code, 2)
            client.assert_not_called()
            self.assertEqual(output, 'Required API key is not configured.\n')

    def test_explicit_path_required_and_argument_errors_sanitized(self):
        for args in ([], ['--unexpected-private-path']):
            with patch.object(smoke, 'OpenAI') as client, contextlib.redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit) as raised:
                    smoke.main(args)
                self.assertEqual(raised.exception.code, 2)
                self.assertNotIn('unexpected-private', err.getvalue())
                client.assert_not_called()

    def test_missing_unreadable_and_unsupported_input(self):
        os.environ['OPENAI_API_KEY'] = 'synthetic-secret'
        for path in (self.path.with_name('missing.png'), Path(self.directory.name)):
            code, output, client = self.run_main(argv=[str(path)])
            self.assertEqual(code, 2)
            self.assertNotIn(str(path), output)
            client.assert_not_called()
        self.path.write_bytes(b'private corrupt content')
        code, output, client = self.run_main()
        self.assertEqual(code, 2)
        client.assert_not_called()

    def test_success_configuration_one_call_and_safe_output(self):
        os.environ['OPENAI_API_KEY'] = 'synthetic-secret'
        client = StubClient(response())
        original = smoke.InspectionService.analyze_photo
        with patch.object(smoke, 'AnalyzerConfig', wraps=smoke.AnalyzerConfig) as config, \
             patch.object(smoke.InspectionService, 'analyze_photo', autospec=True, side_effect=original) as analyze:
            code, output, factory = self.run_main(client)
        self.assertEqual(code, 0)
        config.assert_called_once_with(model='gpt-4.1-mini-2025-04-14', max_prepared_image_bytes=20971520)
        analyze.assert_called_once()
        factory.assert_called_once_with(api_key='synthetic-secret', base_url='https://api.openai.com/v1', max_retries=0)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.options, [dict(timeout=90.0, max_retries=0)])
        request = client.calls[0]
        self.assertEqual(request['model'], smoke.MODEL)
        self.assertEqual(request['input'][0]['content'][0]['detail'], 'high')
        self.assertNotIn('max_output_tokens', request)
        data = json.loads(output)
        self.assertEqual(set(data), {'analysis_id', 'status', 'outcome', 'failure_code', 'finding_count', 'findings',
            'analyzer_id', 'analyzer_version', 'requested_model', 'provider_model', 'prompt_version', 'schema_version', 'preparation_version'})
        self.assertEqual(data['finding_count'], 1)
        finding = data['findings'][0]
        self.assertEqual(set(finding), {'category', 'surface', 'location', 'description', 'certainty', 'state', 'eligible_for_report'})
        self.assertEqual(finding['state'], 'pending_review')
        self.assertFalse(finding['eligible_for_report'])
        for private in ('synthetic-secret', str(self.path), 'private-image', 'sha256', 'base64', 'Synthetic smoke'):
            self.assertNotIn(private, output)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [self.path])

    def test_provider_failure_stops_safely_without_retry(self):
        os.environ['OPENAI_API_KEY'] = 'synthetic-secret'
        client = StubClient(error=RuntimeError('private-provider-diagnostic synthetic-secret'))
        code, output, _ = self.run_main(client)
        self.assertEqual(code, 1)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.options[0]['max_retries'], 0)
        self.assertEqual(json.loads(output)['failure_code'], 'unavailable')
        self.assertNotIn('private-provider-diagnostic', output)
        self.assertNotIn('synthetic-secret', output)

    def test_decode_failure_never_calls_provider(self):
        os.environ['OPENAI_API_KEY'] = 'synthetic-secret'
        self.path.write_bytes(b'\x89PNG\r\n\x1a\ncorrupt')
        client = StubClient(response())
        code, output, _ = self.run_main(client)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)['failure_code'], 'unreadable_image')
        self.assertFalse(client.calls)

    def test_jpeg_and_zero_findings_succeed(self):
        os.environ['OPENAI_API_KEY'] = 'synthetic-secret'
        self.path.write_bytes(image_bytes(fmt='JPEG'))
        from test_openai_analyzer import payload
        client = StubClient(response(payload('no_visible_findings', [])))
        code, output, _ = self.run_main(client)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['finding_count'], 0)
        self.assertEqual(len(client.calls), 1)

    def test_input_read_is_bounded(self):
        os.environ['OPENAI_API_KEY'] = 'synthetic-secret'
        with patch.object(smoke, 'MAX_INPUT_BYTES', 8):
            code, _, client = self.run_main()
        self.assertEqual(code, 2)
        client.assert_not_called()

    def test_client_setup_failure_is_sanitized(self):
        os.environ['OPENAI_API_KEY'] = 'synthetic-secret'
        with patch.object(smoke, 'OpenAI', side_effect=RuntimeError('synthetic-secret private diagnostic')), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            code = smoke.main([str(self.path)])
        self.assertEqual(code, 1)
        self.assertEqual(output.getvalue(), 'Smoke could not complete.\n')
