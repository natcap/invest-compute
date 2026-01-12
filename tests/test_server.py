import json
import os.path
import shutil
import subprocess
import tempfile
import unittest

from pygeoapi import flask_app


class PyGeoAPIServerTests(unittest.TestCase):

    def setUp(self):
        self.client = flask_app.APP.test_client()
        self.datastack_url = 'https://github.com/natcap/invest-compute/raw/refs/heads/feature/compute-note-playbook/tests/test_data/invest_carbon_datastack.tgz'
        self.workspace_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.workspace_dir)

    # def testExecuteProcessMetadata(self):
    #     response = self.client.get(f'/processes/execute')
    #     self.assertEqual(response.status_code, 200)

    def testExecuteProcessExecutionSync(self):
        """Test execution of the 'execute' process in sync mode."""
        response = self.client.post('/processes/execute/execution', json={
            'inputs': {
                'datastack_url': self.datastack_url
            }
        })
        self.assertEqual(response.status_code, 200)
        execution_response = json.loads(response.get_data(as_text=True))
        # in sync mode with default response type ("raw"), the process
        # outputs should be returned directly in the json response
        self.assertEqual(set(execution_response.keys()), {'workspace_url'})

        job_url = response.headers['Location'].split('http://localhost:5000')[1]
        job_response = json.loads(self.client.get(job_url).get_data(as_text=True))
        self.assertEqual(job_response['status'], 'successful')

        results_endpoint_response = json.loads(self.client.get(
            f'{job_url}/results?f=json').get_data(as_text=True))
        # in sync mode, the same results should be returned from the initial
        # execution endpoint and from any subsequent calls to the results endpoint
        self.assertEqual(execution_response, results_endpoint_response)

        local_dest_path = os.path.join(self.workspace_dir, 'results')
        os.mkdir(local_dest_path)
        subprocess.run([
            'gcloud', 'storage', 'cp', '--recursive',
            f'{execution_response["workspace_url"]}/*', local_dest_path
        ], check=True)
        self.assertEqual(
            set(os.listdir(local_dest_path)),
            {
                'datastack.tgz',     # datastack archive downloaded from the input url
                'datastack',         # extracted datastack directory
                'stdout.log',        # stdout from the slurm job
                'stderr.log',        # stderr from the slurm job
                'script.slurm',      # the slurm script sent to sbatch
                'carbon_workspace',  # the invest model workspace directory
                'results.json'       # json results file used by pygeoapi
            }
        )
        # curl -X POST -H "Content-Type: application/json" -d '{"inputs": {"datastack_url": "https://github.com/natcap/invest-compute/raw/refs/heads/feature/compute-note-playbook/tests/test_data/invest_carbon_datastack.tgz"}}' localhost:5000/processes/execute/execution

    def testExecuteProcessExecutionAsync(self):
        """Test execution of the 'execute' process in async mode."""
        response = self.client.post(f'/processes/execute/execution',
            json={'inputs': {'datastack_url': self.datastack_url}},
            headers={'Prefer': 'respond-async'})
        print(response.headers)
        self.assertEqual(response.status_code, 201)
        execution_response = json.loads(response.get_data(as_text=True))
        # pygeoapi incorrectly calls this key 'id' instead of 'job_id'
        # https://github.com/geopython/pygeoapi/issues/2197
        self.assertEqual(set(execution_response.keys()), {'status', 'type', 'id'})
        self.assertEqual(execution_response['status'], 'accepted')
        self.assertEqual(execution_response['type'], 'process')  # according to the OGC standard this should always be 'process'
        self.assertEqual(
            response.headers['Location'],
            f'http://localhost:5000/jobs/{execution_response["id"]}')

        # poll status until the job finishes
        # TODO: test with a longer running job
        while True:
            job_response = json.loads(self.client.get(
                f'/jobs/{execution_response["id"]}').get_data(as_text=True))
            print('status:', job_response['status'])
            self.assertNotIn(job_response['status'], {'failed', 'dismissed'})
            if job_response['status'] == 'successful':
                break

        results_response = json.loads(self.client.get(
            f'/jobs/{execution_response["id"]}/results?f=json').get_data(as_text=True))
        print('results response:', results_response)
        local_dest_path = os.path.join(self.workspace_dir, 'results')
        os.mkdir(local_dest_path)
        subprocess.run([
            'gcloud', 'storage', 'cp', '--recursive', f'{results_response["workspace_url"]}/*', local_dest_path
        ], check=True)
        self.assertEqual(
            set(os.listdir(local_dest_path)),
            {
                'datastack.tgz',     # datastack archive downloaded from the input url
                'datastack',         # extracted datastack directory
                'stdout.log',        # stdout from the slurm job
                'stderr.log',        # stderr from the slurm job
                'script.slurm',      # the slurm script sent to sbatch
                'carbon_workspace',  # the invest model workspace directory
                'results.json'       # json results file used by pygeoapi
            }
        )

    # def testExecuteProcessErrorSync(self):
    #     """Test executing a datastack that should cause a model error."""
    #     response = self.client.post(f'/processes/execute/execution', json={
    #         'inputs': {
    #             # this datastack includes an invalid raster path
    #             'datastack_url': 'https://github.com/natcap/invest-compute/raw/refs/heads/feature/compute-note-playbook/tests/test_data/invest_carbon_error_datastack.tgz'
    #         }
    #     })
    #     self.assertEqual(response.status_code, 400)
    #     data = json.loads(response.get_data(as_text=True))
    #     self.assertEqual(set(data.keys()), {'workspace_url'})

    #     local_dest_path = os.path.join(self.workspace_dir, 'results')
    #     os.mkdir(local_dest_path)
    #     subprocess.run([
    #         'gcloud', 'storage', 'cp', '--recursive', f'{data["workspace_url"]}/*', local_dest_path
    #     ], check=True)
    #     self.assertEqual(
    #         set(os.listdir(local_dest_path)),
    #         {
    #             'datastack.tgz',     # datastack archive downloaded from the input url
    #             'datastack',         # extracted datastack directory
    #             'stdout.log',        # stdout from the slurm job
    #             'stderr.log',        # stderr from the slurm job
    #             'script.slurm',      # the slurm script sent to sbatch
    #             'carbon_workspace',  # the invest model workspace directory
    #             'results.json'       # json results file used by pygeoapi
    #         }
    #     )

    #     # expect model error to be captured in stderr.log
    #     with open(os.path.join(local_dest_path, 'stderr.log')) as err_log:
    #         self.assertIn(
    #             'RuntimeError: does_not_exist.tif: No such file or directory',
    #             err_log.read())

    def testValidateProcessMetadata(self):
        response = self.client.get(f'/processes/validate')
        self.assertEqual(response.status_code, 200)

    def testValidateProcessExecutionSync(self):
        """Validation of a datastack should return validation messages"""
        response = self.client.post(f'/processes/validate/execution', json={
            'inputs': {
                'datastack_url': self.datastack_url
            }
        })
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(set(data.keys()), {'workspace_url', 'validation_results'})
        self.assertEqual(
            data['validation_results'],
            [{
                'input_ids': ['workspace_dir'],
                'error_message': 'Key is missing from the args dict'
            }]
        )

        local_dest_path = os.path.join(self.workspace_dir, 'results')
        os.mkdir(local_dest_path)
        subprocess.run([
            'gcloud', 'storage', 'cp', '--recursive', f'{data["workspace_url"]}/*', local_dest_path
        ], check=True)
        self.assertEqual(
            set(os.listdir(local_dest_path)),
            {
                'datastack.tgz',     # datastack archive downloaded from the input url
                'datastack',         # extracted datastack directory
                'stdout.log',        # stdout from the slurm job
                'stderr.log',        # stderr from the slurm job
                'script.slurm',      # the slurm script sent to sbatch
                'results.json'       # json results file used by pygeoapi
            }
        )
