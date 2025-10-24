import json
import os.path
import unittest

from pygeoapi import flask_app


class PyGeoAPIServerTests(unittest.TestCase):

    def setUp(self):
        self.client = flask_app.APP.test_client()
        self.raster_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), 'test_data/carbon_willamette.invs.json'))

    def tearDown(self):
        pass

    def testExecuteProcessMetadata(self):
        response = self.client.get(f'/processes/execute')
        self.assertEqual(response.status_code, 200)

    def testExecuteProcessExecution(self):
        response = self.client.post(f'/processes/execute/execution', json={
            'inputs': {
                'datastack_path': self.raster_path
            }
        })
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        print(data)
        self.assertEqual(set(data.keys()), 'workspace')
        self.assertEqual(
            set(os.listdir(data['workspace'])),
            {'stdout.log', 'stderr.log', 'script.slurm', 'carbon_workspace'}
        )

    def testValidateProcessMetadata(self):
        response = self.client.get(f'/processes/validate')
        self.assertEqual(response.status_code, 200)

    def testValidateProcessExecution(self):
        """Validation of a datastack should return validation messages"""
        response = self.client.post(f'/processes/validate/execution', json={
            'inputs': {
                'datastack_path': self.raster_path
            }
        })
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(set(data.keys()), {'validation_results', 'workspace'})
        self.assertEqual(
            data['validation_results'],
            [{
                'input_ids': ['workspace_dir'],
                'error_message': 'Key is missing from the args dict'
            }]
        )
        self.assertEqual(
            set(os.listdir(data['workspace'])),
            {'stdout.log', 'stderr.log', 'script.slurm'}
        )
