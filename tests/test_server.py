import json
import os.path
import unittest

class PyGeoAPIServerTests(unittest.TestCase):

    def setUp(self):
        # Import current pygeoapi Flask app module
        from pygeoapi import flask_app
        self.client = flask_app.APP.test_client()

    def tearDown(self):
        pass

    def testExecuteProcessMetadata(self):
        response = self.client.get(f'/processes/execute')
        self.assertEqual(response.status_code, 200)

    def testExecuteProcessExecution(self):
        path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), 'test_data/carbon_willamette.invs.json'))
        response = self.client.post(f'/processes/execute/execution', json={
            'inputs': {
                'datastack_path': path
            }
        })
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertTrue(os.path.exists(data['workspace_dir']))

    def testValidateProcessMetadata(self):
        response = self.client.get(f'/processes/validate')
        self.assertEqual(response.status_code, 200)

    def testValidateProcessExecution(self):
        """Validation of a datastack should return validation messages"""
        path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), 'test_data/carbon_willamette.invs.json'))
        response = self.client.post(f'/processes/validate/execution', json={
            'inputs': {
                'datastack_path': path
            }
        })
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(data, {
            'validation_errors': [
                {
                    'input_ids': ['workspace_dir'],
                    'error_message': 'Key is missing from the args dict'
                }
            ]
        })
