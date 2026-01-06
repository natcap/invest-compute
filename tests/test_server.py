import json
import os.path
import unittest

from pygeoapi import flask_app


class PyGeoAPIServerTests(unittest.TestCase):

    def setUp(self):
        self.client = flask_app.APP.test_client()
        self.datastack_url = 'https://github.com/natcap/invest-compute/raw/refs/heads/feature/compute-note-playbook/tests/test_data/invest_carbon_datastack.tgz'

    def tearDown(self):
        pass

    def testExecuteProcessMetadata(self):
        response = self.client.get(f'/processes/execute')
        self.assertEqual(response.status_code, 200)

    def testExecuteProcessExecutionSync(self):
        response = self.client.post(f'/processes/execute/execution', json={
            'inputs': {
                'datastack_url': self.datastack_url
            }
        })
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(set(data.keys()), {'status', 'type', 'job_id'})
        self.assertEqual(data['status'], 'successful')
        # self.assertEqual(
        #     set(os.listdir(data['workspace'])),
        #     {'stdout.log', 'stderr.log', 'script.slurm', 'carbon_workspace'}
        # )
        # curl -X POST -H "Content-Type: application/json" -d '{"inputs": {"datastack_url": "https://github.com/natcap/invest-compute/raw/refs/heads/feature/compute-note-playbook/tests/test_data/invest_carbon_datastack.tgz"}}' localhost:5000/processes/execute/execution

    def testExecuteProcessExecutionAsync(self):
        response = self.client.post(f'/processes/execute/execution',
            json={'inputs': {'datastack_url': self.datastack_url}},
            headers={'Prefer': 'respond-async'})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(set(data.keys()), {'status', 'type', 'job_id'})
        self.assertEqual(data['status'], 'accepted')
        # self.assertEqual(
        #     set(os.listdir(data['workspace'])),
        #     {'stdout.log', 'stderr.log', 'script.slurm', 'carbon_workspace'}
        # )

    def testExecuteProcessErrorSync(self):
        """Test executing a datastack that should cause a model error."""
        response = self.client.post(f'/processes/execute/execution', json={
            'inputs': {
                # this datastack includes an invalid raster path
                'datastack_url': 'https://github.com/natcap/invest-compute/raw/refs/heads/feature/compute-note-playbook/tests/test_data/invest_carbon_error_datastack.tgz'
            }
        })
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(set(data.keys()), {'status', 'type', 'job_id'})
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
                'datastack_url': self.datastack_url
            }
        })
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(set(data.keys()), {'status', 'type', 'job_id'})
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
