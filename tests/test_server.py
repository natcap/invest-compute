import json
import os.path
import unittest

from pygeoapi import flask_app


class PyGeoAPIServerTests(unittest.TestCase):

    def setUp(self):
        self.client = flask_app.APP.test_client()
        self.datastack_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), 'test_data/carbon_willamette.invs.json'))

    def tearDown(self):
        pass

    def testExecuteProcessMetadata(self):
        response = self.client.get(f'/processes/execute')
        self.assertEqual(response.status_code, 200)

    def testExecuteProcessExecution(self):
        response = self.client.post(f'/processes/execute/execution', json={
            'inputs': {
                'datastack_path': self.datastack_path
            }
        })
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(set(data.keys()), {'workspace'})
        self.assertEqual(
            set(os.listdir(data['workspace'])),
            {'stdout.log', 'stderr.log', 'script.slurm', 'carbon_workspace'}
        )
        # curl -X POST -H "Content-Type: application/json" -d '{"inputs": {"datastack_path": "tests/test_data/carbon_willamette.invs.json"}}' localhost:5000/processes/execute/execution

    def testExecuteProcessError(self):
        """Test executing a datastack that should cause a model error."""
        response = self.client.post(f'/processes/execute/execution', json={
            'inputs': {
                # this datastack includes an invalid raster path
                'datastack_path': os.path.abspath(os.path.join(
                    os.path.dirname(__file__), 'test_data/carbon_error.invs.json'))
            }
        })
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(set(data.keys()), {'workspace'})
        self.assertEqual(
            set(os.listdir(data['workspace'])),
            {'stdout.log', 'stderr.log', 'script.slurm', 'carbon_workspace'}
        )
        # expect model error to be captured in stderr.log
        with open(os.path.join(data['workspace'], 'stderr.log')) as err_log:
            self.assertIn(
                'RuntimeError: does_not_exist.tif: No such file or directory',
                err_log.read())

    def testValidateProcessMetadata(self):
        response = self.client.get(f'/processes/validate')
        self.assertEqual(response.status_code, 200)

    def testValidateProcessExecution(self):
        """Validation of a datastack should return validation messages"""
        response = self.client.post(f'/processes/validate/execution', json={
            'inputs': {
                'datastack_path': self.datastack_path
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
